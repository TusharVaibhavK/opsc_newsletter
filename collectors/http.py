"""One HTTP client for all jobs: retries with backoff, conditional GETs, robots.txt, counts."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from collectors.config import USER_AGENT

GITHUB_GRAPHQL = "https://api.github.com/graphql"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_WAIT_SECONDS = 120  # never block a CI run for an hour waiting out a rate limit


class GitHubError(RuntimeError):
    pass


class RateLimited(GitHubError):
    pass


def _is_rate_limited(resp: httpx.Response) -> bool:
    if resp.status_code not in (403, 429):
        return False
    if resp.headers.get("x-ratelimit-remaining") == "0":
        return True
    return "rate limit" in resp.text[:500].lower()


class Http:
    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.token = token
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.calls = 0
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser | None] = {}

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Http:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _wait(self, resp: httpx.Response | None, attempt: int) -> float:
        if resp is not None:
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                return min(float(retry_after), MAX_WAIT_SECONDS)
            reset = resp.headers.get("x-ratelimit-reset")
            if resp.headers.get("x-ratelimit-remaining") == "0" and reset and reset.isdigit():
                return min(max(float(reset) - time.time(), 1.0), MAX_WAIT_SECONDS)
        return min(2.0**attempt + random.uniform(0, 1), MAX_WAIT_SECONDS)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request, retrying timeouts, 5xx, 429 and rate-limited 403s with backoff."""
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self.calls += 1
            try:
                resp = self.client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    raise
                self.sleep(self._wait(None, attempt))
                continue
            if resp.status_code in RETRY_STATUSES or _is_rate_limited(resp):
                if attempt == self.max_attempts:
                    return resp
                self.sleep(self._wait(resp, attempt))
                continue
            return resp
        raise RuntimeError("unreachable") from last_exc  # pragma: no cover

    def get(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> httpx.Response:
        """GET with optional conditional headers; a 304 means the cached copy is still current."""
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        return self.request("GET", url, headers=headers)

    def allowed_by_robots(self, url: str) -> bool:
        """RFC 9309: a missing robots.txt (4xx) allows everything; 5xx or network errors don't."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None
            try:
                resp = self.request("GET", f"{origin}/robots.txt")
            except httpx.TransportError:
                parser = None
            else:
                if resp.status_code >= 500:
                    parser = None
                else:
                    parser = RobotFileParser()
                    parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is not None and parser.can_fetch(USER_AGENT, url)

    def graphql(self, query: str, variables: dict[str, Any], attempts: int = 2) -> dict[str, Any]:
        """Run a GitHub GraphQL query. Raises GitHubError on any error in the response.

        A reply that isn't JSON, or a GraphQL-level timeout, is retried once: GitHub produces
        both when a query on a very large repo runs past its time limit.
        """
        if not self.token:
            raise GitHubError("GITHUB_TOKEN is required for the GitHub GraphQL API")
        problem = "no attempts made"
        for attempt in range(1, attempts + 1):
            resp = self.request(
                "POST",
                GITHUB_GRAPHQL,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            if _is_rate_limited(resp):
                raise RateLimited(f"GitHub rate limit reached (HTTP {resp.status_code})")
            if resp.status_code != 200:
                raise GitHubError(f"GitHub GraphQL HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                payload: dict[str, Any] = resp.json()
            except ValueError:
                problem = f"non-JSON reply (HTTP 200, {len(resp.content)} bytes)"
            else:
                errors = payload.get("errors")
                if not errors:
                    data: dict[str, Any] = payload["data"]
                    return data
                messages = "; ".join(str(e.get("message", e)) for e in errors)
                if any(e.get("type") == "RATE_LIMITED" for e in errors):
                    raise RateLimited(messages)
                if "timeout" not in messages.lower() and "went wrong" not in messages.lower():
                    raise GitHubError(messages)
                problem = messages
            if attempt < attempts:
                self.sleep(self._wait(None, attempt))
        raise GitHubError(f"GitHub GraphQL failed after {attempts} attempts: {problem}")
