# mtg-data

Sync infrastructure for Matty's MTG collection (ManaBox) and Scryfall card data into Supabase.

## Credentials

The scripts read three values from the environment (see `.env.example`):

| Key | Purpose |
| --- | --- |
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Full read/write key — keep secret |
| `SUPABASE_DB_URL` | Direct Postgres connection string |

`scripts/config.py` loads these the same way everywhere, so the same code runs
locally and in a remote/mobile session:

**Local dev** — copy the template and fill it in (the `.env` file is gitignored):

```bash
cp .env.example .env      # then edit .env with your values
pip install -r requirements.txt
```

**Remote / Claude Code on the web / mobile** — do *not* use a `.env` file. Add
the three keys as **environment secrets** in the Claude Code environment
settings. Every remote session then gets them injected automatically, so syncs
and card lookups work from your phone without your machine being on. (Supabase
itself is always-on cloud infrastructure — nothing here depends on a local
server.)

Usage in code:

```python
import config
url = config.require("SUPABASE_URL")   # raises a clear error if unset
```

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

Both scripts are idempotent upserts — re-run them freely after each ManaBox
scan session or when Scryfall data goes stale. Without `--prune`, entries
removed from ManaBox stay in `collection`; with it, they're deleted and the
sync reports what was pruned.

### Desktop-only vs. works-anywhere

`sync_scryfall.py` uses a direct Postgres connection (`SUPABASE_DB_URL`),
which needs raw TCP on port 5432. That's fine on a desktop network but is
blocked in most remote/mobile sandboxes, which only permit outbound HTTPS —
so **run Scryfall syncs from your desktop.** It's also a large, slow,
infrequent operation, which fits desktop better anyway.

`sync_manabox.py` talks to Supabase over HTTPS instead (the REST API via
`supabase-py`, using `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`), so it
runs the same from desktop or a remote/mobile Claude Code session — export a
CSV from ManaBox on your phone and sync straight from there.
