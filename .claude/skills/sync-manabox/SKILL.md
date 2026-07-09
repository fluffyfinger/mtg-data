---
name: sync-manabox
description: Sync a freshly-exported ManaBox collection CSV into the Supabase `collection` table. Use whenever Matty says he's updated his ManaBox collection, exported a new CSV, or wants his collection synced/refreshed — on desktop or the mobile/web Claude Code app.
---

Run this after Matty exports a new collection CSV from the ManaBox app.

## Steps

1. **Get the CSV.** If Matty attached/pasted a file in this conversation, use that.
   Otherwise ask him to export from ManaBox (Collection → Export → CSV) and
   attach it or give a path.

2. **Check for credentials.** The script needs `SUPABASE_URL` +
   `SUPABASE_SERVICE_ROLE_KEY` in the environment — either from a local
   `.env` (desktop) or environment secrets (mobile/remote). If
   `python scripts/sync_manabox.py` fails with a missing-env error, tell
   Matty to check his Claude Code environment secrets rather than trying to
   create a `.env` in a remote session. (It does not need `SUPABASE_DB_URL`.)

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

5. **If that call fails with a 403 / `connect_rejected` / policy-denial
   error** (some remote/mobile sandboxes only allow outbound HTTPS to a
   fixed allowlist that doesn't include supabase.co — retrying won't help),
   fall back to the MCP path instead:
   ```bash
   python scripts/sync_manabox.py <path-to-csv> --emit-sql --prune
   ```
   This does the CSV parsing locally (no network call) and prints one
   self-contained SQL statement to stdout. Take that SQL verbatim and run it
   with the Supabase `execute_sql` MCP tool (project ref
   `oxpgmwiwwmehaireeqnb`), which goes through the approved MCP connector
   instead of the sandbox's blocked network egress. The query returns one
   summary row: `parsed`, `skipped`, `skipped_sample`, `inserted`, `updated`,
   `pruned`, `pruned_sample` — use it the same way as the normal run's
   summary line in step 6.

6. **Report the summary** (`inserted`, `updated`, `skipped`, `pruned`) back
   to Matty in plain terms — e.g. "Added 12 new cards, updated 3, removed 5
   that are no longer in your ManaBox export." If `skipped` or `pruned` is
   nonzero, mention a couple of names from `skipped_sample` / `pruned_sample`
   (or the printed samples in the normal-run path) so he knows what changed,
   not just a count.

7. Do **not** run `sync_scryfall.py` as part of this routine — Matty updates
   that separately and rarely, and it only works from desktop anyway (needs
   a direct DB connection). Only mention it if the ManaBox sync reports
   collection rows that fail to join to `cards` (a sign Scryfall data is
   stale).
