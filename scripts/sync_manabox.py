"""Sync a ManaBox collection export into the Supabase `collection` table.

Parses a ManaBox CSV export and upserts into `collection`, keyed on the
table's unique constraint (scryfall_id, foil, binder_name). Duplicate keys
within the CSV have their quantities summed. Rows whose printing isn't in
`cards` yet are skipped with a warning — run sync_scryfall.py first.

With --prune, collection rows whose key is absent from the CSV are deleted
afterwards, making the table an exact mirror of the export.

Talks to Supabase over HTTPS (the REST/PostgREST API via supabase-py)
rather than a raw Postgres connection, so this runs the same from a desktop
`.env` session or a remote/mobile Claude Code session where only outbound
HTTPS is allowed — unlike sync_scryfall.py, which needs a direct DB
connection and is desktop-only.

Usage:
    python scripts/sync_manabox.py path/to/ManaBox_Collection.csv
    python scripts/sync_manabox.py path/to/export.csv --prune
    python scripts/sync_manabox.py path/to/export.csv --dry-run
"""
import argparse
import csv
import sys
from pathlib import Path

from supabase import create_client

import config

COLUMNS = (
    "scryfall_id", "name", "set_code", "collector_number", "foil",
    "quantity", "condition", "language", "binder_name", "binder_type",
    "purchase_price",
)
BATCH_SIZE = 500
# PostgREST builds `in_()` filters as a query string, so keep chunks well
# under any URL-length limit.
FETCH_CHUNK_SIZE = 200

# ManaBox foil column values: "normal", "foil", "etched". The collection
# table only tracks a boolean, so any special treatment counts as foil.
NONFOIL_VALUES = {"normal", ""}


def parse_csv(path: Path) -> list[dict]:
    """Read a ManaBox export, aggregating duplicate (id, foil, binder) keys."""
    entries: dict[tuple, dict] = {}
    skipped_no_id = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sid = (row.get("Scryfall ID") or "").strip()
            if not sid:
                skipped_no_id += 1
                continue
            foil = row.get("Foil", "").strip().lower() not in NONFOIL_VALUES
            qty = int(row.get("Quantity") or 1)
            key = (sid, foil, row.get("Binder Name", ""))
            if key in entries:
                entries[key]["quantity"] += qty
                continue
            price = (row.get("Purchase price") or "").strip()
            entries[key] = {
                "scryfall_id": sid,
                "name": row["Name"],
                "set_code": row.get("Set code"),
                "collector_number": row.get("Collector number"),
                "foil": foil,
                "quantity": qty,
                "condition": row.get("Condition"),
                "language": row.get("Language"),
                "binder_name": row.get("Binder Name", ""),
                "binder_type": row.get("Binder Type"),
                "purchase_price": float(price) if price else None,
            }
    if skipped_no_id:
        print(f"warning: skipped {skipped_no_id} CSV rows with no Scryfall ID")
    return list(entries.values())


def chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def fetch_known_scryfall_ids(client, scryfall_ids: list[str]) -> set[str]:
    """Return the subset of scryfall_ids present in `cards`."""
    known: set[str] = set()
    for chunk in chunks(sorted(set(scryfall_ids)), FETCH_CHUNK_SIZE):
        resp = client.table("cards").select("scryfall_id").in_("scryfall_id", chunk).execute()
        known.update(row["scryfall_id"] for row in resp.data)
    return known


def fetch_existing_collection(client) -> dict[tuple, dict]:
    """Return {(scryfall_id, foil, binder_name): row} for every current row,
    where row has "id", "name", "set_code" for prune reporting.
    """
    existing: dict[tuple, dict] = {}
    page_size = 1000
    offset = 0
    while True:
        resp = (
            client.table("collection")
            .select("id, scryfall_id, foil, binder_name, name, set_code")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        for row in resp.data:
            existing[(row["scryfall_id"], row["foil"], row["binder_name"])] = row
        if len(resp.data) < page_size:
            break
        offset += page_size
    return existing


def upsert_entries(client, entries: list[dict], existing: dict[tuple, dict]) -> tuple[int, int]:
    """Upsert all entries; return (inserted, updated) counts."""
    inserted = updated = 0
    for entry in entries:
        key = (entry["scryfall_id"], entry["foil"], entry["binder_name"])
        if key in existing:
            updated += 1
        else:
            inserted += 1
    for batch in chunks(entries, BATCH_SIZE):
        rows = [{c: e[c] for c in COLUMNS} for e in batch]
        client.table("collection").upsert(
            rows, on_conflict="scryfall_id,foil,binder_name"
        ).execute()
    return inserted, updated


def prune(client, entries: list[dict], existing: dict[tuple, dict]) -> list[dict]:
    """Delete collection rows whose (scryfall_id, foil, binder_name) key is
    not in the CSV. Returns the deleted rows for reporting.
    """
    keep_keys = {(e["scryfall_id"], e["foil"], e["binder_name"]) for e in entries}
    to_delete = [row for key, row in existing.items() if key not in keep_keys]
    if not to_delete:
        return []
    ids = [row["id"] for row in to_delete]
    for id_chunk in chunks(ids, FETCH_CHUNK_SIZE):
        client.table("collection").delete().in_("id", id_chunk).execute()
    return to_delete


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path", type=Path, help="ManaBox CSV export")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and summarize without touching the database")
    ap.add_argument("--prune", action="store_true",
                    help="delete collection rows not present in the CSV")
    args = ap.parse_args()

    entries = parse_csv(args.csv_path)
    total_qty = sum(e["quantity"] for e in entries)
    binders = sorted({(e["binder_name"], e["binder_type"]) for e in entries})
    print(f"parsed {len(entries)} collection entries ({total_qty} cards) "
          f"across {len(binders)} binders/decks")

    if args.dry_run:
        for name, btype in binders:
            n = sum(e["quantity"] for e in entries if e["binder_name"] == name)
            print(f"  [{btype}] {name}: {n} cards")
        print("dry run — no database changes made")
        return 0

    client = create_client(
        config.require("SUPABASE_URL"), config.require("SUPABASE_SERVICE_ROLE_KEY")
    )

    # The FK to cards(scryfall_id) makes unknown printings fail the whole
    # batch, so check first and skip them with a useful message instead.
    known = fetch_known_scryfall_ids(client, [e["scryfall_id"] for e in entries])
    # Prune keeps everything in the CSV — including entries skipped below
    # for a missing cards row — so only cards removed in ManaBox go away.
    keep = entries
    missing = [e for e in entries if e["scryfall_id"] not in known]
    entries = [e for e in entries if e["scryfall_id"] in known]

    if missing:
        print(f"warning: {len(missing)} entries not found in cards table "
              "— run sync_scryfall.py first. Skipped:")
        for e in missing[:10]:
            print(f"  {e['name']} ({e['set_code']} #{e['collector_number']})")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")
    if not entries:
        print("error: nothing to sync — cards table has none of these printings")
        return 1

    existing = fetch_existing_collection(client)
    inserted, updated = upsert_entries(client, entries, existing)
    pruned = prune(client, keep, existing) if args.prune else []

    if pruned:
        print(f"pruned {len(pruned)} rows no longer in the export:")
        for row in pruned[:10]:
            print(f"  {row['name']} ({row['set_code']}) from {row['binder_name']}")
        if len(pruned) > 10:
            print(f"  ... and {len(pruned) - 10} more")

    print(f"collection: {inserted} inserted, {updated} updated, "
          f"{len(missing)} skipped, {len(pruned)} pruned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
