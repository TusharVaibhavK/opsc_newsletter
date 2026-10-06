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

from collectors.content import Content, Cycle, CycleEvent, Profile, WatchItem, load_content
from collectors.db.models import Base
from collectors.db.session import make_engine, migrate
from collectors.http import Http
from collectors.jobs import JobContext
from collectors.sync import sync_content

TODAY = dt.date(2026, 10, 5)


@pytest.fixture(scope="session")
def content() -> Content:
    """The real content/, for the tests that check it. Everything else uses `pinned`."""
    return load_content()


@pytest.fixture(scope="session")
def pinned(content: Content) -> Content:
    """Real programs and orgs, but a fixed profile and watchlist, so editing your own
    profile.yaml or watchlist.yaml can never break a test."""
    profile = Profile(
        github_username=None,
        languages=["go", "java", "python"],
        interests=["backend", "ml"],
        timezone="Asia/Kolkata",
        target="GSoC 2027",
    )
    watchlist = [
        WatchItem(org="kubeflow", status="primary", priority=1, next_action="x"),
        WatchItem(org="sw360", status="exploring", priority=2, next_action="x"),
    ]
    return content.model_copy(update={"profile": profile, "watchlist": watchlist})


def with_username(content: Content, username: str) -> Content:
    profile = content.profile.model_copy(update={"github_username": username})
    return content.model_copy(update={"profile": profile})


@pytest.fixture(scope="session")
def with_deadline(pinned: Content) -> Content:
    """GSoC gets one dated event, so deadline tests don't depend on dates in content/."""
    cycle = Cycle(
        name="GSoC 2027",
        events=[CycleEvent(kind="apply_close", date=dt.date(2027, 3, 31), confirmed=False)],
    )
    gsoc = pinned.program("gsoc").model_copy(update={"cycles": [cycle]})
    programs = [gsoc if p.slug == "gsoc" else p for p in pinned.programs]
    return pinned.model_copy(update={"programs": programs})


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
def make_ctx(session: Session, pinned: Content, http: Http) -> Callable[..., JobContext]:
    def build(**overrides: object) -> JobContext:
        params: dict[str, object] = {
            "session": session,
            "content": pinned,
            "http": http,
            "today": TODAY,
            "log": lambda _m: None,
        }
        params.update(overrides)
        return JobContext(**params)  # type: ignore[arg-type]

    return build


@pytest.fixture
def deadline_ctx(make_ctx: Callable[..., JobContext], with_deadline: Content) -> JobContext:
    """A context set a week before the synthetic GSoC deadline above."""
    return make_ctx(content=with_deadline, today=dt.date(2027, 3, 25))
