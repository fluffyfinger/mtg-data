# mtg-data Optimization Plan

Goal: get this project back to a simple, desktop-first Python sync tool (P0),
then grow it into a small multi-user collection/trading app on Vercel (P1),
and eventually fold in the dad-pod `mtg-tracker` project (P2).

**Guiding principle:** the database (Supabase) is the product. The Python
scripts, the future web app, and mtg-tracker are all just clients of one
well-designed schema.

---

## Where things stand today

- Two sync scripts: `sync_scryfall.py` (bulk card data → `cards`, ~116k rows)
  and `sync_manabox.py` (ManaBox CSV → `collection`, ~1.3k rows).
- The project drifted off the rails accommodating remote/mobile sandboxes:
  `sync_manabox.py` carries three transport paths (REST via supabase-py,
  `--emit-sql` for MCP, plus docs for each failure mode), and the README/skill
  spend most of their words on sandbox networking workarounds.
- **Security (must-know):** RLS is disabled on both `cards` and `collection`,
  and `collection_enriched` is a SECURITY DEFINER view. Right now anyone with
  the project's anon key can read *and modify* every row via PostgREST. That's
  tolerable-ish for a single-user hobby DB, but it must be fixed before any
  friend-facing deployment — and enabling RLS costs nothing now because the
  sync scripts use the service role / direct Postgres, which bypass RLS.

---

## P0 — Clean up existing (desktop/terminal only)

Outcome: one obvious way to run each script, from a terminal, with a `.env`.
Less code, fewer dependencies, no sandbox lore.

### 1. Collapse `sync_manabox.py` to one transport
- Drop the supabase-py REST path *and* keep the best implementation that
  already exists: the single atomic SQL statement `--emit-sql` builds
  (upsert + prune + summary in one transaction). Execute it directly over
  psycopg using `SUPABASE_DB_URL` — same connection style as
  `sync_scryfall.py`.
- This deletes ~150 lines of REST plumbing (`fetch_known_scryfall_ids`,
  `fetch_existing_collection`, `upsert_entries`, `prune`, chunking/paging),
  removes the `--emit-sql` flag, and fixes two latent issues for free:
  the current upsert+prune is not atomic, and inserted/updated counts are
  computed client-side before the write instead of from the write itself.
- Keep `--dry-run` and `--prune` exactly as they are.

### 2. Simplify credentials to one required secret
- Both scripts then need only `SUPABASE_DB_URL`. Keep `SUPABASE_URL` /
  `SUPABASE_SERVICE_ROLE_KEY` in `.env.example` as commented "future web app"
  entries or drop them until P1.
- `requirements.txt`: remove `supabase`; keep `psycopg`, `requests`, `ijson`,
  `python-dotenv`.

### 3. Rewrite docs for the desktop workflow
- README: setup (`cp .env.example .env`, `pip install`), the two commands,
  order (`sync_scryfall.py` first), done. Delete all sandbox/proxy/allowlist
  sections.
- `.claude/skills/sync-manabox/SKILL.md`: trim to the desktop flow — get CSV,
  dry-run if the diff looks big, run with `--prune`, report the summary.
  Delete steps 5's MCP fallback and the environment-secrets troubleshooting.

### 4. Lock the database down now (cheap, unblocks P1)
- Enable RLS on `cards` and `collection` with a simple read-only policy for
  `authenticated`/`anon` (or no policies at all yet — scripts are unaffected).
- Recreate `collection_enriched` with `security_invoker = true`.
- Ship as `migrations/002_enable_rls.sql` and apply it.

### 5. Migration hygiene
- Keep the `migrations/NNN_*.sql` convention (001 is already
  "version control only" for applied DDL). Every future schema change is a
  new numbered file, applied via Supabase MCP `apply_migration` or the SQL
  editor — never ad-hoc.

**P0 exit criteria:** fresh clone + `.env` + two commands works; repo has no
mention of sandboxes/proxies/MCP fallbacks; Supabase security advisors show
no ERROR-level findings.

---

## P1 — Multi-user schema (friends, sharing, trades) + Vercel later

Outcome: friends each sync their own ManaBox collection, can see each other's
collections (opt-in), and can propose trades. Web app comes after the schema.

### Schema direction (new migration, additive)

| Table | Change / purpose |
| --- | --- |
| `cards` | Unchanged — global shared reference data, read-only to everyone. |
| `profiles` | New. One row per user, FK to `auth.users` (Supabase Auth). Display name, etc. |
| `collection` | Add `user_id uuid not null references profiles`. Unique key becomes `(user_id, scryfall_id, foil, binder_name)`. Backfill existing rows with Matty's user_id. |
| `pods` / `pod_members` | New. A pod = a friend group (the dad pod). Sharing is scoped to pod membership rather than global. |
| `trade_proposals` | New. `from_user`, `to_user`, `status` (draft/sent/accepted/declined/completed), timestamps. |
| `trade_items` | New. One row per card in a proposal: `proposal_id`, `collection_id` (or scryfall_id + qty), `direction` (offer/request). |
| `wishlists` (optional) | Want-lists enable "you have X that Bob wants" matching — the fun part of trade proposals. Can slip to P2. |

### RLS policies (the point of P0's groundwork)
- `collection`: owner has full CRUD; pod-mates get `select` only.
- `trade_proposals` / `trade_items`: visible and editable only to the two
  parties; status transitions enforced.
- `cards` / `profiles`: read for all authenticated users.

### Sync scripts adapt, not rewrite
- `sync_manabox.py` gains a `--user` (or reads a default from `.env`) and
  writes `user_id`; prune scopes to that user's rows only. Everything else
  identical.
- Friends without terminals: near-term, they export a ManaBox CSV and send it
  to Matty (or a Claude session) to sync. Longer-term, CSV upload becomes a
  web app feature.

### Deployment (later half of P1)
- Next.js on Vercel + `supabase-js` with the **anon key only** — RLS does the
  authorization. The service role key never leaves the desktop `.env`.
- Supabase Auth with magic links (easiest for a friend group; no passwords).
- Free tiers of both Vercel (Hobby) and Supabase cover this scale — no spend.

**P1 exit criteria:** two real users with separate synced collections; RLS
verified (user A cannot modify user B's rows); trade proposal flow works via
SQL/API even before there's a UI.

---

## P2 — Merge & rebuild dad-pod `mtg-tracker`

`fluffyfinger/mtg-tracker` exists (private) but isn't in this session's scope,
so this stays intentionally sketchy until we look inside it. Direction:

1. **Inventory first.** Add the repo to a session, list what mtg-tracker
   actually does today (features, data model, who uses it), and mark each
   feature keep / rebuild / drop.
2. **One database.** Whatever survives gets rebuilt on the P1 schema —
   mtg-data's Supabase project stays the single source of truth. No
   second card database, no second collection table.
3. **One app.** mtg-tracker's features become pages/routes in the P1 Vercel
   app rather than a separate deployment. `mtg-data` likely becomes the
   repo for both (schema + sync + web), and mtg-tracker gets archived.
4. **Pod features land here:** game-night scheduling, deck/power-bracket
   tracking per pod member, win tracking — whatever the dad pod already
   relies on.

**Decide at P2 kickoff, not now:** merge direction (into mtg-data vs. a fresh
repo), and which tracker features are actually still used.

---

## Open questions for Matty (none block P0)

1. **RLS timing:** OK to apply the lockdown migration as part of P0? Sync
   scripts are unaffected; only anon-key access changes (which nothing uses
   yet). Recommended: yes.
2. **P1 sharing model:** default-visible to the whole pod, or per-binder
   opt-in? (Affects RLS policy shape; pod-visible is simpler.)
3. **Trade matching:** is the wishlist/want-list feature P1 or P2?
4. **P2 merge direction:** gut feel says everything consolidates into
   mtg-data — confirm when we crack open mtg-tracker.
