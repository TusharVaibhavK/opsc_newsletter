"""Reconcile content/*.yaml into the database. YAML wins; nothing is written back to content/."""

from __future__ import annotations

import re

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from collectors.content import Content
from collectors.content import Org as OrgYaml
from collectors.db.models import Org, OrgProgram, Program, ProgramCycle, Repo
from collectors.db.session import upsert


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def effective_links(org: OrgYaml | None, row: Org | None) -> dict[str, str | None]:
    """Links for the site and the page watcher: YAML overrides first, else the GSoC import."""
    links = org.links if org else None

    def pick(override: object, imported: str | None) -> str | None:
        return str(override) if override else imported

    return {
        "homepage": pick(links and links.homepage, row.homepage if row else None),
        "ideas": pick(links and links.ideas, row.ideas_url if row else None),
        "guide": pick(links and links.guide, row.guide_url if row else None),
        "chat": pick(links and links.chat, row.chat_url if row else None),
        "ai_policy": str(links.ai_policy) if links and links.ai_policy else None,
        "ideas_next": str(links.ideas_next) if links and links.ideas_next else None,
    }


def sync_content(session: Session, content: Content) -> dict[str, int]:
    # Programs and their cycles are fully derived from YAML.
    upsert(
        session,
        Program,
        [
            {
                "slug": p.slug,
                "name": p.name,
                "organizer": p.organizer,
                "url": str(p.url),
                "kind": p.kind,
                "paid": p.paid,
                "watch_urls": [str(u) for u in p.watch_urls],
            }
            for p in content.programs
        ],
    )
    program_slugs = [p.slug for p in content.programs]
    session.execute(delete(Program).where(Program.slug.not_in(program_slugs)))
    session.execute(delete(ProgramCycle))
    cycles = [
        {
            "program": p.slug,
            "cycle": c.name,
            "event": e.kind,
            "label": e.label or "",
            "date": e.date,
            "precision": e.precision,
            "confirmed": e.confirmed,
            "source_url": str(c.source_url) if c.source_url else None,
        }
        for p in content.programs
        for c in p.cycles
        for e in c.events
    ]
    if cycles:
        session.execute(insert(ProgramCycle), cycles)

    # Curated orgs. An earlier GSoC import may have created the same org under a slugified name;
    # rename it to the curated slug (foreign keys cascade) instead of creating a duplicate.
    for org in content.orgs:
        existing = session.scalars(select(Org).where(Org.gsoc_name == org.api_name)).first()
        if existing and existing.slug != org.slug:
            clash = session.get(Org, org.slug)
            if clash is not None:
                session.delete(clash)
                session.flush()
            session.execute(update(Org).where(Org.slug == existing.slug).values(slug=org.slug))
            session.flush()
            session.expire_all()
    upsert(
        session,
        Org,
        [
            {
                "slug": o.slug,
                "name": o.name,
                "gsoc_name": o.api_name,
                "curated": True,
                "languages": o.languages,
                "tracks": list(o.tracks),
                "github_owners": o.github_owners,
            }
            for o in content.orgs
        ],
    )
    curated = [o.slug for o in content.orgs]
    session.execute(update(Org).where(Org.slug.not_in(curated)).values(curated=False))

    session.execute(delete(OrgProgram))
    org_programs = [{"org": o.slug, "program": p} for o in content.orgs for p in o.programs]
    if org_programs:
        session.execute(insert(OrgProgram), org_programs)

    repos = [
        {"full_name": r.name, "org": o.slug, "gfi_labels": r.gfi_labels, "tracked": True}
        for o in content.orgs
        for r in o.repos
    ]
    upsert(session, Repo, repos)
    session.execute(
        update(Repo)
        .where(Repo.full_name.not_in([r["full_name"] for r in repos]))
        .values(tracked=False)
    )
    session.flush()
    return {
        "programs": len(program_slugs),
        "cycles": len(cycles),
        "orgs": len(curated),
        "repos": len(repos),
    }
