"""collect_github: one GraphQL query per tracked repo per day, plus your own PRs and reviews.

Definitions (also shown on the site's methodology page):
- open_gfi_count: open issues carrying any of the repo's beginner labels.
- gfi_median_claim_hours: for the 30 newest beginner issues, hours until the first sign that
  someone other than the issue's author took it: an assignment to another person, a pull request
  from another person linked to it, or a first comment from someone who is neither the author nor
  a maintainer. Bots never count. Needs at least 3 claimed issues.
- new_contributors_30d: distinct people with no merged contribution yet, whose first pull request
  we saw opened in the last 30 days. GitHub only reveals its first-timer flags to people with
  access to the repo, so for everyone else a newcomer shows up as association NONE; that is what
  we count (plus the first-timer flags, where visible). Accumulates daily, so it undercounts for
  the first month.
- open_newcomer_prs: open PRs from those newcomers that no human with standing has replied to.
- median_first_response_hours: for PRs by people outside the project opened 2-60 days ago, hours
  until the first review or comment from a human with standing in the repo (not the author, not a
  bot, not another newcomer), or the merge. Bots' and maintainers' own PRs are excluded.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import statistics
from typing import Any

from sqlalchemy import delete, func, insert, select

from collectors.db.models import Event, MyActivity, Newcomer, OpenIssue, Repo, RepoSnapshot
from collectors.db.session import upsert
from collectors.http import GitHubError, RateLimited
from collectors.jobs import JobContext, Partial, Skip, emit

# "NONE" is what a newcomer looks like to anyone without access to the repo.
NEWCOMER = {"NONE", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER"}
MAINTAINER = {"OWNER", "MEMBER", "COLLABORATOR"}
# Whose reply counts as "someone with standing answered": maintainers and past contributors.
STANDING = MAINTAINER | {"CONTRIBUTOR"}
MIN_SAMPLES = 3
RECENT_MERGE_DAYS = 3  # an unseen merge older than this is backfill, not news
MERGE_EVENT_KEEP_DAYS = 30

ISSUE_FIELDS = """
fragment IssueFields on Issue {
  number title url createdAt state
  author { login }
  comments(first: 10) {
    totalCount
    nodes { createdAt authorAssociation author { __typename login } }
  }
  assignees(first: 1) { totalCount }
  labels(first: 10) { nodes { name } }
  timelineItems(first: 20, itemTypes: [ASSIGNED_EVENT, CONNECTED_EVENT, CROSS_REFERENCED_EVENT]) {
    nodes {
      __typename
      ... on AssignedEvent {
        createdAt
        actor { login }
        assignee { __typename ... on User { login } ... on Bot { login } }
      }
      ... on ConnectedEvent { createdAt actor { login } }
      ... on CrossReferencedEvent {
        createdAt
        actor { login }
        source { __typename ... on PullRequest { state author { __typename login } } }
      }
    }
  }
}
"""

PR_FIELDS = """
fragment PrFields on PullRequest {
  number url createdAt mergedAt state authorAssociation
  author { __typename login }
  reviews(first: 10) { nodes { createdAt authorAssociation author { __typename login } } }
  comments(first: 10) { nodes { createdAt authorAssociation author { __typename login } } }
}
"""

# Two smaller queries per repo instead of one big one: on very large repos a single query
# asking for issues, PRs, reviews and comments together can run past GitHub's time limit.
PRS_QUERY = (
    """
query RepoPrs($owner: String!, $name: String!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    nameWithOwner
    stargazerCount
    hasIssuesEnabled
    recentPrs: pullRequests(first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { ...PrFields }
    }
    openPrs: pullRequests(states: OPEN, first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { ...PrFields }
    }
  }
}
"""
    + PR_FIELDS
)

ISSUES_QUERY = (
    """
query RepoIssues($owner: String!, $name: String!, $labels: [String!]) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    openGfi: issues(states: OPEN, labels: $labels, first: 50,
                    orderBy: {field: CREATED_AT, direction: DESC}) {
      totalCount
      nodes { ...IssueFields }
    }
    recentGfi: issues(labels: $labels, first: 30, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { ...IssueFields }
    }
  }
}
"""
    + ISSUE_FIELDS
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


def _is_bot(actor: dict[str, Any] | None) -> bool:
    """GraphQL reports apps as type Bot (login without the REST API's "[bot]" suffix)."""
    actor = actor or {}
    return actor.get("__typename") == "Bot" or str(actor.get("login") or "").endswith("[bot]")


def _claim_event_time(event: dict[str, Any], author: str | None) -> dt.datetime | None:
    """When this timeline event shows someone other than the issue's author taking the issue."""
    kind = event.get("__typename")
    if kind == "AssignedEvent":
        assignee = event.get("assignee") or {}
        who = assignee.get("login")
        if not who or who == author or assignee.get("__typename") == "Bot":
            return None
    elif kind == "ConnectedEvent":
        actor = event.get("actor")
        if not _login(actor) or _login(actor) == author or _is_bot(actor):
            return None
    elif kind == "CrossReferencedEvent":
        source = event.get("source") or {}
        if source.get("__typename") != "PullRequest":
            return None
        pr_author = source.get("author")
        if not _login(pr_author) or _login(pr_author) == author or _is_bot(pr_author):
            return None
    else:
        return None
    return parse_ts(event.get("createdAt"))


def claimed_at(issue: dict[str, Any]) -> dt.datetime | None:
    """Earliest sign someone other than the author took the issue."""
    times: list[dt.datetime] = []
    author = _login(issue.get("author"))
    for comment in issue["comments"]["nodes"]:
        actor = comment.get("author")
        login = _login(actor)
        if (
            login
            and login != author
            and not _is_bot(actor)
            and comment.get("authorAssociation") not in MAINTAINER
        ):
            if ts := parse_ts(comment.get("createdAt")):
                times.append(ts)
            break
    for event in issue["timelineItems"]["nodes"]:
        if ts := _claim_event_time(event, author):
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
    """Earliest human reply with standing in the repo (or the merge itself)."""
    author = _login(pr.get("author"))
    times: list[dt.datetime] = []
    for kind in ("reviews", "comments"):
        for node in (pr.get(kind) or {}).get("nodes") or []:
            actor = node.get("author")
            login = _login(actor)
            if not login or login == author or _is_bot(actor):
                continue
            if node.get("authorAssociation") not in STANDING:
                continue
            if ts := parse_ts(node.get("createdAt")):
                times.append(ts)
    if merged := parse_ts(pr.get("mergedAt")):
        times.append(merged)
    return min(times) if times else None


def _is_newcomer_pr(pr: dict[str, Any]) -> bool:
    return (
        pr.get("authorAssociation") in NEWCOMER
        and bool(_login(pr.get("author")))
        and not _is_bot(pr.get("author"))
    )


def repo_metrics(repo: dict[str, Any], now: dt.datetime, has_labels: bool) -> dict[str, Any]:
    """Turn the RepoPrs and RepoIssues replies into snapshot fields, issues and newcomers."""
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
        created = parse_ts(pr["createdAt"])
        if created and _is_newcomer_pr(pr):
            login = str(_login(pr.get("author")))
            newcomers[login] = min(created, newcomers.get(login, created))

    waits, unanswered = [], 0
    for pr in repo["recentPrs"]["nodes"]:
        created = parse_ts(pr["createdAt"])
        if not created or _is_bot(pr.get("author")) or pr.get("authorAssociation") in MAINTAINER:
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
        1 for pr in repo["openPrs"]["nodes"] if _is_newcomer_pr(pr) and first_response(pr) is None
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
    variables = {"owner": owner, "name": name}
    found = ctx.http.graphql(PRS_QUERY, variables).get("repository")
    if found is None:
        raise GitHubError(f"{repo.full_name} not found (renamed or deleted?)")
    if labels and found.get("hasIssuesEnabled"):
        issues = ctx.http.graphql(ISSUES_QUERY, {**variables, "labels": labels})
        found = {**found, **(issues.get("repository") or {})}
    metrics = repo_metrics(found, now, has_labels=bool(labels))

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


def _collect_my_activity(ctx: JobContext, username: str, now: dt.datetime) -> int:
    me = username.lower()
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
            repo = node["repository"]
            if repo["owner"]["login"].lower() == me:
                continue  # your own repos aren't contributions to someone else's project
            merged = parse_ts(node.get("mergedAt"))
            state = "merged" if merged else ("closed" if node["state"] == "CLOSED" else "open")
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

    # Forget anything recorded before own repos were excluded. Merge events are celebrations
    # rather than history, so they also expire after a month, which clears first-run backfill.
    ctx.session.execute(delete(MyActivity).where(func.lower(MyActivity.repo).like(f"{me}/%")))
    ctx.session.execute(
        delete(Event).where(
            Event.kind == "pr_merged",
            (func.lower(Event.url).like(f"https://github.com/{me}/%"))
            | (Event.occurred_at < now - dt.timedelta(days=MERGE_EVENT_KEEP_DAYS)),
        )
    )
    upsert(ctx.session, MyActivity, rows)

    recent = now - dt.timedelta(days=RECENT_MERGE_DAYS)
    for row in rows:
        if row["kind"] != "pr" or row["state"] != "merged" or existing.get(row["url"]) == "merged":
            continue
        # Newly merged since we last looked, or merged just now. A merge we are seeing for the
        # first time that happened weeks ago is backfill, not news.
        if row["url"] not in existing and (row["merged_at"] is None or row["merged_at"] < recent):
            continue
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
        except (KeyError, TypeError, ValueError) as exc:  # unexpected shape: skip this repo only
            errors.append(f"{repo.full_name}: {type(exc).__name__}: {exc}")

    activity = 0
    username = ctx.content.profile.github_username
    if username and not any("rate limited" in e for e in errors):
        try:
            activity = _collect_my_activity(ctx, username, now)
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
