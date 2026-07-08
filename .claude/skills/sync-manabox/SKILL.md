---
name: sync-manabox
description: Sync a freshly-exported ManaBox collection CSV into the Supabase `collection` table. Use whenever Matty says he's updated his ManaBox collection, exported a new CSV, or wants his collection synced/refreshed. Runs from a desktop terminal.
---

Run this after Matty exports a new collection CSV from the ManaBox app.

## Steps

1. **Get the CSV.** If Matty attached/pasted a file in this conversation, use
   that. Otherwise ask him to export from ManaBox (Collection → Export → CSV)
   and give a path.

2. **Check for credentials.** The script needs `SUPABASE_DB_URL` in the
   local `.env` (see `.env.example`). If it fails with a missing-env error,
   point Matty at the README setup section.

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

5. **Report the summary** (`inserted`, `updated`, `skipped`, `pruned`) back
   to Matty in plain terms — e.g. "Added 12 new cards, updated 3, removed 5
   that are no longer in your ManaBox export." If `skipped` or `pruned` is
   nonzero, mention a couple of names from the printed samples so he knows
   what changed, not just a count.

6. Do **not** run `sync_scryfall.py` as part of this routine — Matty updates
   that separately and rarely. Only mention it if the sync reports skipped
   entries (a sign Scryfall data is stale).
