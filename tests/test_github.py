"""collect_github: metric definitions, idempotent daily runs, and graceful degradation."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

import httpx
import respx
from sqlalchemy import func, select

from collectors.db.models import JobRun, Newcomer, OpenIssue, RepoSnapshot
from collectors.http import GITHUB_GRAPHQL, Http
from collectors.jobs import JobContext, run_job
from collectors.jobs.github import collect_github, login_hash, repo_metrics

NOW = dt.datetime(2026, 10, 5, 0, 30)


def ts(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue(
    number: int,
    created: float,
    *,
    comments: tuple[tuple[float, str, str], ...] = (),
    assigned: bool = False,
    timeline: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "url": f"https://github.com/kubeflow/pipelines/issues/{number}",
        "createdAt": ts(created),
        "state": "OPEN",
        "author": {"login": "reporter"},
        "comments": {
            "totalCount": len(comments),
            "nodes": [
                {"createdAt": ts(h), "authorAssociation": a, "author": {"login": who}}
                for h, a, who in comments
            ],
        },
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
    reviews: tuple[tuple[float, str], ...] = (),
    merged: float | None = None,
    bot: bool = False,
) -> dict[str, Any]:
    return {
        "number": number,
        "url": f"https://github.com/kubeflow/pipelines/pull/{number}",
        "createdAt": ts(created),
        "mergedAt": ts(merged) if merged is not None else None,
        "state": "OPEN",
        "authorAssociation": assoc,
        "author": {"__typename": "Bot" if bot else "User", "login": login},
        "reviews": {
            "nodes": [{"createdAt": ts(h), "author": {"login": who}} for h, who in reviews]
        },
    }


def repository() -> dict[str, Any]:
    linked = {
        "__typename": "CrossReferencedEvent",
        "createdAt": ts(3),
        "source": {"__typename": "PullRequest", "state": "OPEN"},
    }
    return {
        "nameWithOwner": "kubeflow/pipelines",
        "stargazerCount": 4200,
        "hasIssuesEnabled": True,
        "openGfi": {
            "totalCount": 3,
            "nodes": [issue(1, 5), issue(2, 6, assigned=True), issue(3, 7, timeline=(linked,))],
        },
        "recentGfi": {
            "nodes": [
                issue(10, 10, comments=((8, "NONE", "newcomer1"),)),  # claimed by comment after 2h
                issue(
                    11, 30, timeline=({"__typename": "AssignedEvent", "createdAt": ts(24)},)
                ),  # 6h
                issue(  # a maintainer's comment isn't a claim; the linked PR at 40h ago is (10h)
                    12,
                    50,
                    comments=((49, "MEMBER", "maintainer"),),
                    timeline=(
                        {
                            "__typename": "CrossReferencedEvent",
                            "createdAt": ts(40),
                            "source": {"__typename": "PullRequest", "state": "OPEN"},
                        },
                    ),
                ),
            ]
        },
        "recentPrs": {
            "nodes": [
                pr(
                    100, 24 * 10, "CONTRIBUTOR", "a", reviews=((24 * 10 - 24, "maint"),)
                ),  # 24h to review
                pr(101, 24 * 20, "CONTRIBUTOR", "b", merged=24 * 20 - 48),  # merged after 48h
                pr(
                    102,
                    24 * 30,
                    "FIRST_TIME_CONTRIBUTOR",
                    "newbie",
                    reviews=((24 * 30 - 12, "maint"),),
                ),  # 12h
                pr(103, 24 * 5, "NONE", "c"),  # no response yet
                pr(104, 24 * 6, "MEMBER", "maint"),  # maintainers' own PRs don't count
                pr(105, 24 * 7, "FIRST_TIMER", "dependabot[bot]", bot=True),  # bots never count
                pr(106, 12, "FIRST_TIME_CONTRIBUTOR", "fresh"),  # too new to judge response time
                pr(107, 24 * 90, "CONTRIBUTOR", "old"),  # older than 60 days
            ]
        },
        "openPrs": {
            "nodes": [
                pr(106, 12, "FIRST_TIME_CONTRIBUTOR", "fresh"),
                pr(108, 30, "FIRST_TIME_CONTRIBUTOR", "reviewed", reviews=((20, "maint"),)),
            ]
        },
    }


def test_metric_definitions() -> None:
    m = repo_metrics(repository(), NOW, has_labels=True)
    snap = m["snapshot"]
    assert snap["open_gfi_count"] == 3
    assert snap["open_gfi_unclaimed"] == 1  # #2 is assigned, #3 has a linked PR
    assert snap["gfi_median_claim_hours"] == 6.0  # median of 2, 6, 10
    assert snap["median_first_response_hours"] == 24.0  # median of 24, 48, 12
    assert snap["unanswered_pr_share"] == 0.25  # 1 of 4 eligible PRs unanswered
    assert snap["open_newcomer_prs"] == 1  # "reviewed" already has a review
    assert set(m["newcomers"]) == {"newbie", "fresh", "reviewed"}  # bot excluded
    assert {i["number"] for i in m["open_issues"]} == {1, 2, 3}


def test_repo_without_beginner_labels() -> None:
    repo = repository()
    repo.pop("openGfi")
    repo.pop("recentGfi")
    snap = repo_metrics(repo, NOW, has_labels=False)["snapshot"]
    assert snap["open_gfi_count"] is None and snap["gfi_median_claim_hours"] is None


def mock_graphql(router: respx.Router, counter: list[int]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        if "RepoMetrics" in body["query"]:
            return httpx.Response(200, json={"data": {"rateLimit": {}, "repository": repository()}})
        return httpx.Response(200, json={"data": {"rateLimit": {}, "search": {"nodes": []}}})

    router.post(GITHUB_GRAPHQL).mock(side_effect=respond)


def test_collect_saves_snapshot_and_hashes_logins(make_ctx: Callable[..., JobContext]) -> None:
    calls: list[int] = []
    with respx.mock(assert_all_called=False) as router:
        mock_graphql(router, calls)
        ctx = make_ctx(only_repo="kubeflow/pipelines", clock=lambda: NOW)
        summary = collect_github(ctx)
    assert summary.startswith("1 repos collected")
    snap = ctx.session.get(RepoSnapshot, ("kubeflow/pipelines", dt.date(2026, 10, 5)))
    assert snap is not None and snap.stars == 4200 and snap.new_contributors_30d == 3
    assert ctx.session.scalar(select(func.count()).select_from(OpenIssue)) == 3
    hashes = set(ctx.session.scalars(select(Newcomer.login_hash)))
    assert login_hash("newbie") in hashes and "newbie" not in hashes


def test_same_day_rerun_spends_no_calls(make_ctx: Callable[..., JobContext]) -> None:
    calls: list[int] = []
    with respx.mock(assert_all_called=False) as router:
        mock_graphql(router, calls)
        collect_github(make_ctx(only_repo="kubeflow/pipelines", clock=lambda: NOW))
        first = len(calls)
        summary = collect_github(make_ctx(only_repo="kubeflow/pipelines", clock=lambda: NOW))
        assert len(calls) == first and "1 already fresh" in summary
        collect_github(make_ctx(only_repo="kubeflow/pipelines", force=True, clock=lambda: NOW))
        assert len(calls) == first + 1
    assert (
        len(list(make_ctx().session.scalars(select(RepoSnapshot)))) == 1
    )  # upserted, not duplicated


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
        return httpx.Response(
            200, json={"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}
        )

    with respx.mock(assert_all_called=False) as router:
        router.post(GITHUB_GRAPHQL).mock(side_effect=respond)
        ctx = make_ctx(clock=lambda: NOW)
        run = run_job("collect_github", collect_github, ctx)
    assert run.status == "error" and "rate limited after 1 repos" in (run.summary or "")
    assert ctx.session.scalar(select(func.count()).select_from(RepoSnapshot)) == 1  # kept
    assert ctx.session.scalar(select(func.count()).select_from(JobRun)) == 1
