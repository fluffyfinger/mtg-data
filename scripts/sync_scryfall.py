"""Sync Scryfall bulk card data into the Supabase `cards` table.

Downloads Scryfall's "default_cards" bulk export (every printing of every
card — multiple rows per oracle_id is intentional) and batch-upserts it into
`cards` keyed on scryfall_id. Credentials come from the environment via
config.py (local .env or injected secrets); see .env.example.

Usage:
    python scripts/sync_scryfall.py                 # download and sync
    python scripts/sync_scryfall.py --file FILE     # reuse a downloaded bulk JSON
    python scripts/sync_scryfall.py --batch-size N  # rows per upsert (default 1000)
"""
import argparse
import sys
from pathlib import Path

import ijson
import psycopg
import requests
from psycopg.types.json import Jsonb

import config

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
# Scryfall's API guidelines require an identifying User-Agent and Accept header.
HEADERS = {"User-Agent": "mtg-data-sync/1.0", "Accept": "application/json"}
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COLUMNS = (
    "scryfall_id", "oracle_id", "name", "mana_cost", "cmc", "type_line",
    "oracle_text", "power", "toughness", "color_identity", "colors",
    "keywords", "set_code", "collector_number", "rarity", "legalities",
)
UPSERT_SET = ", ".join(f"{c} = excluded.{c}" for c in COLUMNS[1:]) + ", updated_at = now()"


def download_bulk() -> Path:
    """Download the default_cards bulk file to data/ and return its path."""
    index = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    index.raise_for_status()
    entry = next(e for e in index.json()["data"] if e["type"] == "default_cards")
    size_mb = entry["size"] / 1024 / 1024
    print(f"Downloading default_cards ({size_mb:.0f} MB compressed on the wire)...")

    DATA_DIR.mkdir(exist_ok=True)
    dest = DATA_DIR / "default-cards.json"
    with requests.get(entry["download_uri"], headers=HEADERS, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        written = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                written += len(chunk)
                if written % (200 << 20) < (1 << 20):
                    print(f"  ... {written >> 20} MB")
    print(f"Downloaded to {dest} ({written >> 20} MB)")
    return dest


def card_to_row(card: dict) -> tuple:
    """Map one Scryfall card object to a `cards` row.

    Double-faced/split cards keep text on card_faces rather than the top
    level; join face values so oracle text and costs are still queryable.
    """
    faces = card.get("card_faces") or []

    def face_join(key: str, sep: str = " // "):
        if card.get(key) is not None:
            return card[key]
        vals = [f[key] for f in faces if f.get(key)]
        return sep.join(vals) if vals else None

    colors = card.get("colors")
    if colors is None and faces:
        colors = []
        for f in faces:
            for c in f.get("colors") or []:
                if c not in colors:
                    colors.append(c)

    return (
        card["id"],
        card.get("oracle_id"),
        card["name"],
        face_join("mana_cost"),
        card.get("cmc"),
        card.get("type_line"),
        face_join("oracle_text", "\n//\n"),
        face_join("power"),
        face_join("toughness"),
        card.get("color_identity"),
        colors,
        card.get("keywords"),
        card.get("set"),
        card.get("collector_number"),
        card.get("rarity"),
        Jsonb(card.get("legalities") or {}),
    )


def upsert_batch(cur, rows: list[tuple]) -> tuple[int, int]:
    """Upsert one batch; return (inserted, updated) counts via the xmax trick."""
    placeholders = "(" + ", ".join(["%s"] * len(COLUMNS)) + ")"
    stmt = (
        f"insert into cards ({', '.join(COLUMNS)}) values "
        + ", ".join([placeholders] * len(rows))
        + f" on conflict (scryfall_id) do update set {UPSERT_SET}"
        + " returning (xmax = 0)"
    )
    cur.execute(stmt, [v for row in rows for v in row])
    inserted = sum(1 for (is_insert,) in cur.fetchall() if is_insert)
    return inserted, len(rows) - inserted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, help="already-downloaded bulk JSON to use")
    ap.add_argument("--batch-size", type=int, default=1000)
    args = ap.parse_args()

    db_url = config.require("SUPABASE_DB_URL")
    path = args.file or download_bulk()

    inserted = updated = 0
    with psycopg.connect(db_url) as conn, conn.cursor() as cur, open(path, "rb") as f:
        batch: list[tuple] = []
        for card in ijson.items(f, "item"):
            batch.append(card_to_row(card))
            if len(batch) >= args.batch_size:
                i, u = upsert_batch(cur, batch)
                conn.commit()  # commit per batch so a crash keeps progress
                inserted += i
                updated += u
                batch.clear()
                if (inserted + updated) % 25000 < args.batch_size:
                    print(f"  ... {inserted + updated} cards processed")
        if batch:
            i, u = upsert_batch(cur, batch)
            conn.commit()
            inserted += i
            updated += u

    print(f"cards: {inserted} inserted, {updated} updated, {inserted + updated} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
