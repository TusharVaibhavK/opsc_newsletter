"""Engine and session helpers, migrations, and a dialect-aware upsert."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, Table, create_engine, event
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Session

from collectors.config import database_url

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
CHUNK = 500


def utcnow() -> dt.datetime:
    """Naive UTC. SQLite has no time zones, so every timestamp in the database is naive UTC."""
    return dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0)


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite"):
        if ":memory:" not in url and url != "sqlite://":
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url)

        @event.listens_for(engine, "connect")
        def _enforce_foreign_keys(dbapi_conn: Any, _record: Any) -> None:
            # Match Postgres behaviour; SQLite ignores foreign keys unless asked.
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def alembic_config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR.as_posix())
    # configparser treats % as interpolation; URL-encoded characters must be escaped.
    url = engine.url.render_as_string(hide_password=False).replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrate(engine: Engine) -> None:
    """Bring the schema to the latest migration."""
    cfg = alembic_config(engine)
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def upsert(
    session: Session,
    model: type[DeclarativeBase],
    rows: Sequence[dict[str, Any]],
    update: Sequence[str] | None = None,
) -> None:
    """Insert rows, updating `update` columns (default: all non-key columns) on key conflicts."""
    if not rows:
        return
    table = cast(Table, model.__table__)
    keys = [c.name for c in table.primary_key.columns]
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        insert = pg_insert
    elif dialect == "sqlite":
        insert = sqlite_insert  # type: ignore[assignment]
    else:  # pragma: no cover - only SQLite and Postgres are supported
        raise RuntimeError(f"unsupported database dialect: {dialect}")
    columns = list(update) if update is not None else [c for c in rows[0] if c not in keys]
    for start in range(0, len(rows), CHUNK):
        stmt = insert(table).values(list(rows[start : start + CHUNK]))
        if columns:
            stmt = stmt.on_conflict_do_update(
                index_elements=keys, set_={c: stmt.excluded[c] for c in columns}
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=keys)
        session.execute(stmt)
