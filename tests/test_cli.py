"""Scheduling: which jobs are due on which day."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from collectors.cli import due_jobs, main
from collectors.db.models import JobRun, ProgramYear

DAILY = ["collect_github", "watch_pages", "score_and_notify"]


def seed(engine: Engine) -> None:
    with Session(engine) as s:
        s.add(ProgramYear(org="kubeflow", program="gsoc", year=2026, num_projects=9))
        s.add(JobRun(job="scrape_programs", started_at=dt.datetime(2026, 10, 1), status="ok"))
        s.commit()


def test_first_run_does_everything(engine: Engine, session: Session) -> None:
    assert set(due_jobs(engine, dt.date(2026, 10, 6))) == {*DAILY, "import_gsoc", "scrape_programs"}


def test_ordinary_weekday(engine: Engine, session: Session) -> None:
    seed(engine)
    assert due_jobs(engine, dt.date(2026, 10, 6)) == [
        "collect_github",
        "watch_pages",
        "score_and_notify",
    ]


def test_monday_adds_weekly_jobs(engine: Engine, session: Session) -> None:
    seed(engine)
    jobs = due_jobs(engine, dt.date(2026, 10, 5))  # a Monday
    assert jobs[0] == "import_gsoc" and "scrape_programs" in jobs and jobs[-1] == "score_and_notify"


def test_announcement_season_imports_daily(engine: Engine, session: Session) -> None:
    seed(engine)
    assert "import_gsoc" in due_jobs(engine, dt.date(2027, 2, 17))  # a Wednesday in season
    assert "import_gsoc" not in due_jobs(engine, dt.date(2027, 6, 16))


def test_validate_command() -> None:
    assert main(["validate"]) == 0
