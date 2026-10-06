"""score_and_notify: weekly competition bands and fit scores, then alerts.

Competition compares demand (newcomers crowding in) with supply (slots and ideas), standardised
across the curated orgs. It is relative: "high" means more crowded than most orgs tracked here,
not crowded in absolute terms. The numeric score never leaves the database; the site shows
bands only. Weights are the build plan's starting guesses with the chat term (P) removed and
the remaining crowding weights rescaled to sum to 1.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from collectors.content import Content
from collectors.db.models import (
    Event,
    JobRun,
    MyActivity,
    PageSnapshot,
    ProgramYear,
    Repo,
    RepoSnapshot,
    ScoreWeekly,
    WatchedPage,
)
from collectors.db.session import upsert
from collectors.jobs import JobContext, Partial, emit
from collectors.notify import send_alerts

WEIGHTS: dict[str, float] = {
    "new_contributors": 0.375,  # people with no merged PR yet, first seen in the last 30 days
    "claim_speed": 0.25,  # 1 / median hours until a beginner issue is claimed
    "newcomer_backlog": 0.1875,  # open newcomer PRs nobody has answered
    "log_stars": 0.1875,  # brand recognition proxy
    "slots": -0.40,  # average GSoC projects a year, last 3 years (supply)
    "ideas": -0.20,  # ideas on the current list (supply)
}
FIT_WEIGHTS = {"languages": 0.40, "tracks": 0.20, "merged_prs": 0.25, "streak": 0.15}
MIN_CONFIDENCE = 0.5
MIN_ORGS = 4
WEEKS = 12
DEADLINE_KINDS = {
    "apply_open",
    "apply_close",
    "orgs_announced",
    "results",
    "contribution_start",
    "start",
}
KIND_TEXT = {
    "apply_open": "applications open",
    "apply_close": "applications close",
    "orgs_announced": "orgs are announced",
    "results": "results are announced",
    "contribution_start": "the contribution period starts",
    "start": "it starts",
}


def monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


@dataclass
class OrgInputs:
    org: str
    values: dict[str, float | None]


def _latest_per_repo(snapshots: list[RepoSnapshot], until: dt.date) -> dict[str, RepoSnapshot]:
    """The newest snapshot per repo on or before `until`, ignoring anything older than 14 days."""
    latest: dict[str, RepoSnapshot] = {}
    for snap in snapshots:
        if until - dt.timedelta(days=14) <= snap.date <= until:
            current = latest.get(snap.repo)
            if current is None or snap.date > current.date:
                latest[snap.repo] = snap
    return latest


def gather_inputs(ctx: JobContext, week: dt.date) -> list[OrgInputs]:
    session = ctx.session
    week_end = week + dt.timedelta(days=6)
    repos_by_org: dict[str, list[str]] = defaultdict(list)
    for repo in session.scalars(select(Repo).where(Repo.tracked.is_(True))):
        repos_by_org[repo.org].append(repo.full_name)
    snapshots = list(session.scalars(select(RepoSnapshot).where(RepoSnapshot.date <= week_end)))
    latest = _latest_per_repo(snapshots, week_end)

    years = sorted(
        {y for y in session.scalars(select(ProgramYear.year).where(ProgramYear.program == "gsoc"))}
    )[-3:]
    slots: dict[str, list[int]] = defaultdict(list)
    for py in session.scalars(select(ProgramYear).where(ProgramYear.program == "gsoc")):
        if py.year in years:
            slots[py.org].append(py.num_projects)

    ideas_urls = {
        p.entity_slug: p.url
        for p in session.scalars(select(WatchedPage).where(WatchedPage.kind == "ideas"))
    }

    out: list[OrgInputs] = []
    for org in ctx.content.orgs:
        snaps = [latest[r] for r in repos_by_org.get(org.slug, []) if r in latest]
        claims = [s.gfi_median_claim_hours for s in snaps if s.gfi_median_claim_hours is not None]
        n30 = [s.new_contributors_30d for s in snaps if s.new_contributors_30d is not None]
        backlog = [s.open_newcomer_prs for s in snaps if s.open_newcomer_prs is not None]
        stars = [s.stars for s in snaps if s.stars is not None]
        ideas_count = None
        url = ideas_urls.get(org.slug)
        if url:
            snap = session.scalars(
                select(PageSnapshot)
                .where(
                    PageSnapshot.url == url,
                    PageSnapshot.fetched_at < week_end + dt.timedelta(days=1),
                )
                .order_by(PageSnapshot.fetched_at.desc())
            ).first()
            if snap and snap.headings:
                ideas_count = float(len(snap.headings))
        org_slots = slots.get(org.slug, [])
        out.append(
            OrgInputs(
                org=org.slug,
                values={
                    "new_contributors": float(sum(n30)) if n30 else None,
                    "claim_speed": 1 / max(statistics.median(claims), 0.5) if claims else None,
                    "newcomer_backlog": float(sum(backlog)) if backlog else None,
                    "log_stars": math.log1p(max(stars)) if stars else None,
                    # Missing years count as zero slots: the org didn't take part that year.
                    "slots": sum(org_slots) / len(years)
                    if years and org_slots
                    else (0.0 if years else None),
                    "ideas": ideas_count,
                },
            )
        )
    return out


def _zscores(values: list[float | None]) -> list[float | None]:
    present = [v for v in values if v is not None]
    if len(present) < 3:
        return [None] * len(values)
    mean = statistics.fmean(present)
    sd = statistics.pstdev(present)
    if sd == 0:
        return [0.0 if v is not None else None for v in values]
    return [None if v is None else (v - mean) / sd for v in values]


def competition(inputs: list[OrgInputs]) -> dict[str, dict[str, Any]]:
    """Composite score, confidence and band per org. Missing inputs count as average (z = 0)."""
    total = sum(abs(w) for w in WEIGHTS.values())
    z_by_input = {name: _zscores([i.values[name] for i in inputs]) for name in WEIGHTS}
    results: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(inputs):
        present = [n for n in WEIGHTS if z_by_input[n][idx] is not None]
        composite = sum(WEIGHTS[n] * (z_by_input[n][idx] or 0.0) for n in WEIGHTS)
        results[item.org] = {
            "composite": composite,
            "confidence": round(sum(abs(WEIGHTS[n]) for n in present) / total, 3),
            "present": present,
            "inputs": item.values,
            "z": {n: z_by_input[n][idx] for n in WEIGHTS},
        }
    eligible = [o for o, r in results.items() if r["confidence"] >= MIN_CONFIDENCE]
    scores = sorted(results[o]["composite"] for o in eligible)
    for org, result in results.items():
        if org not in eligible or len(eligible) < MIN_ORGS:
            result["score"], result["band"] = None, "unknown"
            continue
        below = sum(1 for s in scores if s < result["composite"])
        ties = sum(1 for s in scores if s == result["composite"])
        pct = 100 * (below + 0.5 * ties) / len(scores)
        result["score"] = round(pct, 1)
        result["band"] = "low" if pct < 100 / 3 else ("medium" if pct < 200 / 3 else "high")
    return results


def streak(years: set[int], latest: int | None) -> int:
    count, year = 0, latest
    while year is not None and year in years:
        count, year = count + 1, year - 1
    return count


def fit_scores(ctx: JobContext) -> dict[str, dict[str, float]]:
    content: Content = ctx.content
    session = ctx.session
    langs = {lang.lower() for lang in content.profile.languages}
    interests = set(content.profile.interests)
    merged: dict[str, int] = defaultdict(int)
    for act in session.scalars(
        select(MyActivity).where(MyActivity.kind == "pr", MyActivity.state == "merged")
    ):
        if act.org:
            merged[act.org] += 1
    years: dict[str, set[int]] = defaultdict(set)
    for py in session.scalars(select(ProgramYear).where(ProgramYear.program == "gsoc")):
        if py.num_projects > 0:
            years[py.org].add(py.year)
    latest = max((y for ys in years.values() for y in ys), default=None)
    out: dict[str, dict[str, float]] = {}
    for org in content.orgs:
        org_langs = {lang.lower() for lang in org.languages}
        parts = {
            "languages": len(org_langs & langs) / len(org_langs) if org_langs else 0.0,
            "tracks": 1.0 if set(org.tracks) & interests else 0.0,
            "merged_prs": min(merged.get(org.slug, 0), 5) / 5,
            "streak": min(streak(years.get(org.slug, set()), latest), 5) / 5,
        }
        out[org.slug] = {
            "fit": round(100 * sum(FIT_WEIGHTS[k] * v for k, v in parts.items()), 1),
            **parts,
        }
    return out


def score(ctx: JobContext) -> int:
    fits = fit_scores(ctx)
    this_week = monday(ctx.today)
    rows: list[dict[str, Any]] = []
    for back in range(WEEKS):
        week = this_week - dt.timedelta(weeks=back)
        for org, result in competition(gather_inputs(ctx, week)).items():
            rows.append(
                {
                    "org": org,
                    "week": week,
                    "competition_score": result["score"],
                    "band": result["band"],
                    "confidence": result["confidence"],
                    "fit_score": fits[org]["fit"],
                    "components": {
                        "present": result["present"],
                        "inputs": result["inputs"],
                        "fit": fits[org],
                    },
                }
            )
    upsert(ctx.session, ScoreWeekly, rows)
    return len(rows)


def cycle_title(program: str, cycle: str) -> str:
    """'GSoC 2027' and 'Hacktoberfest 2026' already name their program; '2027 Term 1' doesn't."""
    first = cycle.split()[0].upper() if cycle.split() else ""
    initials = "".join(w[0] for w in program.split() if w[0].isupper() or w.lower() == "of").upper()
    if cycle.startswith(program) or (len(first) > 1 and first == initials):
        return cycle
    return f"{program} {cycle}"


def deadline_events(ctx: JobContext) -> int:
    count = 0
    horizon = ctx.today + dt.timedelta(days=7)
    for program in ctx.content.programs:
        for cycle in program.cycles:
            for event in cycle.events:
                if event.precision != "day" or event.kind not in DEADLINE_KINDS:
                    continue
                if not ctx.today <= event.date <= horizon:
                    continue
                days = (event.date - ctx.today).days
                when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
                what = event.label or KIND_TEXT[event.kind]
                status = "" if event.confirmed else ", estimated"
                name = cycle_title(program.name, cycle.name)
                day = f"{event.date:%b} {event.date.day}"
                key = ":".join(
                    [
                        "deadline",
                        program.slug,
                        cycle.name,
                        event.kind,
                        event.label or "",
                        str(event.date),
                    ]
                )
                emit(
                    ctx.session,
                    key=key,
                    kind="deadline",
                    title=f"{name}: {what.lower()} {when} ({day}{status})",
                    entity_type="program",
                    entity_slug=program.slug,
                    url=str(cycle.source_url or program.url),
                    detail={"date": event.date.isoformat(), "confirmed": event.confirmed},
                )
                count += 1
    return count


def failing_job_events(ctx: JobContext) -> int:
    runs: dict[str, list[JobRun]] = defaultdict(list)
    for run in ctx.session.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(200)):
        if len(runs[run.job]) < 2:
            runs[run.job].append(run)
    count = 0
    for job, last_two in runs.items():
        if len(last_two) == 2 and all(r.status == "error" for r in last_two):
            emit(
                ctx.session,
                key=f"job-failing:{job}:{last_two[0].started_at:%Y-%m-%d}",
                kind="job_failing",
                title=f"{job} failed twice in a row: {last_two[0].summary or 'see /admin'}",
                entity_type="source",
                entity_slug=job,
                detail={"job": job},
            )
            count += 1
    return count


def score_and_notify(ctx: JobContext) -> str:
    scored = score(ctx)
    deadlines = deadline_events(ctx)
    failing = failing_job_events(ctx)
    ctx.session.flush()
    pending = list(
        ctx.session.scalars(
            select(Event).where(Event.notified_at.is_(None)).order_by(Event.occurred_at)
        )
    )
    summary = f"{scored} org-weeks scored, {deadlines} deadline alerts, {failing} failing jobs"
    if ctx.dry_run:
        return summary + f", {len(pending)} alerts not sent (dry run)"
    channel, error = send_alerts(ctx.http, pending)
    if error:
        raise Partial(summary + f" | alerts not sent: {error}")
    now = ctx.now
    for event in pending:
        event.notified_at, event.notified_via = now, channel
    return summary + f", {len(pending)} alerts via {channel}"
