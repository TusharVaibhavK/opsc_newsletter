"""Shared fixtures: a migrated throwaway database, the real content/, and a job context.

No test touches the network: HTTP is mocked with respx, and the clock is pinned.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from collectors.content import Content, load_content
from collectors.db.models import Base
from collectors.db.session import make_engine, migrate
from collectors.http import Http
from collectors.jobs import JobContext
from collectors.sync import sync_content

TODAY = dt.date(2026, 10, 5)


@pytest.fixture(scope="session")
def content() -> Content:
    return load_content()


def _reset(eng: Engine) -> None:
    Base.metadata.drop_all(eng)
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """SQLite by default; set TEST_DATABASE_URL (CI does) to run every test against Postgres."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        eng = make_engine(url)
        _reset(eng)
        migrate(eng)
        yield eng
        _reset(eng)
        eng.dispose()
    else:
        eng = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
        migrate(eng)
        yield eng
        eng.dispose()


@pytest.fixture
def session(engine: Engine, content: Content) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        sync_content(s, content)
        s.commit()
        yield s


@pytest.fixture
def http() -> Iterator[Http]:
    with Http("test-token", sleep=lambda _s: None) as client:
        yield client


@pytest.fixture
def make_ctx(session: Session, content: Content, http: Http) -> Callable[..., JobContext]:
    def build(**overrides: object) -> JobContext:
        params: dict[str, object] = {
            "session": session,
            "content": content,
            "http": http,
            "today": TODAY,
            "log": lambda _m: None,
        }
        params.update(overrides)
        return JobContext(**params)  # type: ignore[arg-type]

    return build
