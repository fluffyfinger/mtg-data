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
