"""Sync a ManaBox collection export into the Supabase `collection` table.

Parses a ManaBox CSV export and upserts into `collection`, keyed on the
table's unique constraint (scryfall_id, foil, binder_name). Duplicate keys
within the CSV have their quantities summed. Rows whose printing isn't in
`cards` yet are skipped with a warning — run sync_scryfall.py first.

Usage:
    python scripts/sync_manabox.py path/to/ManaBox_Collection.csv
    python scripts/sync_manabox.py path/to/export.csv --dry-run
"""
import argparse
import csv
import sys
from pathlib import Path

import psycopg

import config

COLUMNS = (
    "scryfall_id", "name", "set_code", "collector_number", "foil",
    "quantity", "condition", "language", "binder_name", "binder_type",
    "purchase_price",
)
UPSERT_SET = ", ".join(f"{c} = excluded.{c}" for c in COLUMNS[1:]) + ", last_synced = now()"
BATCH_SIZE = 500

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


def upsert_batch(cur, batch: list[dict]) -> tuple[int, int]:
    """Upsert one batch; return (inserted, updated) counts via the xmax trick."""
    placeholders = "(" + ", ".join(["%s"] * len(COLUMNS)) + ")"
    stmt = (
        f"insert into collection ({', '.join(COLUMNS)}) values "
        + ", ".join([placeholders] * len(batch))
        + " on conflict (scryfall_id, foil, binder_name) do update set "
        + UPSERT_SET
        + " returning (xmax = 0)"
    )
    cur.execute(stmt, [e[c] for e in batch for c in COLUMNS])
    inserted = sum(1 for (is_insert,) in cur.fetchall() if is_insert)
    return inserted, len(batch) - inserted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path", type=Path, help="ManaBox CSV export")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and summarize without touching the database")
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

    db_url = config.require("SUPABASE_DB_URL")
    inserted = updated = 0
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        # The FK to cards(scryfall_id) makes unknown printings fail the whole
        # batch, so check first and skip them with a useful message instead.
        cur.execute(
            "select scryfall_id::text from cards where scryfall_id = any(%s::uuid[])",
            ([e["scryfall_id"] for e in entries],),
        )
        known = {row[0] for row in cur.fetchall()}
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

        for start in range(0, len(entries), BATCH_SIZE):
            i, u = upsert_batch(cur, entries[start:start + BATCH_SIZE])
            inserted += i
            updated += u
        conn.commit()

    print(f"collection: {inserted} inserted, {updated} updated, "
          f"{len(missing)} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
