"""The page watcher: extraction, stable fingerprints, alerts only on meaningful changes."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import httpx
import respx
from sqlalchemy import select

from collectors.db.models import Event, WatchedPage
from collectors.jobs import JobContext
from collectors.jobs.pages import Target, check, extract, fingerprint, next_year_url

URL = "https://example.org/gsoc/2026/ideas"
NEXT = "https://example.org/gsoc/2027/ideas"
FILLER = "<p>" + "Some context about the project and how to apply. " * 20 + "</p>"


def page(*ideas: str, extra: str = "") -> str:
    body = "".join(f"<h3>{i}</h3><p>Details about {i}.</p>" for i in ideas)
    main = f"<main><h2>Getting started</h2>{FILLER}{body}{extra}</main>"
    return f"<html><body><nav>Menu</nav>{main}</body></html>"


def test_extract_markdown_and_html() -> None:
    md = "# Ideas\n## Intro\n## Add tracing\n## Faster parser\n## Bulk import\n### Skills\n"
    assert extract(md, "text/plain").headings == ["Add tracing", "Faster parser", "Bulk import"]
    html = page("Idea one: tracing", "Idea two: caching", "Idea three: FHIR")
    assert extract(html, "text/html").headings == [
        "Idea one: tracing",
        "Idea two: caching",
        "Idea three: FHIR",
    ]


def test_numbered_ideas_win_over_page_furniture() -> None:
    html = page(
        "Key Dates",
        "Eligibility",
        "Project 1: Tracing",
        "Project 2: Caching",
        "Project 3: Search",
        "Feedback",
    )
    assert extract(html, "text/html").headings == [
        "Project 1: Tracing",
        "Project 2: Caching",
        "Project 3: Search",
    ]


def test_fingerprint_ignores_shuffles_and_relative_times() -> None:
    a = "Alpha\nBeta\nUpdated 3 hours ago\n1,204 views"
    b = "Beta\nAlpha\nUpdated 5 hours ago\n1,377 views"
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(a + "\nGamma")


def test_next_year_url() -> None:
    assert next_year_url(URL, 2026) == NEXT
    assert next_year_url("https://example.org/ideas", 2026) is None
    confluence = "https://x.atlassian.net/wiki/spaces/RES/pages/752844801/Summer+of+Code+2026"
    assert next_year_url(confluence, 2026) is None  # page IDs, not years, address Confluence pages


def events(ctx: JobContext) -> list[Event]:
    return list(ctx.session.scalars(select(Event).order_by(Event.occurred_at)))


def test_ideas_page_lifecycle(make_ctx: Callable[..., JobContext]) -> None:
    target = Target(URL, "ideas", "org", "kubeflow", "Kubeflow ideas page")
    responses = iter(
        [
            httpx.Response(
                200,
                text=page("Tracing", "Caching", "Search"),
                headers={"content-type": "text/html", "etag": '"v1"'},
            ),
            httpx.Response(304),
            httpx.Response(
                200,
                text=page("Tracing", "Caching", "Search", "Benchmarks"),
                headers={"content-type": "text/html"},
            ),
            httpx.Response(
                200,
                text=page(
                    "Tracing", "Caching", "Search", "Benchmarks", extra="<p>New mentor added.</p>"
                ),
                headers={"content-type": "text/html"},
            ),
        ]
    )
    clock = [dt.datetime(2026, 10, 5, 1, 0)]
    ctx = make_ctx(clock=lambda: clock[0])

    def next_day() -> None:
        clock[0] += dt.timedelta(days=1)

    with respx.mock() as router:
        router.get("https://example.org/robots.txt").respond(404)
        router.get(URL).mock(side_effect=lambda _r: next(responses))
        assert check(ctx, target) == "baseline"
        assert events(ctx) == []  # first sight is never an alert
        next_day()
        assert check(ctx, target) == "unchanged"  # 304
        watched = ctx.session.get(WatchedPage, URL)
        assert (
            watched is not None and watched.last_status == 200
        )  # a 304 doesn't look like a dead link
        next_day()
        assert check(ctx, target) == "changed"
        next_day()
        assert check(ctx, target) == "edited"  # text-only edit: snapshot, no alert
    found = events(ctx)
    assert len(found) == 1 and found[0].kind == "ideas_changed"
    assert found[0].detail["added"] == ["Benchmarks"]


def test_next_year_page_needs_real_new_content(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    current = Target(URL, "ideas", "org", "kubeflow", "Kubeflow ideas page")
    upcoming = Target(NEXT, "ideas_next", "org", "kubeflow", "Kubeflow next-year ideas page")
    this_year = page("Tracing", "Caching", "Search", extra="<p>GSoC 2026</p>")
    with respx.mock() as router:
        router.get("https://example.org/robots.txt").respond(404)
        router.get(URL).respond(200, text=this_year, headers={"content-type": "text/html"})
        check(ctx, current)
        nxt = router.get(NEXT)
        nxt.respond(404)
        assert check(ctx, upcoming) == "not-yet"
        nxt.respond(
            200, text=this_year.replace("2026", "2025"), headers={"content-type": "text/html"}
        )
        assert check(ctx, upcoming) == "not-yet"  # never mentions 2027
        nxt.respond(
            200,
            text=page("Tracing", "Caching", "Search", extra="<p>GSoC 2027 ideas</p>"),
            headers={"content-type": "text/html"},
        )
        assert check(ctx, upcoming) == "published"
        assert check(ctx, upcoming) == "unchanged"
    published = [e for e in events(ctx) if e.kind == "ideas_published"]
    assert len(published) == 1


def test_wiki_redirect_is_not_a_published_page(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    upcoming = Target(NEXT, "ideas_next", "org", "kubeflow", "next")
    with respx.mock() as router:
        router.get("https://example.org/robots.txt").respond(404)
        router.get(NEXT).respond(302, headers={"location": "https://example.org/wiki/Home"})
        router.get("https://example.org/wiki/Home").respond(
            200, text=page("A", "B", "C", extra="2027"), headers={"content-type": "text/html"}
        )
        assert check(ctx, upcoming) == "not-yet"


def test_robots_txt_is_respected(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    with respx.mock(assert_all_called=False) as router:
        router.get("https://example.org/robots.txt").respond(
            200, text="User-agent: *\nDisallow: /gsoc/\n"
        )
        page_route = router.get(URL)
        assert check(ctx, Target(URL, "ideas", "org", "kubeflow", "x")) == "robots"
        assert not page_route.called
