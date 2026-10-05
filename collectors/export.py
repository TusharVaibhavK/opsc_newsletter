"""Write the JSON slice the static site builds from (site/src/data/*.json).

Public by design: everything here ends up on the website. Contributor names, job tracebacks and
the numeric competition score stay in the database and are never exported.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collectors.config import SITE_DATA_DIR, uses_history_store
from collectors.content import Content
from collectors.db.models import (
    Event,
    JobRun,
    MyActivity,
    OpenIssue,
    Org,
    PageSnapshot,
    ProgramYear,
    ProjectHistory,
    Repo,
    RepoSnapshot,
    ScoreWeekly,
    WatchedPage,
)
from collectors.db.session import utcnow
from collectors.jobs.score import WEEKS, WEIGHTS, monday, streak
from collectors.sync import effective_links

ISSUES_PER_ORG = 6
EVENTS_KEPT = 150
JOBS_KEPT = 60
SOURCE_JOBS = (
    "collect_github",
    "import_gsoc",
    "watch_pages",
    "scrape_programs",
    "score_and_notify",
)


def _iso(value: dt.datetime | dt.date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(microsecond=0).isoformat() + "Z"
    return value.isoformat()


def _write(out_dir: Path, name: str, payload: Any) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
    (out_dir / name).write_text(text + "\n", encoding="utf-8", newline="\n")


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def export_gsoc(session: Session, content: Content) -> tuple[dict[str, Any], dict[str, Any]]:
    curated = {o.slug: o for o in content.orgs}
    years_by_org: dict[str, dict[int, int]] = defaultdict(dict)
    for py in session.scalars(select(ProgramYear).where(ProgramYear.program == "gsoc")):
        years_by_org[py.org][py.year] = py.num_projects
    all_years = sorted({y for ys in years_by_org.values() for y in ys})
    latest = all_years[-1] if all_years else None

    orgs = []
    for row in session.scalars(select(Org).order_by(Org.name)):
        years = years_by_org.get(row.slug, {})
        if not years and row.slug not in curated:
            continue
        active = {y for y, n in years.items() if n > 0}
        orgs.append(
            {
                "slug": row.slug,
                "name": curated[row.slug].name if row.slug in curated else row.name,
                "curated": row.slug in curated,
                "category": row.category,
                "description": (row.description or "")[:400] or None,
                "technologies": row.technologies or [],
                "topics": row.topics or [],
                "links": effective_links(curated.get(row.slug), row),
                "years": {str(y): n for y, n in sorted(years.items())},
                "streak": streak(active, latest),
                "first_year": min(years) if years else None,
                "in_latest": latest in years if latest else False,
                "total_projects": sum(years.values()),
            }
        )

    projects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in session.scalars(
        select(ProjectHistory).order_by(
            ProjectHistory.org, ProjectHistory.year.desc(), ProjectHistory.title
        )
    ):
        projects[p.org].append({"year": p.year, "title": p.title, "url": p.project_url})
    return {"latest_year": latest, "years": all_years, "orgs": orgs}, dict(projects)


def export_metrics(session: Session, today: dt.date) -> dict[str, Any]:
    repos = list(
        session.scalars(select(Repo).where(Repo.tracked.is_(True)).order_by(Repo.full_name))
    )
    since = today - dt.timedelta(weeks=WEEKS)
    snaps: dict[str, list[RepoSnapshot]] = defaultdict(list)
    for snap in session.scalars(
        select(RepoSnapshot).where(RepoSnapshot.date >= since).order_by(RepoSnapshot.date)
    ):
        snaps[snap.repo].append(snap)

    orgs: dict[str, Any] = {}
    for repo in repos:
        history = snaps.get(repo.full_name, [])
        latest = history[-1] if history else None
        entry = orgs.setdefault(
            repo.org, {"repos": [], "weekly": [], "last_refreshed": None, "history_days": 0}
        )
        entry["repos"].append(
            {
                "name": repo.full_name,
                "gfi_labels": repo.gfi_labels or [],
                "date": _iso(latest.date) if latest else None,
                "stars": latest.stars if latest else None,
                "issues_enabled": latest.issues_enabled if latest else None,
                "open_gfi_count": latest.open_gfi_count if latest else None,
                "open_gfi_unclaimed": latest.open_gfi_unclaimed if latest else None,
                "gfi_median_claim_hours": latest.gfi_median_claim_hours if latest else None,
                "new_contributors_30d": latest.new_contributors_30d if latest else None,
                "open_newcomer_prs": latest.open_newcomer_prs if latest else None,
                "median_first_response_hours": latest.median_first_response_hours
                if latest
                else None,
                "unanswered_pr_share": latest.unanswered_pr_share if latest else None,
                "prs_sampled": latest.prs_sampled if latest else None,
            }
        )
        if latest and (
            entry["last_refreshed"] is None or _iso(latest.date) > entry["last_refreshed"]
        ):
            entry["last_refreshed"] = _iso(latest.date)
        entry["history_days"] = max(entry["history_days"], len(history))

    for org, entry in orgs.items():
        org_repos = [r["name"] for r in entry["repos"]]
        weekly = []
        for back in range(WEEKS - 1, -1, -1):
            week = monday(today) - dt.timedelta(weeks=back)
            end = week + dt.timedelta(days=6)
            latest_in_week = []
            for name in org_repos:
                in_week = [s for s in snaps.get(name, []) if week <= s.date <= end]
                if in_week:
                    latest_in_week.append(in_week[-1])
            if not latest_in_week:
                continue

            def total(field: str, rows: list[RepoSnapshot] = latest_in_week) -> int | None:
                vals = [getattr(s, field) for s in rows if getattr(s, field) is not None]
                return sum(vals) if vals else None

            def mid(field: str, rows: list[RepoSnapshot] = latest_in_week) -> float | None:
                return _median([getattr(s, field) for s in rows if getattr(s, field) is not None])

            weekly.append(
                {
                    "week": _iso(week),
                    "new_contributors_30d": total("new_contributors_30d"),
                    "open_gfi_count": total("open_gfi_count"),
                    "open_newcomer_prs": total("open_newcomer_prs"),
                    "gfi_median_claim_hours": mid("gfi_median_claim_hours"),
                    "median_first_response_hours": mid("median_first_response_hours"),
                    "stars": max(
                        (s.stars for s in latest_in_week if s.stars is not None), default=None
                    ),
                }
            )
        entry["weekly"] = weekly
        _ = org
    return {"orgs": orgs}


def export_scores(session: Session, today: dt.date) -> dict[str, Any]:
    this_week = monday(today)
    rows = list(session.scalars(select(ScoreWeekly).order_by(ScoreWeekly.org, ScoreWeekly.week)))
    orgs: dict[str, Any] = {}
    for row in rows:
        entry = orgs.setdefault(row.org, {"bands": []})
        entry["bands"].append({"week": _iso(row.week), "band": row.band})
        if row.week == this_week:
            fit = (row.components or {}).get("fit", {})
            entry.update(
                {
                    "band": row.band,
                    "confidence": round(row.confidence, 2),
                    "inputs_present": (row.components or {}).get("present", []),
                    "fit": round(row.fit_score),
                    "fit_parts": {k: round(v, 2) for k, v in fit.items() if k != "fit"},
                }
            )
    return {"week": _iso(this_week), "weights": WEIGHTS, "orgs": orgs}


def _issue_status(issue: OpenIssue) -> str:
    if issue.linked_pr:
        return "pr-linked"
    if issue.assigned:
        return "assigned"
    return "discussed" if issue.comments else "unclaimed"


def export_issues(session: Session, today: dt.date) -> dict[str, Any]:
    """A few open issues per org, rotated daily, so the board never sends everyone to one issue."""
    org_of = {r.full_name: r.org for r in session.scalars(select(Repo))}
    by_org: dict[str, list[OpenIssue]] = defaultdict(list)
    for issue in session.scalars(select(OpenIssue).order_by(OpenIssue.repo, OpenIssue.number)):
        if issue.repo in org_of:
            by_org[org_of[issue.repo]].append(issue)
    out: dict[str, Any] = {}
    for org, issues in sorted(by_org.items()):
        open_to_newcomers = [i for i in issues if not i.assigned and not i.linked_pr]
        open_to_newcomers.sort(key=lambda i: (i.comments > 0, -i.created_at.timestamp()))
        if open_to_newcomers:
            offset = today.toordinal() % len(open_to_newcomers)
            rotated = open_to_newcomers[offset:] + open_to_newcomers[:offset]
        else:
            rotated = []
        shown = sorted(
            rotated[:ISSUES_PER_ORG], key=lambda i: (i.comments > 0, -i.created_at.timestamp())
        )
        out[org] = {
            "total_open": len(issues),
            "open_to_newcomers": len(open_to_newcomers),
            "shown": [
                {
                    "repo": i.repo,
                    "number": i.number,
                    "title": i.title,
                    "url": i.url,
                    "created_at": _iso(i.created_at),
                    "age_days": (today - i.created_at.date()).days,
                    "comments": i.comments,
                    "labels": i.labels or [],
                    "status": _issue_status(i),
                }
                for i in shown
            ],
        }
    return {"date": _iso(today), "per_org": ISSUES_PER_ORG, "orgs": out}


def export_activity(session: Session, content: Content, today: dt.date) -> dict[str, Any]:
    acts = list(session.scalars(select(MyActivity).order_by(MyActivity.opened_at.desc())))

    def item(a: MyActivity) -> dict[str, Any]:
        return {
            "url": a.url,
            "repo": a.repo,
            "org": a.org,
            "title": a.title,
            "state": a.state,
            "opened_at": _iso(a.opened_at),
            "merged_at": _iso(a.merged_at),
        }

    prs = [a for a in acts if a.kind == "pr"]
    reviews = [a for a in acts if a.kind == "review"]
    by_org: dict[str, dict[str, int]] = defaultdict(
        lambda: {"merged": 0, "open": 0, "closed": 0, "reviews": 0}
    )
    for a in prs:
        by_org[a.org or "other"][a.state] += 1
    for a in reviews:
        by_org[a.org or "other"]["reviews"] += 1

    weeks: dict[dt.date, dict[str, int]] = {}
    for back in range(25, -1, -1):
        weeks[monday(today) - dt.timedelta(weeks=back)] = {"merged": 0, "opened": 0, "reviews": 0}
    for a in prs:
        if (w := monday(a.opened_at.date())) in weeks:
            weeks[w]["opened"] += 1
        if a.merged_at and (w := monday(a.merged_at.date())) in weeks:
            weeks[w]["merged"] += 1
    for a in reviews:
        if (w := monday(a.opened_at.date())) in weeks:
            weeks[w]["reviews"] += 1
    run = 0
    for _week, counts in sorted(weeks.items(), reverse=True):
        if sum(counts.values()) == 0:
            if run == 0 and _week == monday(today):
                continue  # this week isn't over yet; don't break the streak
            break
        run += 1

    log = [
        {
            "date": _iso(e.date),
            "kind": e.kind,
            "org": e.org,
            "note": e.note,
            "url": str(e.url) if e.url else None,
        }
        for e in sorted(content.log, key=lambda e: e.date, reverse=True)
    ]
    return {
        "username": content.profile.github_username,
        "totals": {
            "prs": len(prs),
            "merged": sum(1 for a in prs if a.state == "merged"),
            "open": sum(1 for a in prs if a.state == "open"),
            "reviews": len(reviews),
        },
        "streak_weeks": run,
        "by_org": dict(by_org),
        "weekly": [{"week": _iso(w), **c} for w, c in sorted(weeks.items())],
        "prs": [item(a) for a in prs[:60]],
        "reviews": [item(a) for a in reviews[:60]],
        "log": log,
    }


def export_events(session: Session) -> list[dict[str, Any]]:
    events = session.scalars(select(Event).order_by(Event.occurred_at.desc()).limit(EVENTS_KEPT))
    return [
        {
            "id": hashlib.sha256(e.dedupe_key.encode()).hexdigest()[:12],
            "kind": e.kind,
            "title": e.title,
            "url": e.url,
            "entity_type": e.entity_type,
            "entity_slug": e.entity_slug,
            "occurred_at": _iso(e.occurred_at),
            "detail": e.detail or {},
        }
        for e in events
    ]


def export_pages(session: Session, today: dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pages = list(
        session.scalars(select(WatchedPage).order_by(WatchedPage.entity_slug, WatchedPage.url))
    )
    week_ago = dt.datetime.combine(today - dt.timedelta(days=7), dt.time())
    ideas: dict[str, Any] = {}
    for page in pages:
        if page.kind == "ideas":
            snapshots = list(
                session.scalars(
                    select(PageSnapshot)
                    .where(PageSnapshot.url == page.url)
                    .order_by(PageSnapshot.fetched_at)
                )
            )
            current = snapshots[-1].headings if snapshots else []
            older = [s for s in snapshots if s.fetched_at <= week_ago]
            baseline = older[-1].headings if older else (snapshots[0].headings if snapshots else [])
            ideas.setdefault(page.entity_slug, {}).update(
                {
                    "url": page.url,
                    "checked_at": _iso(page.last_checked_at),
                    "changed_at": _iso(page.last_changed_at),
                    "status": page.last_status,
                    "note": page.note,
                    "count": len(current),
                    "titles": current,
                    "added_this_week": [t for t in current if t not in baseline],
                    "removed_this_week": [t for t in baseline if t not in current],
                }
            )
        elif page.kind == "ideas_next":
            ideas.setdefault(page.entity_slug, {})["next"] = {
                "url": page.url,
                "published": page.note == "published",
                "checked_at": _iso(page.last_checked_at),
            }
    listing = [
        {
            "url": p.url,
            "kind": p.kind,
            "entity_type": p.entity_type,
            "entity_slug": p.entity_slug,
            "last_status": p.last_status,
            "last_checked_at": _iso(p.last_checked_at),
            "last_changed_at": _iso(p.last_changed_at),
            "consecutive_errors": p.consecutive_errors,
            "needs_confirmation": p.needs_confirmation,
            "note": p.note,
        }
        for p in pages
    ]
    return listing, ideas


def export_jobs(session: Session) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runs = list(session.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(JOBS_KEPT)))
    last_ok: dict[str, str | None] = {}
    for job in SOURCE_JOBS:
        ok = session.scalars(
            select(JobRun)
            .where(JobRun.job == job, JobRun.status == "ok")
            .order_by(JobRun.id.desc())
        ).first()
        last_ok[job] = _iso(ok.finished_at) if ok else None
    listing = [
        {
            "job": r.job,
            "started_at": _iso(r.started_at),
            "finished_at": _iso(r.finished_at),
            "status": r.status,
            "api_calls": r.api_calls,
            "summary": r.summary,
        }
        for r in runs
    ]
    return listing, last_ok


def export_all(
    session: Session, content: Content, today: dt.date, out_dir: Path = SITE_DATA_DIR
) -> dict[str, int]:
    gsoc, projects = export_gsoc(session, content)
    metrics = export_metrics(session, today)
    scores = export_scores(session, today)
    issues = export_issues(session, today)
    activity = export_activity(session, content, today)
    events = export_events(session)
    pages, ideas = export_pages(session, today)
    jobs, last_ok = export_jobs(session)
    meta = {
        "generated_at": _iso(utcnow()),
        "today": _iso(today),
        "data_mode": "history" if uses_history_store() else "postgres",
        "latest_gsoc_year": gsoc["latest_year"],
        "last_ok": last_ok,
        "counts": {
            "gsoc_orgs": len(gsoc["orgs"]),
            "orgs_with_metrics": len(metrics["orgs"]),
            "open_issues": sum(o["total_open"] for o in issues["orgs"].values()),
            "events": len(events),
        },
    }
    files = {
        "meta.json": meta,
        "gsoc.json": gsoc,
        "projects.json": projects,
        "metrics.json": metrics,
        "scores.json": scores,
        "issues.json": issues,
        "activity.json": activity,
        "events.json": events,
        "ideas.json": ideas,
        "pages.json": pages,
        "jobs.json": jobs,
    }
    for name, payload in files.items():
        _write(out_dir, name, payload)
    return {name: len(json.dumps(payload)) for name, payload in files.items()}
