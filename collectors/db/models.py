"""Database schema. Raw facts are append-only snapshots keyed by date; everything else is derived.

Portable across SQLite (local dev, CI, history-store mode) and Postgres (Neon): arrays are JSON
columns, and every table is keyed by natural keys (org slug, repo full name, program slug) so the
JSONL history in data/db/ can rebuild a database without integer IDs drifting.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def fk(target: str) -> ForeignKey:
    """Foreign key on a natural key: renames and deletes cascade to the history tables."""
    return ForeignKey(target, ondelete="CASCADE", onupdate="CASCADE")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JsonType, list[Any]: JsonType}


class Program(Base):
    __tablename__ = "programs"
    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    organizer: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20))
    paid: Mapped[bool | None] = mapped_column(Boolean)
    watch_urls: Mapped[list[Any]] = mapped_column(default=list)


class ProgramCycle(Base):
    __tablename__ = "program_cycles"
    program: Mapped[str] = mapped_column(fk("programs.slug"), primary_key=True)
    cycle: Mapped[str] = mapped_column(String(120), primary_key=True)
    event: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), primary_key=True, default="")
    date: Mapped[dt.date] = mapped_column(Date)
    precision: Mapped[str] = mapped_column(String(10), default="day")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_url: Mapped[str | None] = mapped_column(String(500))


class Org(Base):
    __tablename__ = "orgs"
    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    gsoc_name: Mapped[str | None] = mapped_column(String(200), unique=True)
    curated: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    technologies: Mapped[list[Any]] = mapped_column(default=list)
    topics: Mapped[list[Any]] = mapped_column(default=list)
    homepage: Mapped[str | None] = mapped_column(String(500))
    ideas_url: Mapped[str | None] = mapped_column(String(500))
    guide_url: Mapped[str | None] = mapped_column(String(500))
    chat_url: Mapped[str | None] = mapped_column(String(500))
    languages: Mapped[list[Any]] = mapped_column(default=list)
    tracks: Mapped[list[Any]] = mapped_column(default=list)
    github_owners: Mapped[list[Any]] = mapped_column(default=list)


class OrgProgram(Base):
    __tablename__ = "org_programs"
    org: Mapped[str] = mapped_column(fk("orgs.slug"), primary_key=True)
    program: Mapped[str] = mapped_column(fk("programs.slug"), primary_key=True)


class Repo(Base):
    __tablename__ = "repos"
    full_name: Mapped[str] = mapped_column(String(200), primary_key=True)
    org: Mapped[str] = mapped_column(fk("orgs.slug"))
    gfi_labels: Mapped[list[Any]] = mapped_column(default=list)
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)


class ProgramYear(Base):
    __tablename__ = "program_years"
    org: Mapped[str] = mapped_column(fk("orgs.slug"), primary_key=True)
    program: Mapped[str] = mapped_column(fk("programs.slug"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    num_projects: Mapped[int] = mapped_column(Integer, default=0)


class ProjectHistory(Base):
    __tablename__ = "projects_history"
    org: Mapped[str] = mapped_column(fk("orgs.slug"), primary_key=True)
    program: Mapped[str] = mapped_column(fk("programs.slug"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # hash of URL or title
    title: Mapped[str] = mapped_column(String(500))
    # Contributor names are deliberately not stored: nothing needs them, and the history in
    # data/db/ is public.
    project_url: Mapped[str | None] = mapped_column(String(500))
    code_url: Mapped[str | None] = mapped_column(String(1000))


class RepoSnapshot(Base):
    __tablename__ = "repo_snapshots"
    repo: Mapped[str] = mapped_column(fk("repos.full_name"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    stars: Mapped[int | None] = mapped_column(Integer)
    issues_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    open_gfi_count: Mapped[int | None] = mapped_column(Integer)
    open_gfi_unclaimed: Mapped[int | None] = mapped_column(Integer)
    gfi_median_claim_hours: Mapped[float | None] = mapped_column(Float)
    new_contributors_30d: Mapped[int | None] = mapped_column(Integer)
    open_newcomer_prs: Mapped[int | None] = mapped_column(Integer)
    median_first_response_hours: Mapped[float | None] = mapped_column(Float)
    unanswered_pr_share: Mapped[float | None] = mapped_column(Float)
    prs_sampled: Mapped[int | None] = mapped_column(Integer)


class Newcomer(Base):
    """First time we saw each first-time contributor open a PR. Feeds new_contributors_30d.

    Only a one-way hash of the login is kept: enough to avoid counting someone twice, without
    publishing a list of other people's usernames in the committed history.
    """

    __tablename__ = "newcomers"
    repo: Mapped[str] = mapped_column(fk("repos.full_name"), primary_key=True)
    login_hash: Mapped[str] = mapped_column(String(40), primary_key=True)
    first_pr_at: Mapped[dt.datetime] = mapped_column(DateTime)


class OpenIssue(Base):
    """Current open beginner issues per repo. Replaced on every collection run."""

    __tablename__ = "open_issues"
    repo: Mapped[str] = mapped_column(fk("repos.full_name"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    linked_pr: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[list[Any]] = mapped_column(default=list)
    seen_at: Mapped[dt.datetime] = mapped_column(DateTime)


class WatchedPage(Base):
    """One row per watched URL: last known state plus conditional-request validators."""

    __tablename__ = "watched_pages"
    url: Mapped[str] = mapped_column(String(1000), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # ideas | ideas_next | program | source
    entity_type: Mapped[str] = mapped_column(String(10))  # org | program | source
    entity_slug: Mapped[str] = mapped_column(String(120))
    etag: Mapped[str | None] = mapped_column(String(300))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    last_status: Mapped[int | None] = mapped_column(Integer)
    last_hash: Mapped[str | None] = mapped_column(String(64))
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    last_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(300))


class PageSnapshot(Base):
    """A watched page's extracted headings, stored only when the page changes."""

    __tablename__ = "page_snapshots"
    url: Mapped[str] = mapped_column(String(1000), primary_key=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    headings: Mapped[list[Any]] = mapped_column(default=list)
    dates: Mapped[list[Any]] = mapped_column(default=list)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)


class Idea(Base):
    __tablename__ = "ideas"
    org: Mapped[str] = mapped_column(fk("orgs.slug"), primary_key=True)
    url: Mapped[str] = mapped_column(String(1000), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), primary_key=True)
    first_seen: Mapped[dt.date] = mapped_column(Date)
    last_seen: Mapped[dt.date] = mapped_column(Date)


class MyActivity(Base):
    __tablename__ = "my_activity"
    url: Mapped[str] = mapped_column(String(500), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # pr | review
    repo: Mapped[str] = mapped_column(String(200))
    org: Mapped[str | None] = mapped_column(String(120))  # matched via github_owners; no FK
    title: Mapped[str] = mapped_column(String(500))
    state: Mapped[str] = mapped_column(String(20))  # open | merged | closed
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime)
    merged_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class Event(Base):
    """Something worth telling you about. Feeds the change feed, RSS and alerts."""

    __tablename__ = "events"
    dedupe_key: Mapped[str] = mapped_column(String(300), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str | None] = mapped_column(String(10))
    entity_slug: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    url: Mapped[str | None] = mapped_column(String(1000))
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    notified_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    notified_via: Mapped[str | None] = mapped_column(String(20))


class ScoreWeekly(Base):
    """Derived from snapshots and recomputed every run, so it is never part of the history."""

    __tablename__ = "scores_weekly"
    org: Mapped[str] = mapped_column(fk("orgs.slug"), primary_key=True)
    week: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    competition_score: Mapped[float | None] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    fit_score: Mapped[float] = mapped_column(Float)
    components: Mapped[dict[str, Any]] = mapped_column(default=dict)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10))  # running | ok | error | skipped
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)


# Derived tables the JSONL history skips; they are recomputed on every run.
NOT_IN_HISTORY = frozenset({"scores_weekly"})
# Keep the history file for job runs from growing forever.
JOB_RUNS_KEPT = 400
