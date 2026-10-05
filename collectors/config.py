"""Paths and environment settings shared by every job."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "db"
SITE_DATA_DIR = ROOT / "site" / "src" / "data"
LOCAL_DB = DATA_DIR / "local.db"

USER_AGENT = "oss-map/0.1 (open source program tracker; one request per page per day)"

# Years of GSoC project titles to keep for orgs that are not hand-curated.
RECENT_GSOC_YEARS = 3


def database_url() -> str:
    """Postgres when DATABASE_URL is set; otherwise a local SQLite file."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Neon and Supabase hand out postgres:// URLs; SQLAlchemy wants an explicit driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url
    return f"sqlite:///{LOCAL_DB.as_posix()}"


def uses_history_store() -> bool:
    """True when the committed JSONL history is the source of truth (no DATABASE_URL)."""
    return not os.environ.get("DATABASE_URL", "").strip()


def github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None
