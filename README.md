# mtg-data

Sync infrastructure for Matty's MTG collection (ManaBox) and Scryfall card
data into Supabase. Run from a desktop terminal.

## Setup

```bash
cp .env.example .env      # then fill in SUPABASE_DB_URL
pip install -r requirements.txt
```

The scripts need one credential, `SUPABASE_DB_URL` — the project's direct
Postgres connection string (see `.env.example`).

## Syncing

Order matters: `collection` has a foreign key into `cards`, so sync Scryfall
first.

```bash
# 1. Full Scryfall "default_cards" bulk data -> cards table
#    (downloads ~500MB+ to data/, streams it, upserts in batches)
python scripts/sync_scryfall.py

# 2. ManaBox CSV export -> collection table
#    --prune deletes rows no longer in the export, keeping the table an
#    exact mirror of ManaBox (omit it to only add/update)
python scripts/sync_manabox.py path/to/ManaBox_Collection.csv --prune

# Preview what a ManaBox sync would do without touching the database:
python scripts/sync_manabox.py path/to/ManaBox_Collection.csv --dry-run

# Re-running sync_scryfall.py later can reuse the downloaded file:
python scripts/sync_scryfall.py --file data/default-cards.json
```

Both scripts are idempotent — re-run them freely after each ManaBox scan
session or when Scryfall data goes stale. Without `--prune`, entries removed
from ManaBox stay in `collection`; with it, they're deleted and the sync
reports what was pruned.

Run `sync_scryfall.py` rarely (new set releases, stale data); run
`sync_manabox.py` after every scan session.

## Database

Schema lives in `migrations/` as numbered SQL files — every schema change is
a new file, applied to the Supabase project (ref `heiyckeurcfjpnhmsjfo`) via
the SQL editor or MCP `apply_migration`, never ad-hoc.

RLS is enabled on all tables with no anon policies: the REST API is locked
until the multi-user web app (see `PLAN.md`) adds real auth. The sync scripts
are unaffected — a direct Postgres connection bypasses RLS.
