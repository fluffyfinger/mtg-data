---
name: sync-manabox
description: Sync a freshly-exported ManaBox collection CSV into the Supabase `collection` table. Use whenever Matty says he's updated his ManaBox collection, exported a new CSV, or wants his collection synced/refreshed — on desktop or the mobile/web Claude Code app.
---

Run this after Matty exports a new collection CSV from the ManaBox app.

## Steps

1. **Get the CSV.** If Matty attached/pasted a file in this conversation, use that.
   Otherwise ask him to export from ManaBox (Collection → Export → CSV) and
   attach it or give a path.

2. **Check for credentials.** The script needs `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL` in the environment — either
   from a local `.env` (desktop) or environment secrets (mobile/remote). If
   `python scripts/sync_manabox.py` fails with a missing-env error, tell Matty
   to check his Claude Code environment secrets rather than trying to create
   a `.env` in a remote session.

3. **Dry-run first if the diff looks big.** If this is the first sync in a
   while, or Matty seems unsure what changed, run with `--dry-run` first and
   summarize what would change before running for real.

4. **Run the sync with `--prune`:**
   ```bash
   python scripts/sync_manabox.py <path-to-csv> --prune
   ```
   `--prune` keeps `collection` an exact mirror of the ManaBox export —
   correct for routine re-syncs after a scan session, since anything Matty
   removed from ManaBox should disappear from the DB too.

5. **Report the summary line** (`inserted`, `updated`, `skipped`, `pruned`)
   back to Matty in plain terms — e.g. "Added 12 new cards, updated 3,
   removed 5 that are no longer in your ManaBox export."

6. Do **not** run `sync_scryfall.py` as part of this routine — Matty updates
   that separately and rarely. Only mention it if the ManaBox sync reports
   collection rows that fail to join to `cards` (a sign Scryfall data is
   stale).
