"""ossmap: the command-line entry point for local runs and the scheduled GitHub Action.

    ossmap validate                     check content/ against the schemas
    ossmap run JOB [JOB ...]            run jobs now (e.g. ossmap run import_gsoc)
    ossmap daily                        the scheduled pipeline: whichever jobs are due today
    ossmap export                       rewrite site/src/data/*.json from the database
    ossmap migrate                      apply database migrations (Postgres mode)

Without DATABASE_URL, every command rebuilds a scratch SQLite database from the committed
history in data/db/, so local runs and CI runs always start from the same state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select

from collectors.config import LOCAL_DB, database_url, github_token, uses_history_store
from collectors.content import Content, ContentError, load_content
from collectors.db import history
from collectors.db.models import JobRun, ProgramYear
from collectors.db.session import make_engine, migrate, session_scope
from collectors.export import export_all
from collectors.http import Http
from collectors.jobs import JobContext, JobFn, run_job
from collectors.jobs.github import collect_github
from collectors.jobs.gsoc import import_gsoc
from collectors.jobs.pages import scrape_programs, watch_pages
from collectors.jobs.score import score_and_notify
from collectors.sync import sync_content

JOBS: dict[str, JobFn] = {
    "import_gsoc": import_gsoc,
    "collect_github": collect_github,
    "watch_pages": watch_pages,
    "scrape_programs": scrape_programs,
    "score_and_notify": score_and_notify,
}
ORDER = list(JOBS)  # import first so new orgs exist before scoring; score last


def today_for(content: Content) -> dt.date:
    """'Today' in the profile's time zone, so a 06:00 IST run counts as that IST day."""
    return dt.datetime.now(ZoneInfo(content.profile.timezone)).date()


def due_jobs(engine: Engine, today: dt.date) -> list[str]:
    """Daily: GitHub, ideas pages, scoring. Weekly on Mondays: GSoC import and program pages,
    except Jan 15 – May 15, when the GSoC import runs daily for the announcement season."""
    with session_scope(engine) as session:
        has_gsoc = session.scalars(select(ProgramYear.year).limit(1)).first() is not None
        ran_ok = set(session.scalars(select(JobRun.job).where(JobRun.status == "ok")))
    in_season = dt.date(today.year, 1, 15) <= today <= dt.date(today.year, 5, 15)
    monday = today.weekday() == 0
    due = ["collect_github", "watch_pages", "score_and_notify"]
    if monday or in_season or not has_gsoc:
        due.append("import_gsoc")
    if monday or "scrape_programs" not in ran_ok:
        due.append("scrape_programs")
    return [j for j in ORDER if j in due]


def prepare(content: Content) -> Engine:
    """Migrate, load history (history mode), and sync content/ into the database."""
    if uses_history_store():
        LOCAL_DB.unlink(missing_ok=True)
    engine = make_engine(database_url())
    migrate(engine)
    with session_scope(engine) as session:
        if uses_history_store() and history.is_empty(session):
            counts = history.hydrate(session)
            print(f"loaded history: {sum(counts.values())} rows from data/db/")
        sync_content(session, content)
    return engine


def run_jobs(
    engine: Engine,
    content: Content,
    names: Sequence[str],
    *,
    dry_run: bool = False,
    force: bool = False,
    repo: str | None = None,
) -> list[JobRun]:
    today = today_for(content)
    runs: list[JobRun] = []
    with Http(github_token()) as http:
        for name in names:
            with session_scope(engine) as session:
                ctx = JobContext(
                    session=session,
                    content=content,
                    http=http,
                    today=today,
                    dry_run=dry_run,
                    force=force,
                    only_repo=repo,
                )
                runs.append(run_job(name, JOBS[name], ctx))
                if dry_run:
                    session.rollback()
    return runs


def finish(engine: Engine, content: Content) -> None:
    """Write the site's JSON and, always, the JSONL history (the backup in Postgres mode)."""
    with session_scope(engine) as session:
        sizes = export_all(session, content, today_for(content))
        counts = history.dump(session)
    print(f"exported {len(sizes)} site data files; history: {sum(counts.values())} rows")


def _load() -> Content:
    try:
        return load_content()
    except ContentError as exc:
        print("content/ has problems:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(2) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ossmap", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate content/")
    sub.add_parser("migrate", help="apply database migrations")
    sub.add_parser("export", help="rewrite site data from the database")
    run = sub.add_parser("run", help="run specific jobs now")
    run.add_argument("jobs", nargs="+", choices=ORDER)
    daily = sub.add_parser("daily", help="run the jobs due today, then export")
    daily.add_argument("--jobs", help="comma-separated jobs to run instead of the schedule")
    for p in (run, daily):
        p.add_argument(
            "--dry-run", action="store_true", help="fetch but save nothing, send nothing"
        )
        p.add_argument("--force", action="store_true", help="ignore same-day freshness and ETags")
    run.add_argument("--repo", help="collect_github: only this owner/name")
    args = parser.parse_args(argv)

    content = _load()
    if args.command == "validate":
        print(
            f"content OK: {len(content.programs)} programs, {len(content.orgs)} orgs, "
            f"{len(content.watchlist)} on the watchlist, {len(content.guide_slugs)} guides"
        )
        return 0
    engine = prepare(content)
    if args.command == "migrate":
        print("database is at the latest migration")
        return 0
    if args.command == "export":
        finish(engine, content)
        return 0

    if args.command == "run":
        names = [j for j in ORDER if j in args.jobs]
    elif args.jobs:
        names = [j for j in ORDER if j in {s.strip() for s in args.jobs.split(",")}]
    else:
        names = due_jobs(engine, today_for(content))
    print(f"jobs: {', '.join(names)}" + (" (dry run)" if args.dry_run else ""))
    runs = run_jobs(
        engine,
        content,
        names,
        dry_run=args.dry_run,
        force=args.force,
        repo=getattr(args, "repo", None),
    )
    if not args.dry_run:
        finish(engine, content)
    failed = [r.job for r in runs if r.status == "error"]
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed and not os.environ.get("OSSMAP_IGNORE_FAILURES") else 0


if __name__ == "__main__":
    raise SystemExit(main())
