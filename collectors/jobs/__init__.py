"""Job plumbing: a shared context, job_runs bookkeeping, and the event log."""

from __future__ import annotations

import datetime as dt
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from collectors.content import Content
from collectors.db.models import Event, JobRun
from collectors.db.session import upsert, utcnow
from collectors.http import Http


class Skip(Exception):
    """Raised by a job that has nothing to do (for example, no token configured)."""


class Partial(Exception):
    """Raised by a job that saved some results but hit errors; its writes are kept."""


@dataclass
class JobContext:
    session: Session
    content: Content
    http: Http
    today: dt.date
    dry_run: bool = False
    force: bool = False
    only_repo: str | None = None
    log: Callable[[str], None] = print
    options: dict[str, Any] = field(default_factory=dict)
    clock: Callable[[], dt.datetime] = utcnow  # injectable so tests don't depend on the date

    @property
    def now(self) -> dt.datetime:
        return self.clock()


JobFn = Callable[[JobContext], str]


def run_job(name: str, fn: JobFn, ctx: JobContext) -> JobRun:
    """Run one job in the caller's transaction and record a job_runs row. Never raises.

    On failure the job's partial writes are rolled back before the run is recorded, so one
    broken collector can't leave half-written snapshots behind or stop the jobs after it.
    """
    calls_before = ctx.http.calls
    started = utcnow()
    status, error = "ok", None
    try:
        summary = fn(ctx)
    except Skip as exc:
        ctx.session.rollback()
        status, summary = "skipped", str(exc)
    except Partial as exc:
        status, summary = "error", str(exc)
    except Exception as exc:
        ctx.session.rollback()
        status, summary = "error", f"{type(exc).__name__}: {exc}"
        error = traceback.format_exc()[-4000:]
    run = JobRun(
        job=name,
        started_at=started,
        finished_at=utcnow(),
        status=status,
        api_calls=ctx.http.calls - calls_before,
        summary=summary[:500],
        error=error,
    )
    ctx.session.add(run)
    ctx.session.flush()
    ctx.log(f"[{name}] {status}: {run.summary} ({run.api_calls} requests)")
    return run


def emit(
    session: Session,
    *,
    key: str,
    kind: str,
    title: str,
    entity_type: str | None = None,
    entity_slug: str | None = None,
    url: str | None = None,
    detail: dict[str, Any] | None = None,
    when: dt.datetime | None = None,
) -> None:
    """Record an event once; the dedupe key makes re-runs and repeated detections harmless."""
    upsert(
        session,
        Event,
        [
            {
                "dedupe_key": key[:300],
                "kind": kind,
                "title": title[:300],
                "entity_type": entity_type,
                "entity_slug": entity_slug,
                "url": url,
                "detail": detail or {},
                "occurred_at": when or utcnow(),
                "notified_at": None,
                "notified_via": None,
            }
        ],
        update=[],
    )
