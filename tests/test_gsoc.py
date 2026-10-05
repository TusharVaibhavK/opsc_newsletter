"""import_gsoc: curated names survive, old orgs are skipped, and a new year triggers alerts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import respx
from sqlalchemy import select

from collectors.db.models import Event, Org, ProgramYear, ProjectHistory
from collectors.jobs import JobContext
from collectors.jobs.gsoc import API_URL, apply_gsoc_data, import_gsoc


def org(name: str, years: dict[int, int], **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "url": "https://example.org",
        "category": "Data",
        "description": f"{name} does things",
        "technologies": ["go", "python"],
        "topics": ["ml"],
        "ideas_url": f"https://example.org/{name}/ideas",
        "guide_url": "",
        "irc_channel": "not a url",
        "years": {
            str(y): {
                "num_projects": n,
                "projects": [
                    {
                        "title": f"{name} project {i}",
                        "project_url": f"https://p/{name}/{y}/{i}",
                        "student_name": "Someone Private",
                    }
                    for i in range(n)
                ],
            }
            for y, n in years.items()
        },
        **extra,
    }


DATA = [
    org("Kubeflow", {2024: 8, 2025: 11, 2026: 9}),
    org("MetaBrainz Foundation Inc", {2025: 6, 2026: 7}),
    org("Tiny Recent Org", {2026: 2}),
    org("Long Gone Org", {2016: 3}),
]


def test_import_maps_curated_orgs_and_skips_old_ones(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    summary = apply_gsoc_data(ctx, DATA)
    assert "new:" not in summary  # first import: nothing to announce
    kubeflow = ctx.session.get(Org, "kubeflow")
    assert (
        kubeflow is not None
        and kubeflow.curated
        and kubeflow.ideas_url == "https://example.org/Kubeflow/ideas"
    )
    metabrainz = ctx.session.get(Org, "metabrainz")
    assert metabrainz is not None and metabrainz.name == "MetaBrainz"  # the curated name wins
    assert metabrainz.chat_url is None  # non-URL chat values are dropped
    assert ctx.session.get(Org, "tiny-recent-org") is not None
    assert ctx.session.get(Org, "long-gone-org") is None
    assert ctx.session.get(ProgramYear, ("kubeflow", "gsoc", 2025)).num_projects == 11  # type: ignore[union-attr]
    assert list(ctx.session.scalars(select(Event))) == []
    # Contributor names are never stored.
    assert "contributor_name" not in ProjectHistory.__table__.columns


def test_reimport_is_idempotent(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    apply_gsoc_data(ctx, DATA)
    count = len(list(ctx.session.scalars(select(ProjectHistory))))
    apply_gsoc_data(ctx, DATA)
    assert len(list(ctx.session.scalars(select(ProjectHistory)))) == count


def test_new_year_announces_watchlist_orgs(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    apply_gsoc_data(ctx, DATA)
    next_year = [org("Kubeflow", {2024: 8, 2025: 11, 2026: 9, 2027: 10}), *DATA[1:]]
    summary = apply_gsoc_data(ctx, next_year)
    assert "new: [2027]" in summary
    kinds = {(e.kind, e.entity_slug) for e in ctx.session.scalars(select(Event))}
    assert ("gsoc_orgs_published", "gsoc") in kinds
    assert ("org_announced", "kubeflow") in kinds
    assert ("org_not_listed", "sw360") in kinds  # on the watchlist, not in the 2027 list
    assert ("org_not_listed", "zulip") not in kinds  # curated but not on the watchlist


def test_conditional_request_skips_unchanged_data(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    with respx.mock() as router:
        route = router.get(API_URL)
        route.respond(200, json=DATA, headers={"etag": '"abc"'})
        import_gsoc(ctx)
        route.mock(
            side_effect=lambda r: httpx.Response(
                304 if r.headers.get("if-none-match") == '"abc"' else 200, json=DATA
            )
        )
        assert "304" in import_gsoc(ctx)
