"""collect_github: metric definitions, bot and self-claim handling, daily idempotency, my PRs."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

import httpx
import respx
from sqlalchemy import func, select

from collectors.content import Content
from collectors.db.models import Event, JobRun, MyActivity, Newcomer, OpenIssue, RepoSnapshot
from collectors.http import GITHUB_GRAPHQL, Http
from collectors.jobs import JobContext, run_job
from collectors.jobs.github import (
    claimed_at,
    collect_github,
    first_response,
    login_hash,
    repo_metrics,
)

from .conftest import with_username

NOW = dt.datetime(2026, 10, 5, 0, 30)
BOTS = {"gemini-code-assist", "dependabot", "codecov"}  # GraphQL type Bot, no "[bot]" suffix

Reply = tuple[float, str, str]  # (hours after creation, authorAssociation, login)


def ts(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_ago(hours: float) -> dt.datetime:
    return NOW - dt.timedelta(hours=hours)


def who(login: str) -> dict[str, str]:
    return {"__typename": "Bot" if login in BOTS else "User", "login": login}


def replies(created: float, items: tuple[Reply, ...]) -> dict[str, Any]:
    return {
        "nodes": [
            {"createdAt": ts(created - after), "authorAssociation": assoc, "author": who(login)}
            for after, assoc, login in items
        ]
    }


def assigned_to(created: float, after: float, assignee: str) -> dict[str, Any]:
    return {
        "__typename": "AssignedEvent",
        "createdAt": ts(created - after),
        "actor": who("maintainer"),
        "assignee": who(assignee),
    }


def pr_linked(created: float, after: float, pr_author: str) -> dict[str, Any]:
    return {
        "__typename": "CrossReferencedEvent",
        "createdAt": ts(created - after),
        "actor": who(pr_author),
        "source": {"__typename": "PullRequest", "state": "OPEN", "author": who(pr_author)},
    }


def issue(
    number: int,
    created: float,
    *,
    author: str = "reporter",
    comments: tuple[Reply, ...] = (),
    assigned: bool = False,
    timeline: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "url": f"https://github.com/kubeflow/pipelines/issues/{number}",
        "createdAt": ts(created),
        "state": "OPEN",
        "author": {"login": author},
        "comments": {"totalCount": len(comments), **replies(created, comments)},
        "assignees": {"totalCount": int(assigned)},
        "labels": {"nodes": [{"name": "good first issue"}]},
        "timelineItems": {"nodes": list(timeline)},
    }


def pr(
    number: int,
    created: float,
    assoc: str,
    login: str,
    *,
    reviews: tuple[Reply, ...] = (),
    comments: tuple[Reply, ...] = (),
    merged_after: float | None = None,
) -> dict[str, Any]:
    return {
        "number": number,
        "url": f"https://github.com/kubeflow/pipelines/pull/{number}",
        "createdAt": ts(created),
        "mergedAt": ts(created - merged_after) if merged_after is not None else None,
        "state": "MERGED" if merged_after is not None else "OPEN",
        "authorAssociation": assoc,
        "author": who(login),
        "reviews": replies(created, reviews),
        "comments": replies(created, comments),
    }


def repository() -> dict[str, Any]:
    recent_prs = [
        # Outside contributors who have had something merged before.
        pr(100, 24 * 10, "CONTRIBUTOR", "a", reviews=((24, "MEMBER", "maint"),)),  # 24 h
        pr(101, 24 * 20, "CONTRIBUTOR", "b", merged_after=48),  # merged after 48 h
        # Newcomers: GitHub shows "no association" for people without a merged contribution.
        pr(102, 24 * 29, "NONE", "newbie", comments=((12, "MEMBER", "maint"),)),  # 12 h
        pr(103, 24 * 5, "NONE", "c"),  # nobody has replied
        pr(104, 24 * 6, "MEMBER", "maint"),  # maintainers' own PRs are excluded
        pr(105, 24 * 7, "NONE", "dependabot"),  # bots are excluded, and are not newcomers
        pr(106, 12, "NONE", "fresh"),  # too new to judge response time
        pr(107, 24 * 90, "CONTRIBUTOR", "old"),  # older than the 60-day window
        # Replies that must not count: a review bot, and another newcomer chatting.
        pr(108, 30, "NONE", "bot-reviewed", reviews=((1, "CONTRIBUTOR", "gemini-code-assist"),)),
        pr(109, 40, "NONE", "talker", comments=((3, "NONE", "other-newcomer"),)),
        pr(110, 24 * 4, "NONE", "replied", reviews=((10, "MEMBER", "maint"),)),  # 10 h
    ]
    open_prs = [p for p in recent_prs if p["number"] in (106, 108, 109, 110)]
    return {
        "nameWithOwner": "kubeflow/pipelines",
        "stargazerCount": 4200,
        "hasIssuesEnabled": True,
        "openGfi": {
            "totalCount": 3,
            "nodes": [
                issue(1, 5),
                issue(2, 6, assigned=True),
                issue(3, 7, timeline=(pr_linked(7, 4, "outsider"),)),
            ],
        },
        "recentGfi": {
            "nodes": [
                issue(10, 10, comments=((2, "NONE", "newcomer1"),)),  # claimed after 2 h
                issue(11, 30, timeline=(assigned_to(30, 6, "taker"),)),  # 6 h
                issue(  # a maintainer comment is not a claim; the outsider's linked PR is (10 h)
                    12,
                    50,
                    comments=((1, "MEMBER", "maintainer"),),
                    timeline=(pr_linked(50, 10, "outsider"),),
                ),
                # Neither of these is a claim by someone else:
                issue(13, 20, author="maint-filed", timeline=(assigned_to(20, 0, "maint-filed"),)),
                issue(14, 40, timeline=(pr_linked(40, 1, "reporter"),)),  # the author's own PR
            ]
        },
        "recentPrs": {"nodes": recent_prs},
        "openPrs": {"nodes": open_prs},
    }


def test_metric_definitions() -> None:
    m = repo_metrics(repository(), NOW, has_labels=True)
    snap = m["snapshot"]
    assert snap["open_gfi_count"] == 3
    assert snap["open_gfi_unclaimed"] == 1  # #2 is assigned, #3 has a linked PR
    assert snap["gfi_median_claim_hours"] == 6.0  # median of 2, 6, 10; self-claims ignored
    assert snap["median_first_response_hours"] == 18.0  # median of 24, 48, 12, 10
    assert snap["unanswered_pr_share"] == 0.2  # 1 of 5 sampled PRs has no human reply
    assert snap["prs_sampled"] == 5
    assert snap["open_newcomer_prs"] == 3  # 106 nobody, 108 bot only, 109 newcomer chat only
    assert set(m["newcomers"]) == {"newbie", "c", "fresh", "bot-reviewed", "talker", "replied"}
    assert {i["number"] for i in m["open_issues"]} == {1, 2, 3}


def test_self_claims_bots_and_maintainers_are_not_claims() -> None:
    self_assigned = issue(1, 10, author="maint", timeline=(assigned_to(10, 0, "maint"),))
    assert claimed_at(self_assigned) is None
    assert claimed_at(issue(2, 10, timeline=(pr_linked(10, 1, "reporter"),))) is None
    assert claimed_at(issue(3, 10, comments=((1, "NONE", "codecov"),))) is None
    assert claimed_at(issue(4, 10, comments=((1, "MEMBER", "maintainer"),))) is None
    assert claimed_at(issue(5, 10, timeline=(pr_linked(10, 1, "dependabot"),))) is None
    assigned = issue(6, 10, timeline=(assigned_to(10, 4, "someone"),))
    assert claimed_at(assigned) == hours_ago(6)
    assert claimed_at(issue(7, 10, comments=((3, "NONE", "newcomer"),))) == hours_ago(7)


def test_first_response_needs_a_human_with_standing() -> None:
    assert first_response(pr(1, 100, "NONE", "newbie")) is None
    bots_only = pr(
        1,
        100,
        "NONE",
        "newbie",
        reviews=((1, "CONTRIBUTOR", "gemini-code-assist"),),
        comments=((2, "NONE", "codecov"),),
    )
    assert first_response(bots_only) is None
    assert first_response(pr(1, 100, "NONE", "newbie", comments=((2, "NONE", "other"),))) is None
    assert first_response(pr(1, 100, "NONE", "newbie", comments=((2, "NONE", "newbie"),))) is None
    human = pr(
        1,
        100,
        "NONE",
        "newbie",
        reviews=((5, "CONTRIBUTOR", "regular"),),
        comments=((3, "MEMBER", "maint"),),
    )
    assert first_response(human) == hours_ago(97)  # the earlier of the two
    assert first_response(pr(1, 100, "NONE", "newbie", merged_after=30)) == hours_ago(70)


def test_repo_without_beginner_labels() -> None:
    repo = repository()
    repo.pop("openGfi")
    repo.pop("recentGfi")
    snap = repo_metrics(repo, NOW, has_labels=False)["snapshot"]
    assert snap["open_gfi_count"] is None and snap["gfi_median_claim_hours"] is None


def search_node(
    repo: str, number: int, state: str, created: float, merged: float | None = None
) -> dict[str, Any]:
    return {
        "url": f"https://github.com/{repo}/pull/{number}",
        "title": f"PR {number}",
        "state": state,
        "createdAt": ts(created),
        "mergedAt": ts(merged) if merged is not None else None,
        "closedAt": ts(merged) if merged is not None else None,
        "repository": {"nameWithOwner": repo, "owner": {"login": repo.split("/")[0]}},
    }


def mock_graphql(
    router: respx.Router,
    calls: list[str],
    my_prs: list[dict[str, Any]] | None = None,
    my_reviews: list[dict[str, Any]] | None = None,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        if "RepoMetrics" in body["query"]:
            calls.append("repo")
            data = {"rateLimit": {}, "repository": repository()}
        else:
            calls.append("search")
            nodes = my_reviews if "reviewed-by:" in body["variables"]["q"] else my_prs
            data = {"rateLimit": {}, "search": {"nodes": nodes or []}}
        return httpx.Response(200, json={"data": data})

    router.post(GITHUB_GRAPHQL).mock(side_effect=respond)


def test_collect_saves_snapshot_and_hashes_logins(make_ctx: Callable[..., JobContext]) -> None:
    calls: list[str] = []
    with respx.mock(assert_all_called=False) as router:
        mock_graphql(router, calls)
        ctx = make_ctx(only_repo="kubeflow/pipelines", clock=lambda: NOW)
        summary = collect_github(ctx)
    assert summary.startswith("1 repos collected") and calls == ["repo"]  # no username: no search
    snap = ctx.session.get(RepoSnapshot, ("kubeflow/pipelines", dt.date(2026, 10, 5)))
    assert snap is not None and snap.stars == 4200 and snap.new_contributors_30d == 6
    assert ctx.session.scalar(select(func.count()).select_from(OpenIssue)) == 3
    hashes = set(ctx.session.scalars(select(Newcomer.login_hash)))
    assert login_hash("newbie") in hashes and "newbie" not in hashes
    assert login_hash("dependabot") not in hashes


def test_same_day_rerun_spends_no_repo_calls(make_ctx: Callable[..., JobContext]) -> None:
    calls: list[str] = []
    with respx.mock(assert_all_called=False) as router:
        mock_graphql(router, calls)
        collect_github(make_ctx(only_repo="kubeflow/pipelines", clock=lambda: NOW))
        summary = collect_github(make_ctx(only_repo="kubeflow/pipelines", clock=lambda: NOW))
        assert calls.count("repo") == 1 and "1 already fresh" in summary
        collect_github(make_ctx(only_repo="kubeflow/pipelines", force=True, clock=lambda: NOW))
        assert calls.count("repo") == 2
    assert len(list(make_ctx().session.scalars(select(RepoSnapshot)))) == 1  # upserted


def test_skips_cleanly_without_a_token(make_ctx: Callable[..., JobContext]) -> None:
    with Http(None) as anonymous:
        run = run_job("collect_github", collect_github, make_ctx(http=anonymous))
    assert run.status == "skipped" and "GITHUB_TOKEN" in (run.summary or "")


def test_rate_limit_keeps_partial_results(make_ctx: Callable[..., JobContext]) -> None:
    state = {"n": 0}

    def respond(_request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(200, json={"data": {"rateLimit": {}, "repository": repository()}})
        errors = [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]
        return httpx.Response(200, json={"errors": errors})

    with respx.mock(assert_all_called=False) as router:
        router.post(GITHUB_GRAPHQL).mock(side_effect=respond)
        ctx = make_ctx(clock=lambda: NOW)
        run = run_job("collect_github", collect_github, ctx)
    assert run.status == "error" and "rate limited after 1 repos" in (run.summary or "")
    assert ctx.session.scalar(select(func.count()).select_from(RepoSnapshot)) == 1  # kept
    assert ctx.session.scalar(select(func.count()).select_from(JobRun)) == 1


def merge_event_urls(ctx: JobContext) -> set[str]:
    events = ctx.session.scalars(select(Event).where(Event.kind == "pr_merged"))
    return {e.url for e in events if e.url}


def test_my_activity_skips_own_repos_and_backfill(
    make_ctx: Callable[..., JobContext], pinned: Content
) -> None:
    mine = with_username(pinned, "Me")  # GitHub logins are case-insensitive
    old_merge = search_node("kubeflow/pipelines", 1, "MERGED", 24 * 70, merged=24 * 60)
    fresh_merge = search_node("kubeflow/pipelines", 2, "MERGED", 30, merged=5)
    still_open = search_node("kubeflow/pipelines", 3, "OPEN", 10)
    elsewhere = search_node("someone/else", 4, "MERGED", 20, merged=10)
    side_project = search_node("me/side-project", 5, "MERGED", 24 * 100, merged=24 * 99)
    review = search_node("kubeflow/trainer", 6, "OPEN", 50)
    prs = [old_merge, fresh_merge, still_open, elsewhere, side_project]

    ctx = make_ctx(content=mine, only_repo="kubeflow/pipelines", clock=lambda: NOW)
    # Left over from before own repos were excluded, plus a stale merge celebration.
    ctx.session.add_all(
        [
            MyActivity(
                url="https://github.com/Me/old/pull/9",
                kind="pr",
                repo="Me/old",
                title="x",
                state="merged",
                opened_at=dt.datetime(2026, 1, 1),
            ),
            Event(
                dedupe_key="pr-merged:own",
                kind="pr_merged",
                title="own",
                url="https://github.com/me/old/pull/9",
                occurred_at=NOW,
            ),
            Event(
                dedupe_key="pr-merged:ancient",
                kind="pr_merged",
                title="ancient",
                url="https://github.com/x/y/pull/1",
                occurred_at=NOW - dt.timedelta(days=45),
            ),
        ]
    )
    ctx.session.flush()
    with respx.mock(assert_all_called=False) as router:
        mock_graphql(router, [], my_prs=prs, my_reviews=[review])
        summary = collect_github(ctx)
    assert "5 of your PRs/reviews" in summary  # the side project is not counted
    urls = {a.url for a in ctx.session.scalars(select(MyActivity))}
    assert "https://github.com/me/side-project/pull/5" not in urls
    assert "https://github.com/Me/old/pull/9" not in urls
    # Not the 60-day-old merge (backfill), the own repo, or the 45-day-old event.
    assert merge_event_urls(ctx) == {
        "https://github.com/kubeflow/pipelines/pull/2",
        "https://github.com/someone/else/pull/4",
    }
    org = ctx.session.scalar(select(MyActivity.org).where(MyActivity.url == fresh_merge["url"]))
    assert org == "kubeflow"


def test_pr_that_gets_merged_is_announced_once(
    make_ctx: Callable[..., JobContext], pinned: Content
) -> None:
    mine = with_username(pinned, "me")
    prs = [search_node("kubeflow/pipelines", 3, "OPEN", 24 * 5)]
    with respx.mock(assert_all_called=False) as router:
        mock_graphql(router, [], my_prs=prs)
        ctx = make_ctx(content=mine, only_repo="kubeflow/pipelines", clock=lambda: NOW)
        collect_github(ctx)
        assert merge_event_urls(ctx) == set()
        # Merged four days ago: outside the "just merged" window, but we saw it open before.
        prs[:] = [search_node("kubeflow/pipelines", 3, "MERGED", 24 * 5, merged=24 * 4)]
        collect_github(ctx)
        assert merge_event_urls(ctx) == {"https://github.com/kubeflow/pipelines/pull/3"}
        collect_github(ctx)
    merges = select(func.count()).select_from(Event).where(Event.kind == "pr_merged")
    assert ctx.session.scalar(merges) == 1
