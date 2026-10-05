"""Migrations match the models, upserts are idempotent, and the JSONL history round-trips."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from collectors.content import Content
from collectors.db import history
from collectors.db.models import JOB_RUNS_KEPT, Base, Event, JobRun, Org, RepoSnapshot
from collectors.db.session import make_engine, migrate, upsert
from collectors.sync import sync_content


def test_migrations_match_models(engine: Engine) -> None:
    migrate(engine)  # a second run is a no-op
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    assert diff == []


def test_snapshot_upsert_is_idempotent(session: Session) -> None:
    row = {
        "repo": "kubeflow/pipelines",
        "date": dt.date(2026, 10, 5),
        "stars": 10,
        "open_gfi_count": 3,
    }
    upsert(session, RepoSnapshot, [row])
    upsert(session, RepoSnapshot, [{**row, "stars": 11}])
    session.flush()
    rows = session.scalars(select(RepoSnapshot)).all()
    assert len(rows) == 1 and rows[0].stars == 11


def test_curated_org_takes_over_an_imported_slug(session: Session, content: Content) -> None:
    # An earlier GSoC import created MetaBrainz under its slugified API name.
    session.delete(session.get(Org, "metabrainz"))
    session.flush()
    session.add(
        Org(
            slug="metabrainz-foundation-inc",
            name="MetaBrainz Foundation Inc",
            gsoc_name="MetaBrainz Foundation Inc",
        )
    )
    session.flush()
    sync_content(session, content)
    assert session.get(Org, "metabrainz-foundation-inc") is None
    assert session.get(Org, "metabrainz").curated  # type: ignore[union-attr]


def test_history_round_trip(session: Session, content: Content, tmp_path: Path) -> None:
    session.add(
        Event(
            dedupe_key="k1",
            kind="deadline",
            title="Ünïcode title",
            detail={"dates": ["Mar 31, 2027"]},
            occurred_at=dt.datetime(2026, 10, 5, 6, 30),
        )
    )
    upsert(
        session,
        RepoSnapshot,
        [
            {
                "repo": "kubevirt/kubevirt",
                "date": dt.date(2026, 10, 4),
                "gfi_median_claim_hours": 1.23456,
            }
        ],
    )
    session.add(
        JobRun(
            job="collect_github",
            started_at=dt.datetime(2026, 10, 5),
            status="error",
            error="Traceback: C:/secret/path",
        )
    )
    session.flush()
    counts = history.dump(session, tmp_path)
    assert counts["events"] == 1

    job_line = (tmp_path / "job_runs.jsonl").read_text(encoding="utf-8")
    assert "secret/path" not in job_line and '"error":' not in job_line  # tracebacks stay private
    snap = json.loads(
        (tmp_path / "repo_snapshots.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert snap["gfi_median_claim_hours"] == 1.235

    fresh = make_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    migrate(fresh)
    with Session(fresh) as other:
        history.hydrate(other, tmp_path)
        other.commit()
        event = other.get(Event, "k1")
        assert event is not None and event.title == "Ünïcode title" and event.occurred_at.hour == 6
        assert other.scalar(select(func.count()).select_from(Org)) == len(content.orgs)


def test_job_runs_history_is_pruned(session: Session, tmp_path: Path) -> None:
    for i in range(JOB_RUNS_KEPT + 25):
        session.add(
            JobRun(
                job="watch_pages",
                started_at=dt.datetime(2026, 1, 1) + dt.timedelta(hours=i),
                status="ok",
            )
        )
    session.flush()
    history.dump(session, tmp_path)
    lines = (tmp_path / "job_runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == JOB_RUNS_KEPT
