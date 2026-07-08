"""Sync a ManaBox collection export into the Supabase `collection` table.

Parses a ManaBox CSV export and upserts into `collection`, keyed on the
table's unique constraint (scryfall_id, foil, binder_name). Duplicate keys
within the CSV have their quantities summed. Rows whose printing isn't in
`cards` yet are skipped with a warning — run sync_scryfall.py first.

With --prune, collection rows whose key is absent from the CSV are deleted
afterwards, making the table an exact mirror of the export.

The whole sync runs as one SQL statement over a direct Postgres connection
(SUPABASE_DB_URL, same as sync_scryfall.py), so upsert + prune are atomic
and the reported counts come from the database itself.

Usage:
    python scripts/sync_manabox.py path/to/ManaBox_Collection.csv
    python scripts/sync_manabox.py path/to/export.csv --prune
    python scripts/sync_manabox.py path/to/export.csv --dry-run
"""
import argparse
import csv
import sys
from pathlib import Path

import psycopg

import config

# Card/binder names can contain non-ASCII characters (accents, em dashes,
# etc.); Windows consoles often default stdout to a non-UTF-8 codepage,
# which silently mangles them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

COLUMNS = (
    "scryfall_id", "name", "set_code", "collector_number", "foil",
    "quantity", "condition", "language", "binder_name", "binder_type",
    "purchase_price",
)

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


def sql_literal(value) -> str:
    """Render a Python value as a SQL literal for inlining into the statement."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def build_sql(entries: list[dict], prune_flag: bool) -> str:
    """Build one self-contained SQL statement that upserts `entries` into
    `collection` (skipping printings missing from `cards`) and, if
    prune_flag, deletes collection rows whose key isn't in `entries`.

    Everything happens in one `with` statement so upsert + prune run as a
    single round trip and a single implicit transaction, and the summary
    counts come straight from the writes themselves.
    """
    values_rows = []
    for e in entries:
        vals = ", ".join(sql_literal(e[c]) for c in COLUMNS)
        values_rows.append(f"({vals})")

    prune_cte = ""
    prune_select = "0 as pruned, '' as pruned_sample"
    if prune_flag:
        prune_cte = """,
pruned as (
  delete from collection c
  where not exists (
    select 1 from entries e
    where c.scryfall_id = e.scryfall_id::uuid
      and c.foil = e.foil::boolean
      and c.binder_name = e.binder_name
  )
  returning name, set_code, binder_name
)"""
        prune_select = (
            "(select count(*) from pruned) as pruned, "
            "(select coalesce(string_agg(name || ' (' || coalesce(set_code, '') || ') from ' "
            "|| binder_name, '; '), '') from (select * from pruned limit 10) p) as pruned_sample"
        )

    return f"""with entries({', '.join(COLUMNS)}) as (
  values
    {','.join(values_rows)}
),
known as (
  select e.* from entries e
  where exists (select 1 from cards c where c.scryfall_id = e.scryfall_id::uuid)
),
upserted as (
  insert into collection ({', '.join(COLUMNS)})
  select scryfall_id::uuid, name, set_code, collector_number, foil::boolean,
         quantity::int, condition, language, binder_name, binder_type,
         purchase_price::numeric
  from known
  on conflict (scryfall_id, foil, binder_name) do update set
    name = excluded.name,
    set_code = excluded.set_code,
    collector_number = excluded.collector_number,
    quantity = excluded.quantity,
    condition = excluded.condition,
    language = excluded.language,
    binder_type = excluded.binder_type,
    purchase_price = excluded.purchase_price,
    last_synced = now()
  returning (xmax = 0) as is_insert
){prune_cte}
select
  (select count(*) from entries) as parsed,
  (select count(*) from entries) - (select count(*) from known) as skipped,
  (select coalesce(string_agg(name || ' (' || coalesce(set_code, '') || ' #' || coalesce(collector_number, '') || ')', ', '), '')
     from (select * from entries e where not exists (select 1 from cards c where c.scryfall_id = e.scryfall_id::uuid) limit 10) m
  ) as skipped_sample,
  (select count(*) filter (where is_insert) from upserted) as inserted,
  (select count(*) filter (where not is_insert) from upserted) as updated,
  {prune_select};
"""


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

    if not entries:
        print("error: nothing to sync — the CSV has no usable rows")
        return 1

    if args.dry_run:
        for name, btype in binders:
            n = sum(e["quantity"] for e in entries if e["binder_name"] == name)
            print(f"  [{btype}] {name}: {n} cards")
        print("dry run — no database changes made")
        return 0

    db_url = config.require("SUPABASE_DB_URL")
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(build_sql(entries, args.prune))
        row = cur.fetchone()
        cols = [d.name for d in cur.description]
        summary = dict(zip(cols, row))
        conn.commit()

    if summary["skipped"]:
        print(f"warning: {summary['skipped']} entries not found in cards table "
              "— run sync_scryfall.py first. Skipped:")
        print(f"  {summary['skipped_sample']}")
    if summary["pruned"]:
        print(f"pruned {summary['pruned']} rows no longer in the export:")
        print(f"  {summary['pruned_sample']}")

    print(f"collection: {summary['inserted']} inserted, {summary['updated']} updated, "
          f"{summary['skipped']} skipped, {summary['pruned']} pruned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
