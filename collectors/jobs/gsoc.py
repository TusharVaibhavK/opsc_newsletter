"""import_gsoc: GSoC history for every org from the GSoC Organizations API.

The API is community-maintained, scraped from the official archive; verify surprising numbers
against https://summerofcode.withgoogle.com/archive before relying on them.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select

from collectors.config import RECENT_GSOC_YEARS
from collectors.db.models import Org, ProgramYear, ProjectHistory, WatchedPage
from collectors.db.session import upsert
from collectors.jobs import JobContext, emit
from collectors.sync import slugify

API_URL = "https://api.gsocorganizations.dev/organizations.json"
ARCHIVE_URL = "https://summerofcode.withgoogle.com/programs"
GSOC = "gsoc"


def _http_or_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if value.startswith(("http://", "https://")) else None


def _project_key(project: dict[str, Any]) -> str:
    basis = project.get("project_url") or project.get("title") or ""
    return hashlib.sha256(str(basis).encode()).hexdigest()[:32]


def import_gsoc(ctx: JobContext) -> str:
    page = ctx.session.get(WatchedPage, API_URL) or WatchedPage(
        url=API_URL, kind="source", entity_type="source", entity_slug="gsoc-api"
    )
    resp = ctx.http.get(
        API_URL,
        etag=None if ctx.force else page.etag,
        last_modified=None if ctx.force else page.last_modified,
    )
    page.last_checked_at = ctx.now
    page.last_status = resp.status_code
    if resp.status_code == 304:
        ctx.session.add(page)
        return "unchanged since last import (HTTP 304)"
    resp.raise_for_status()
    summary = apply_gsoc_data(ctx, resp.json())
    page.etag = resp.headers.get("etag")
    page.last_modified = resp.headers.get("last-modified")
    page.last_changed_at = page.last_checked_at
    page.consecutive_errors = 0
    ctx.session.add(page)
    return summary


def apply_gsoc_data(ctx: JobContext, data: list[dict[str, Any]]) -> str:
    session = ctx.session
    known_years = set(
        session.scalars(select(ProgramYear.year).where(ProgramYear.program == GSOC).distinct())
    )
    api_years = {int(y) for org in data for y in org.get("years", {})}
    if not api_years:
        raise ValueError("GSoC API returned no years; refusing to import an empty dataset")
    recent_from = max(api_years) - RECENT_GSOC_YEARS + 1

    rows_by_name = {o.gsoc_name: o for o in session.scalars(select(Org)) if o.gsoc_name}
    taken_slugs = set(session.scalars(select(Org.slug)))

    curated_rows: list[dict[str, Any]] = []
    other_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    project_rows: list[dict[str, Any]] = []
    present: dict[int, set[str]] = {}

    for item in data:
        name = item["name"]
        years = {int(y): v for y, v in item.get("years", {}).items()}
        existing = rows_by_name.get(name)
        curated = bool(existing and existing.curated)
        if not curated and not any(y >= recent_from for y in years):
            continue  # old orgs that are unlikely to return; skip to keep the dataset small
        if existing:
            slug = existing.slug
        else:
            base = slugify(name) or "org"
            slug, n = base, 2
            while slug in taken_slugs:
                slug, n = f"{base}-{n}", n + 1
            taken_slugs.add(slug)
        row = {
            "slug": slug,
            "gsoc_name": name,
            "category": item.get("category") or None,
            "description": item.get("description") or None,
            "technologies": sorted(set(item.get("technologies") or [])),
            "topics": sorted(set(item.get("topics") or [])),
            "homepage": _http_or_none(item.get("url")),
            "ideas_url": _http_or_none(item.get("ideas_url")),
            "guide_url": _http_or_none(item.get("guide_url")),
            "chat_url": _http_or_none(item.get("irc_channel")),
        }
        if curated and existing:
            # The name comes from content/ and must not be overwritten; it is only here because
            # SQLite checks NOT NULL before resolving the upsert conflict.
            curated_rows.append({**row, "name": existing.name, "curated": True})
        else:
            other_rows.append({**row, "name": name, "curated": False})
        for year, info in years.items():
            present.setdefault(year, set()).add(slug)
            year_rows.append(
                {
                    "org": slug,
                    "program": GSOC,
                    "year": year,
                    "num_projects": int(info.get("num_projects") or 0),
                }
            )
            if curated or year >= recent_from:
                for project in info.get("projects") or []:
                    project_rows.append(
                        {
                            "org": slug,
                            "program": GSOC,
                            "year": year,
                            "key": _project_key(project),
                            "title": (project.get("title") or "Untitled")[:500],
                            "project_url": _http_or_none(project.get("project_url")),
                            "code_url": _http_or_none(project.get("code_url")),
                        }
                    )

    gsoc_fields = (
        [k for k in curated_rows[0] if k not in ("slug", "name", "curated")] if curated_rows else []
    )
    upsert(session, Org, curated_rows, update=gsoc_fields)
    upsert(session, Org, other_rows)
    upsert(session, ProgramYear, year_rows)
    # Some orgs list two projects with the same URL; keep the first so the upsert sees unique keys.
    unique_projects = list({(p["org"], p["year"], p["key"]): p for p in project_rows}.values())
    upsert(session, ProjectHistory, unique_projects)
    session.flush()

    # A new program year is always later than every year already imported. (Old years can be
    # missing from the database because inactive orgs are skipped; they are not "new".)
    new_years = sorted(y for y in api_years if known_years and y > max(known_years))
    if known_years and new_years:
        _announce(ctx, new_years, present)
    return (
        f"{len(curated_rows) + len(other_rows)} orgs, {len(year_rows)} org-years, "
        f"{len(unique_projects)} projects, years {min(api_years)}-{max(api_years)}"
        + (f"; new: {new_years}" if known_years and new_years else "")
    )


def _announce(ctx: JobContext, new_years: list[int], present: dict[int, set[str]]) -> None:
    watch = {w.org for w in ctx.content.watchlist if w.status != "dropped"}
    curated = {o.slug: o for o in ctx.content.orgs}
    for year in new_years:
        listed = present.get(year, set())
        emit(
            ctx.session,
            key=f"gsoc-orgs:{year}",
            kind="gsoc_orgs_published",
            title=f"GSoC {year} organizations are out: {len(listed)} orgs",
            entity_type="program",
            entity_slug=GSOC,
            url=ARCHIVE_URL,
            detail={"year": year, "count": len(listed)},
        )
        for slug, org in curated.items():
            on_watchlist = slug in watch
            if slug in listed:
                emit(
                    ctx.session,
                    key=f"org-announced:{slug}:{year}",
                    kind="org_announced",
                    title=f"{org.name} is in GSoC {year}",
                    entity_type="org",
                    entity_slug=slug,
                    detail={"year": year, "watchlist": on_watchlist},
                )
            elif on_watchlist and year == max(new_years):
                emit(
                    ctx.session,
                    key=f"org-not-listed:{slug}:{year}",
                    kind="org_not_listed",
                    title=f"{org.name} is not on the GSoC {year} list",
                    entity_type="org",
                    entity_slug=slug,
                    detail={"year": year, "watchlist": True},
                )
