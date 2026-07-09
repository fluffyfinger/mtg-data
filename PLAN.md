# PLAN

## P1 — Sync infrastructure (done)

Scryfall bulk data → `cards`, ManaBox CSV → `collection`, joined by
`collection_enriched`. Scripts in `scripts/`, on-demand via the
`sync-manabox` skill. See README.md.

## P2 — Merge mtg-data INTO the mtg-tracker Supabase project

**Goal:** one Supabase project — the tracker's (`oxpgmwiwwmehaireeqnb`) —
backing both repos. Collection/deck data synced by mtg-data lands directly
in the DB the Vercel app reads, so nothing ever needs "pushing."

**Direction rationale:** mtg-data's tables are fully regenerable by
idempotent sync scripts; the tracker's `auth.users` (5 pod members) and
game history are not portable between Supabase projects. Move the
regenerable side. Size is fine: cards = 114 MB + tracker 11 MB, well under
the 500 MB free tier.

### Current state (inventoried 2026-07-08)

| | mtg-data | mtg-tracker |
|---|---|---|
| Project ref | `heiyckeurcfjpnhmsjfo` (retiring) | `oxpgmwiwwmehaireeqnb` (keeper) |
| Tables | `cards` (116k rows, 114 MB), `collection` (1.3k rows), `collection_enriched` view | `players`, `cmd_games`, `hg_sessions`, `draft_nights` (~15 rows) |
| Access | service-role key via Python scripts | anon key + magic-link auth + RLS |
| Live usage | synced per ManaBox scan session | 8 cmd games (active, last 2026-07-06), 1 2HG, 1 draft |

### Feature inventory — keep / rebuild / drop

| Feature | Where | Verdict | Notes |
|---|---|---|---|
| Magic-link auth + RLS | `auth.js`, migrations 0001/0002 | **Keep, untouched** | Stays in place — this direction avoids re-auth entirely. |
| Players roster (user-owned cards) | `players.js` | **Keep, untouched** | |
| Commander game logging | `commander.js`, `cmd_games.player_decks` jsonb | **Keep core, rebuild deck input** | The actively-used feature. Matty's deck field becomes a picker fed by `collection` (`binder_type = 'deck'`, grouped by `binder_name`). Other players stay free-text. |
| Manual WUBRG color picker | `colorpicker.js` | **Keep for others, derive for Matty** | Colors for real decks come from `cards.color_identity`; picker stays for opponents/draft archetypes. |
| Dashboard | `dashboard.js` | **Keep UI, rebuild stats later** | Client-side N+1 stats; fine at pod scale. SQL view someday, not a blocker. |
| 2HG planner + bracket | `twohg.js` | **Keep as-is, zero investment** | Used once (April). |
| Draft night logging | `draft.js` | **Keep as-is** | Used once (May). |
| localStorage upgrade guide | `SUPABASE.md`, README backend sections | **Drop / rewrite** | Both describe the pre-Supabase app. |
| Migration GitHub Action | mtg-tracker `migrate.yml` | **Keep, untouched** | New schema ships through it as a normal migration. |
| mtg-data sync scripts + skill | `scripts/`, `sync-manabox` skill | **Keep, repoint** | Only env values change. |

Schemas are disjoint — the merge is purely additive on the tracker side.

### Chunks

Each chunk is independently shippable, in order. Nothing breaks between
chunks: the app keeps working against existing tables throughout.

---

**Chunk 1 — Schema lands in the tracker project**
*~30 min, no user-visible change*

- Copy `migrations/001_initial_schema.sql` (cards, collection,
  collection_enriched) into mtg-tracker `supabase/migrations/` as a new
  timestamped migration.
- Add RLS in the same migration: enable on `cards` + `collection`,
  `select` for `authenticated` only. No insert/update/delete policies —
  writes stay service-role (sync scripts bypass RLS).
- Push to main → GitHub Action applies it.
- **Verify:** tables exist and are empty; app still works.

**Chunk 2 — Repoint mtg-data and backfill**
*~15 min hands-on + a few hours unattended Scryfall upload; desktop*

- Update mtg-data `.env` (and Claude Code environment secrets for
  mobile/remote sessions): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
  `SUPABASE_DB_URL` → tracker project values.
- Run `python scripts/sync_scryfall.py` (long, unattended), then
  `python scripts/sync_manabox.py <latest csv> --prune`.
- **Verify:** row counts match old project (~116k cards, ~1.3k
  collection); `collection_enriched` returns deck rows;
  `sync-manabox` skill works end-to-end.

**Chunk 3 — Docs and references catch up**
*~20 min*

- mtg-data CLAUDE.md + README: swap project ref, note single-project
  setup.
- mtg-tracker CLAUDE.md: document the new tables; delete or rewrite
  SUPABASE.md; fix stale README claims ("no backend", localStorage).
- **Verify:** grep both repos for `heiyckeurcfjpnhmsjfo` — zero hits
  outside changelog/history.

**Chunk 4 — Deck picker in the tracker** *(first real payoff)*
*~1–2 hrs*

- Commander + Draft log forms: Matty's row gets a deck dropdown from
  `select distinct binder_name from collection where binder_type = 'deck'`,
  with free-text fallback.
- Auto-fill colors from the deck's commander `color_identity` (fallback:
  aggregate color identity of deck cards).
- **Verify:** log a real game with a picked deck; colors render on
  dashboard/history.

**Chunk 5 — Retire the old project**
*~10 min, after a comfortable verification window (suggest 2+ weeks)*

- Confirm no script/doc/secret still points at `heiyckeurcfjpnhmsjfo`.
- Pause, then delete the old Supabase project.

---

### Later / optional (not scheduled) — fan-out candidates

Chunks 1–5 are a strict dependency chain (each blocks the next) and
mostly single-threaded work, so parallel/orchestrator-worker execution
doesn't help there — nothing to fan out to. These three items are
independent of each other and of the migration chain, so once Chunk 5
lands they're the actual candidate for orchestrator/worker execution
(one subagent per item, reviewed and integrated afterward) instead of
building them serially:

- **Collection browser page** in the tracker (reads
  `collection_enriched`) — decide whether the pod should see the full
  collection or just deck names.
- **Stats SQL view** to replace client-side N+1 dashboard computation.
- **Repo merge** — sharing the Supabase project is the actual
  requirement; combining repos is cosmetic and can wait indefinitely.

### Open questions

- Pod visibility: full collection browser vs. deck names only?
- Keep the two-repo split (Python sync vs. web app) long-term, or fold
  mtg-data's `scripts/` into mtg-tracker eventually?
