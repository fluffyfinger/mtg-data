"""Shared configuration: load Supabase credentials from the environment.

The same code works in both places:
- Local dev: reads a gitignored `.env` file (via python-dotenv).
- Remote / Claude Code on the web / mobile: reads environment secrets injected
  by the Claude Code environment settings — no `.env` file present.

Never hardcode credentials here. See `.env.example` for the required keys.
"""
import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    # Loads a local `.env` if one exists. No-op when the file is absent (e.g. a
    # remote session), and never overrides variables already in the environment,
    # so injected secrets always win.
    load_dotenv()


def require(name: str) -> str:
    """Return an env var's value, or raise a clear error naming what's missing."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            "Set it in your local .env (see .env.example), or for remote/mobile "
            "sessions, add it as a secret in the Claude Code environment settings."
        )
    return value


def get(name: str, default: str | None = None) -> str | None:
    """Return an optional env var's value, or `default` if unset."""
    return os.environ.get(name, default)
