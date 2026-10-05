"""The shared HTTP client: backoff, rate limits, robots.txt, GraphQL errors."""

from __future__ import annotations

import httpx
import pytest
import respx

from collectors.http import GITHUB_GRAPHQL, GitHubError, Http, RateLimited


def test_retries_server_errors_with_backoff() -> None:
    waits: list[float] = []
    with Http(sleep=waits.append) as http, respx.mock() as router:
        router.get("https://example.org/x").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, text="ok")]
        )
        resp = http.get("https://example.org/x")
    assert resp.status_code == 200 and http.calls == 2 and len(waits) == 1


def test_honours_retry_after_but_caps_the_wait() -> None:
    waits: list[float] = []
    with Http(sleep=waits.append) as http, respx.mock() as router:
        router.get("https://example.org/x").mock(
            side_effect=[
                httpx.Response(429, headers={"retry-after": "7"}),
                httpx.Response(429, headers={"retry-after": "99999"}),
                httpx.Response(200),
            ]
        )
        http.get("https://example.org/x")
    assert waits == [7.0, 120.0]


def test_gives_up_after_max_attempts() -> None:
    with Http(sleep=lambda _s: None, max_attempts=3) as http, respx.mock() as router:
        route = router.get("https://example.org/x").respond(502)
        assert http.get("https://example.org/x").status_code == 502
    assert route.call_count == 3


def test_robots_rules() -> None:
    with Http(sleep=lambda _s: None) as http, respx.mock() as router:
        router.get("https://a.org/robots.txt").respond(
            200, text="User-agent: *\nDisallow: /private/\n"
        )
        router.get("https://b.org/robots.txt").respond(404)
        router.get("https://c.org/robots.txt").respond(503)
        assert http.allowed_by_robots("https://a.org/public/page")
        assert not http.allowed_by_robots("https://a.org/private/page")
        assert http.allowed_by_robots("https://b.org/anything")  # no robots.txt: allowed
        assert not http.allowed_by_robots("https://c.org/anything")  # server error: stay away


def test_graphql_errors() -> None:
    with Http(None) as anonymous, pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        anonymous.graphql("query { viewer { login } }", {})
    with Http("t", sleep=lambda _s: None) as http, respx.mock() as router:
        route = router.post(GITHUB_GRAPHQL)
        route.respond(200, json={"errors": [{"message": "Could not resolve to a Repository"}]})
        with pytest.raises(GitHubError, match="Could not resolve"):
            http.graphql("query", {})
        route.respond(200, json={"errors": [{"type": "RATE_LIMITED", "message": "limit"}]})
        with pytest.raises(RateLimited):
            http.graphql("query", {})
