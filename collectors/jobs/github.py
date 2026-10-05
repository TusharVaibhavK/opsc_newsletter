"""collect_github: one GraphQL query per tracked repo per day, plus your own PRs and reviews.

Definitions (also shown on the site's methodology page):
- open_gfi_count: open issues carrying any of the repo's beginner labels.
- gfi_median_claim_hours: for the 30 newest beginner issues, hours until the first sign someone
  took it: an assignment, a linked pull request, or a first comment from someone who is neither
  the issue author nor a maintainer. Needs at least 3 claimed issues.
- new_contributors_30d: distinct people GitHub flags as first-time contributors whose first PR we
  saw in the last 30 days. Accumulates daily, so it is an undercount for the first month.
- open_newcomer_prs: open PRs from first-time contributors with no review yet.
- median_first_response_hours: for PRs by people outside the project opened 2–60 days ago, hours
  until the first review by someone else or the merge. Bots and maintainers' own PRs excluded.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import statistics
from typing import Any

from sqlalchemy import delete, func, insert, select

from collectors.db.models import MyActivity, Newcomer, OpenIssue, Repo, RepoSnapshot
from collectors.db.session import upsert
from collectors.http import GitHubError, RateLimited
from collectors.jobs import JobContext, Partial, Skip, emit

NEWCOMER = {"FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER"}
MAINTAINER = {"OWNER", "MEMBER", "COLLABORATOR"}
MIN_SAMPLES = 3

ISSUE_FIELDS = """
fragment IssueFields on Issue {
  number title url createdAt state
  author { login }
  comments(first: 5) { totalCount nodes { createdAt authorAssociation author { login } } }
  assignees(first: 1) { totalCount }
  labels(first: 10) { nodes { name } }
  timelineItems(first: 10, itemTypes: [ASSIGNED_EVENT, CONNECTED_EVENT, CROSS_REFERENCED_EVENT]) {
    nodes {
      __typename
      ... on AssignedEvent { createdAt }
      ... on ConnectedEvent { createdAt }
      ... on CrossReferencedEvent { createdAt source { __typename ... on PullRequest { state } } }
    }
  }
}
"""

PR_FIELDS = """
fragment PrFields on PullRequest {
  number url createdAt mergedAt state authorAssociation
  author { __typename login }
  reviews(first: 5) { nodes { createdAt author { login } } }
}
"""

REPO_QUERY = (
    """
query RepoMetrics($owner: String!, $name: String!, $labels: [String!], $withIssues: Boolean!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    nameWithOwner
    stargazerCount
    hasIssuesEnabled
    openGfi: issues(states: OPEN, labels: $labels, first: 50,
                    orderBy: {field: CREATED_AT, direction: DESC}) @include(if: $withIssues) {
      totalCount
      nodes { ...IssueFields }
    }
    recentGfi: issues(labels: $labels, first: 30,
                      orderBy: {field: CREATED_AT, direction: DESC}) @include(if: $withIssues) {
      nodes { ...IssueFields }
    }
    recentPrs: pullRequests(first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { ...PrFields }
    }
    openPrs: pullRequests(states: OPEN, first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { ...PrFields }
    }
  }
}
"""
    + ISSUE_FIELDS
    + PR_FIELDS
)

SEARCH_QUERY = """
query MyActivity($q: String!) {
  rateLimit { cost remaining resetAt }
  search(query: $q, type: ISSUE, first: 100) {
    nodes {
      ... on PullRequest {
        url title state createdAt mergedAt closedAt
        repository { nameWithOwner owner { login } }
      }
    }
  }
}
"""


def login_hash(login: str) -> str:
    """One-way pseudonym for a contributor's login; we only ever need to tell people apart."""
    return hashlib.sha256(f"ossmap:{login.lower()}".encode()).hexdigest()[:32]


def parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return (
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(dt.UTC)
        .replace(tzinfo=None)
    )


def _hours(start: dt.datetime, end: dt.datetime) -> float:
    return max((end - start).total_seconds() / 3600, 0.0)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if len(values) >= MIN_SAMPLES else None


def _login(node: dict[str, Any] | None) -> str | None:
    return (node or {}).get("login")


def claimed_at(issue: dict[str, Any]) -> dt.datetime | None:
    """Earliest sign someone took the issue: assignment, linked PR, or an outside comment."""
    times: list[dt.datetime] = []
    author = _login(issue.get("author"))
    for comment in issue["comments"]["nodes"]:
        login = _login(comment.get("author"))
        if login and login != author and comment.get("authorAssociation") not in MAINTAINER:
            ts = parse_ts(comment["createdAt"])
            if ts:
                times.append(ts)
            break
    for event in issue["timelineItems"]["nodes"]:
        kind = event.get("__typename")
        source = event.get("source") or {}
        if kind in ("AssignedEvent", "ConnectedEvent") or (
            kind == "CrossReferencedEvent" and source.get("__typename") == "PullRequest"
        ):
            ts = parse_ts(event.get("createdAt"))
            if ts:
                times.append(ts)
    return min(times) if times else None


def has_linked_pr(issue: dict[str, Any]) -> bool:
    for event in issue["timelineItems"]["nodes"]:
        if event.get("__typename") == "ConnectedEvent":
            return True
        source = event.get("source") or {}
        if source.get("__typename") == "PullRequest" and source.get("state") in ("OPEN", "MERGED"):
            return True
    return False


def first_response(pr: dict[str, Any]) -> dt.datetime | None:
    author = _login(pr.get("author"))
    times = [
        ts
        for review in pr["reviews"]["nodes"]
        if _login(review.get("author")) not in (None, author)
        and (ts := parse_ts(review.get("createdAt"))) is not None
    ]
    merged = parse_ts(pr.get("mergedAt"))
    if merged:
        times.append(merged)
    return min(times) if times else None


def _is_bot(pr: dict[str, Any]) -> bool:
    author = pr.get("author") or {}
    return author.get("__typename") == "Bot" or str(author.get("login", "")).endswith("[bot]")


def repo_metrics(repo: dict[str, Any], now: dt.datetime, has_labels: bool) -> dict[str, Any]:
    """Turn one RepoMetrics response into snapshot fields, open issues and newcomer sightings."""
    issues_on = bool(repo.get("hasIssuesEnabled")) and has_labels
    open_issues: list[dict[str, Any]] = []
    gfi_count = unclaimed = claim_hours = None
    if issues_on and repo.get("openGfi") is not None:
        gfi_count = repo["openGfi"]["totalCount"]
        for issue in repo["openGfi"]["nodes"]:
            assigned = issue["assignees"]["totalCount"] > 0
            linked = has_linked_pr(issue)
            open_issues.append(
                {
                    "number": issue["number"],
                    "title": issue["title"][:500],
                    "url": issue["url"],
                    "created_at": parse_ts(issue["createdAt"]),
                    "comments": issue["comments"]["totalCount"],
                    "assigned": assigned,
                    "linked_pr": linked,
                    "labels": [n["name"] for n in issue["labels"]["nodes"]],
                }
            )
        unclaimed = sum(1 for i in open_issues if not i["assigned"] and not i["linked_pr"])
        waits = []
        for issue in repo["recentGfi"]["nodes"]:
            created, claim = parse_ts(issue["createdAt"]), claimed_at(issue)
            if created and claim:
                waits.append(_hours(created, claim))
        claim_hours = _median(waits)

    newcomers: dict[str, dt.datetime] = {}
    for pr in repo["recentPrs"]["nodes"] + repo["openPrs"]["nodes"]:
        login = _login(pr.get("author"))
        created = parse_ts(pr["createdAt"])
        if login and created and not _is_bot(pr) and pr.get("authorAssociation") in NEWCOMER:
            newcomers[login] = min(created, newcomers.get(login, created))

    waits, unanswered = [], 0
    for pr in repo["recentPrs"]["nodes"]:
        created = parse_ts(pr["createdAt"])
        if not created or _is_bot(pr) or pr.get("authorAssociation") in MAINTAINER:
            continue
        age_days = (now - created).total_seconds() / 86400
        if not 2 <= age_days <= 60:
            continue
        response = first_response(pr)
        if response:
            waits.append(_hours(created, response))
        else:
            unanswered += 1
    sampled = len(waits) + unanswered

    open_newcomer = sum(
        1
        for pr in repo["openPrs"]["nodes"]
        if pr.get("authorAssociation") in NEWCOMER
        and not _is_bot(pr)
        and first_response(pr) is None
    )
    return {
        "snapshot": {
            "stars": repo.get("stargazerCount"),
            "issues_enabled": bool(repo.get("hasIssuesEnabled")),
            "open_gfi_count": gfi_count,
            "open_gfi_unclaimed": unclaimed,
            "gfi_median_claim_hours": claim_hours,
            "open_newcomer_prs": open_newcomer,
            "median_first_response_hours": _median(waits),
            "unanswered_pr_share": round(unanswered / sampled, 3)
            if sampled >= MIN_SAMPLES
            else None,
            "prs_sampled": sampled,
        },
        "open_issues": open_issues,
        "newcomers": newcomers,
    }


def _collect_repo(ctx: JobContext, repo: Repo, now: dt.datetime) -> None:
    owner, name = repo.full_name.split("/", 1)
    labels = list(repo.gfi_labels or [])
    data = ctx.http.graphql(
        REPO_QUERY,
        {"owner": owner, "name": name, "labels": labels or None, "withIssues": bool(labels)},
    )
    if data.get("repository") is None:
        raise GitHubError(f"{repo.full_name} not found (renamed or deleted?)")
    metrics = repo_metrics(data["repository"], now, has_labels=bool(labels))

    upsert(
        ctx.session,
        Newcomer,
        [
            {"repo": repo.full_name, "login_hash": login_hash(k), "first_pr_at": v}
            for k, v in metrics["newcomers"].items()
        ],
        update=[],
    )
    ctx.session.flush()
    since = now - dt.timedelta(days=30)
    new_30d = ctx.session.scalar(
        select(func.count())
        .select_from(Newcomer)
        .where(Newcomer.repo == repo.full_name, Newcomer.first_pr_at >= since)
    )
    upsert(
        ctx.session,
        RepoSnapshot,
        [
            {
                "repo": repo.full_name,
                "date": ctx.today,
                **metrics["snapshot"],
                "new_contributors_30d": new_30d,
            }
        ],
    )
    ctx.session.execute(delete(OpenIssue).where(OpenIssue.repo == repo.full_name))
    if metrics["open_issues"]:
        ctx.session.execute(
            insert(OpenIssue),
            [{"repo": repo.full_name, "seen_at": now, **i} for i in metrics["open_issues"]],
        )


def _collect_my_activity(ctx: JobContext, username: str) -> int:
    owners = {owner.lower(): o.slug for o in ctx.content.orgs for owner in o.github_owners}
    existing = {a.url: a.state for a in ctx.session.scalars(select(MyActivity))}
    rows: list[dict[str, Any]] = []
    for kind, query in (
        ("pr", f"is:pr author:{username} sort:updated-desc"),
        ("review", f"is:pr reviewed-by:{username} -author:{username} sort:updated-desc"),
    ):
        data = ctx.http.graphql(SEARCH_QUERY, {"q": query})
        for node in data["search"]["nodes"]:
            if not node:
                continue
            merged = parse_ts(node.get("mergedAt"))
            state = "merged" if merged else ("closed" if node["state"] == "CLOSED" else "open")
            repo = node["repository"]
            rows.append(
                {
                    "url": node["url"],
                    "kind": kind,
                    "repo": repo["nameWithOwner"],
                    "org": owners.get(repo["owner"]["login"].lower()),
                    "title": node["title"][:500],
                    "state": state,
                    "opened_at": parse_ts(node["createdAt"]),
                    "merged_at": merged,
                    "closed_at": parse_ts(node.get("closedAt")),
                }
            )
    rows = list({r["url"]: r for r in rows}.values())
    upsert(ctx.session, MyActivity, rows)
    for row in rows:
        if (
            row["kind"] == "pr"
            and row["state"] == "merged"
            and existing.get(row["url"]) != "merged"
        ):
            emit(
                ctx.session,
                key=f"pr-merged:{row['url']}",
                kind="pr_merged",
                title=f"Merged: {row['title']} ({row['repo']})",
                entity_type="org" if row["org"] else None,
                entity_slug=row["org"],
                url=row["url"],
                when=row["merged_at"],
            )
    return len(rows)


def collect_github(ctx: JobContext) -> str:
    if not ctx.http.token:
        raise Skip("GITHUB_TOKEN is not set; GitHub metrics need a token (Actions provides one)")
    now = ctx.now
    query = select(Repo).where(Repo.tracked.is_(True)).order_by(Repo.full_name)
    if ctx.only_repo:
        query = select(Repo).where(Repo.full_name == ctx.only_repo)
    repos = list(ctx.session.scalars(query))
    if ctx.only_repo and not repos:
        raise ValueError(
            f"{ctx.only_repo} is not a tracked repo; add it to an org in content/orgs/"
        )
    fresh = set(
        ctx.session.scalars(select(RepoSnapshot.repo).where(RepoSnapshot.date == ctx.today))
    )

    done, skipped, errors = 0, 0, []
    for repo in repos:
        if repo.full_name in fresh and not ctx.force:
            skipped += 1  # same-day re-run: today's snapshot exists, spend no API calls
            continue
        try:
            _collect_repo(ctx, repo, now)
            done += 1
        except RateLimited as exc:
            errors.append(f"rate limited after {done} repos: {exc}")
            break
        except GitHubError as exc:
            errors.append(f"{repo.full_name}: {exc}")

    activity = 0
    username = ctx.content.profile.github_username
    if username and not any("rate limited" in e for e in errors):
        try:
            activity = _collect_my_activity(ctx, username)
        except GitHubError as exc:
            errors.append(f"my activity: {exc}")

    summary = f"{done} repos collected, {skipped} already fresh today"
    summary += (
        f", {activity} of your PRs/reviews" if username else ", no github_username in profile"
    )
    if errors:
        if done == 0 and skipped == 0:
            raise GitHubError("; ".join(errors))
        raise Partial(summary + " | " + "; ".join(errors))
    return summary
