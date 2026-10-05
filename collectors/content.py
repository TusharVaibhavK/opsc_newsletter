"""Schemas for the hand-curated YAML in content/, plus cross-file validation.

The Astro site mirrors these schemas in site/src/content.config.ts. Change both together.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, model_validator

from collectors.config import CONTENT_DIR

Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Level = Literal["low", "low-medium", "medium", "medium-high", "high"]
Track = Literal["backend", "ml", "data", "cloud", "tooling", "scientific", "web", "systems", "any"]
EventKind = Literal[
    "apply_open",
    "apply_close",
    "orgs_announced",
    "contribution_start",
    "contribution_end",
    "results",
    "start",
    "end",
    "other",
]

# Pairs that must be in chronological order inside one cycle.
ORDERED_PAIRS = (
    ("apply_open", "apply_close"),
    ("contribution_start", "contribution_end"),
    ("start", "end"),
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CycleEvent(Strict):
    kind: EventKind
    date: dt.date
    precision: Literal["day", "month"] = "day"
    confirmed: bool = False
    label: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> CycleEvent:
        if self.kind == "other" and not self.label:
            raise ValueError("events of kind 'other' need a label")
        if self.precision == "month" and self.date.day != 1:
            raise ValueError("month-precision dates must be written as the 1st of the month")
        return self


class Cycle(Strict):
    name: str
    source_url: HttpUrl | None = None
    events: list[CycleEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> Cycle:
        by_kind = {e.kind: e.date for e in self.events}
        for first, second in ORDERED_PAIRS:
            if first in by_kind and second in by_kind and by_kind[first] > by_kind[second]:
                raise ValueError(f"{self.name}: {first} ({by_kind[first]}) is after {second}")
        return self


class Program(Strict):
    slug: Slug
    name: str
    organizer: str
    url: HttpUrl
    kind: Literal["mentorship", "fellowship", "internship", "event"]
    paid: bool | None  # None: pay is unlisted or varies
    pay_note: str
    beginner_friendly: bool
    students_only: bool
    worldwide: bool | None  # None: eligibility by country is unclear
    regions: list[str] = []
    min_age: int | None = None
    requires_underrepresented: bool = False
    requires_prior_contribution: bool = False
    who_can_apply: str
    typical_timing: str
    tracks: list[Track] = []
    tags: list[str] = []
    fit: Level
    fit_note: str
    do_now: str
    watch_urls: list[HttpUrl] = []
    cycles: list[Cycle] = []


class Repo(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    gfi_labels: list[str] = []
    note: str | None = None


class OrgLinks(Strict):
    homepage: HttpUrl | None = None
    ideas: HttpUrl | None = None
    ideas_next: HttpUrl | None = None
    guide: HttpUrl | None = None
    chat: HttpUrl | None = None
    ai_policy: HttpUrl | None = None


class Org(Strict):
    slug: Slug
    name: str
    gsoc_name: str | None = None
    tracks: list[Track] = Field(min_length=1)
    track_label: str
    stack: list[str]
    languages: list[str]
    competition_estimate: Level
    estimate_note: str | None = None
    why: str
    crowded: bool = False
    crowded_reason: str | None = None
    advice: str | None = None
    umbrella: bool = False
    programs: list[Slug] = ["gsoc"]
    github_owners: list[str] = []
    repos: list[Repo] = []
    repos_note: str | None = None
    links: OrgLinks = OrgLinks()
    notes: str | None = None

    @model_validator(mode="after")
    def _crowded_has_reason(self) -> Org:
        if self.crowded and not self.crowded_reason:
            raise ValueError("crowded orgs need a crowded_reason")
        return self

    @property
    def api_name(self) -> str:
        return self.gsoc_name or self.name


class WatchItem(Strict):
    org: Slug
    status: Literal["not_started", "exploring", "contributing", "primary", "backup", "dropped"]
    priority: int = Field(ge=1, le=3)
    role: str | None = None
    next_action: str


class Profile(Strict):
    github_username: str | None = None
    languages: list[str]
    interests: list[Track]
    timezone: str
    target: str


class ChecklistItem(Strict):
    id: Slug
    text: str
    due: dt.date | None = None
    done: bool = False


class PlaybookPhase(Strict):
    slug: Slug
    title: str
    window: str
    start: dt.date
    end: dt.date
    goal: str
    actions: list[str]
    done_when: str

    @model_validator(mode="after")
    def _ordered(self) -> PlaybookPhase:
        if self.start > self.end:
            raise ValueError(f"phase {self.slug} starts after it ends")
        return self


class Playbook(Strict):
    phases: list[PlaybookPhase]
    checklist: list[ChecklistItem]


class LogEntry(Strict):
    date: dt.date
    kind: Literal["chat-help", "docs", "talk", "review", "triage", "issue", "pr", "other"]
    org: Slug | None = None
    note: str
    url: HttpUrl | None = None


class Application(Strict):
    program: Slug
    cycle: str
    org: Slug | None = None
    status: Literal["interested", "drafting", "applied", "accepted", "rejected", "withdrawn"]
    proposal_url: HttpUrl | None = None
    notes: str | None = None


class GlossaryTerm(Strict):
    term: str
    slug: Slug
    definition: str
    see_also: list[Slug] = []


class FlowStep(Strict):
    id: Slug
    title: str
    summary: str
    guide: Slug | None = None
    link: str | None = Field(default=None, pattern=r"^/[a-z0-9/#?=&-]*$")  # internal page
    duration: str | None = None


class FlowPhase(Strict):
    id: Slug
    title: str
    when: str
    steps: list[FlowStep] = Field(min_length=1)
    branch: str | None = None


class Content(Strict):
    programs: list[Program]
    orgs: list[Org]
    watchlist: list[WatchItem]
    profile: Profile
    playbook: Playbook
    log: list[LogEntry]
    applications: list[Application]
    glossary: list[GlossaryTerm]
    flow: list[FlowPhase]
    guide_slugs: list[str]

    def program(self, slug: str) -> Program:
        return next(p for p in self.programs if p.slug == slug)

    def org(self, slug: str) -> Org:
        return next(o for o in self.orgs if o.slug == slug)


class ContentError(Exception):
    """Raised with every problem found, so one run reports them all."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def _read_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_dir[T: BaseModel](folder: Path, model: type[T], problems: list[str]) -> list[T]:
    items: list[T] = []
    for path in sorted(folder.glob("*.yaml")):
        try:
            item = model.model_validate(_read_yaml(path))
        except (ValidationError, yaml.YAMLError) as exc:
            problems.append(f"{folder.name}/{path.name}: {exc}")
            continue
        slug = getattr(item, "slug", path.stem)
        if slug != path.stem:
            problems.append(f"{folder.name}/{path.name}: slug '{slug}' must match the file name")
        items.append(item)
    return items


def _load_file[T: BaseModel](path: Path, model: type[T], problems: list[str]) -> T | None:
    try:
        return model.model_validate(_read_yaml(path))
    except FileNotFoundError:
        problems.append(f"{path.name}: missing")
    except (ValidationError, yaml.YAMLError) as exc:
        problems.append(f"{path.name}: {exc}")
    return None


def _load_list[T: BaseModel](path: Path, model: type[T], problems: list[str]) -> list[T]:
    try:
        raw = _read_yaml(path) or []
    except FileNotFoundError:
        problems.append(f"{path.name}: missing")
        return []
    except yaml.YAMLError as exc:
        problems.append(f"{path.name}: {exc}")
        return []
    if not isinstance(raw, list):
        problems.append(f"{path.name}: expected a list at the top level")
        return []
    items: list[T] = []
    for i, entry in enumerate(raw):
        try:
            items.append(model.model_validate(entry))
        except ValidationError as exc:
            problems.append(f"{path.name}[{i}]: {exc}")
    return items


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for value in values:
        if value in seen and value not in dups:
            dups.append(value)
        seen.add(value)
    return dups


def load_content(root: Path = CONTENT_DIR) -> Content:
    """Load and validate everything under content/. Raises ContentError listing every problem."""
    problems: list[str] = []
    programs = _load_dir(root / "programs", Program, problems)
    orgs = _load_dir(root / "orgs", Org, problems)
    watchlist = _load_list(root / "watchlist.yaml", WatchItem, problems)
    profile = _load_file(root / "profile.yaml", Profile, problems)
    playbook = _load_file(root / "playbook.yaml", Playbook, problems)
    log = _load_list(root / "log.yaml", LogEntry, problems)
    applications = _load_list(root / "applications.yaml", Application, problems)
    glossary = _load_list(root / "glossary.yaml", GlossaryTerm, problems)
    flow = _load_list(root / "flow.yaml", FlowPhase, problems)
    guide_slugs = sorted(p.stem for p in (root / "guides").glob("*.md"))

    program_slugs = {p.slug for p in programs}
    org_slugs = {o.slug for o in orgs}
    glossary_slugs = {g.slug for g in glossary}

    for dup in _duplicates([o.api_name for o in orgs]):
        problems.append(f"orgs: two orgs map to the same GSoC name '{dup}'")
    for dup in _duplicates([r.name.lower() for o in orgs for r in o.repos]):
        problems.append(f"orgs: repo '{dup}' is listed under more than one org")
    for org in orgs:
        for slug in org.programs:
            if slug not in program_slugs:
                problems.append(f"orgs/{org.slug}.yaml: unknown program '{slug}'")
    for dup in _duplicates([w.org for w in watchlist]):
        problems.append(f"watchlist.yaml: '{dup}' appears twice")
    for item in watchlist:
        if item.org not in org_slugs:
            problems.append(f"watchlist.yaml: unknown org '{item.org}'")
    for entry in log:
        if entry.org and entry.org not in org_slugs:
            problems.append(f"log.yaml: unknown org '{entry.org}'")
    for app in applications:
        if app.program not in program_slugs:
            problems.append(f"applications.yaml: unknown program '{app.program}'")
        if app.org and app.org not in org_slugs:
            problems.append(f"applications.yaml: unknown org '{app.org}'")
    for dup in _duplicates([g.slug for g in glossary]):
        problems.append(f"glossary.yaml: duplicate slug '{dup}'")
    for term in glossary:
        for ref in term.see_also:
            if ref not in glossary_slugs:
                problems.append(f"glossary.yaml: '{term.slug}' refers to unknown term '{ref}'")
    for dup in _duplicates([s.id for phase in flow for s in phase.steps]):
        problems.append(f"flow.yaml: duplicate step id '{dup}'")
    for phase in flow:
        for step in phase.steps:
            if step.guide and step.guide not in guide_slugs:
                problems.append(
                    f"flow.yaml: step '{step.id}' links to missing guide '{step.guide}'"
                )
    if playbook:
        for dup in _duplicates([c.id for c in playbook.checklist]):
            problems.append(f"playbook.yaml: duplicate checklist id '{dup}'")

    if problems or profile is None or playbook is None:
        raise ContentError(problems or ["content could not be loaded"])
    return Content(
        programs=programs,
        orgs=orgs,
        watchlist=watchlist,
        profile=profile,
        playbook=playbook,
        log=log,
        applications=applications,
        glossary=glossary,
        flow=flow,
        guide_slugs=guide_slugs,
    )
