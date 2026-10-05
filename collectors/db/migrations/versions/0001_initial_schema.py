"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-05 12:28:13.671798
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "events",
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=10), nullable=True),
        sa.Column("entity_slug", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "detail",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("notified_via", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("dedupe_key", name=op.f("pk_events")),
    )
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_events_occurred_at"), ["occurred_at"], unique=False)

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("api_calls", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
    )
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_runs_job"), ["job"], unique=False)

    op.create_table(
        "my_activity",
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("org", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("merged_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("url", name=op.f("pk_my_activity")),
    )
    op.create_table(
        "orgs",
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("gsoc_name", sa.String(length=200), nullable=True),
        sa.Column("curated", sa.Boolean(), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "technologies",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "topics",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("homepage", sa.String(length=500), nullable=True),
        sa.Column("ideas_url", sa.String(length=500), nullable=True),
        sa.Column("guide_url", sa.String(length=500), nullable=True),
        sa.Column("chat_url", sa.String(length=500), nullable=True),
        sa.Column(
            "languages",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "tracks",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "github_owners",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("slug", name=op.f("pk_orgs")),
        sa.UniqueConstraint("gsoc_name", name=op.f("uq_orgs_gsoc_name")),
    )
    op.create_table(
        "page_snapshots",
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "headings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "dates",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("text_chars", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("url", "fetched_at", name=op.f("pk_page_snapshots")),
    )
    op.create_table(
        "programs",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("organizer", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=True),
        sa.Column(
            "watch_urls",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("slug", name=op.f("pk_programs")),
    )
    op.create_table(
        "watched_pages",
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=10), nullable=False),
        sa.Column("entity_slug", sa.String(length=120), nullable=False),
        sa.Column("etag", sa.String(length=300), nullable=True),
        sa.Column("last_modified", sa.String(length=100), nullable=True),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_hash", sa.String(length=64), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False),
        sa.Column("needs_confirmation", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint("url", name=op.f("pk_watched_pages")),
    )
    op.create_table(
        "ideas",
        sa.Column("org", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org"],
            ["orgs.slug"],
            name=op.f("fk_ideas_org_orgs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org", "url", "title", name=op.f("pk_ideas")),
    )
    op.create_table(
        "org_programs",
        sa.Column("org", sa.String(length=120), nullable=False),
        sa.Column("program", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["org"],
            ["orgs.slug"],
            name=op.f("fk_org_programs_org_orgs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["program"],
            ["programs.slug"],
            name=op.f("fk_org_programs_program_programs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org", "program", name=op.f("pk_org_programs")),
    )
    op.create_table(
        "program_cycles",
        sa.Column("program", sa.String(length=80), nullable=False),
        sa.Column("cycle", sa.String(length=120), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("precision", sa.String(length=10), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["program"],
            ["programs.slug"],
            name=op.f("fk_program_cycles_program_programs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "program", "cycle", "event", "label", name=op.f("pk_program_cycles")
        ),
    )
    op.create_table(
        "program_years",
        sa.Column("org", sa.String(length=120), nullable=False),
        sa.Column("program", sa.String(length=80), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("num_projects", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org"],
            ["orgs.slug"],
            name=op.f("fk_program_years_org_orgs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["program"],
            ["programs.slug"],
            name=op.f("fk_program_years_program_programs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org", "program", "year", name=op.f("pk_program_years")),
    )
    op.create_table(
        "projects_history",
        sa.Column("org", sa.String(length=120), nullable=False),
        sa.Column("program", sa.String(length=80), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("project_url", sa.String(length=500), nullable=True),
        sa.Column("code_url", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(
            ["org"],
            ["orgs.slug"],
            name=op.f("fk_projects_history_org_orgs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["program"],
            ["programs.slug"],
            name=op.f("fk_projects_history_program_programs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org", "program", "year", "key", name=op.f("pk_projects_history")),
    )
    op.create_table(
        "repos",
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("org", sa.String(length=120), nullable=False),
        sa.Column(
            "gfi_labels",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("tracked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org"],
            ["orgs.slug"],
            name=op.f("fk_repos_org_orgs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("full_name", name=op.f("pk_repos")),
    )
    op.create_table(
        "scores_weekly",
        sa.Column("org", sa.String(length=120), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("competition_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("fit_score", sa.Float(), nullable=False),
        sa.Column(
            "components",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org"],
            ["orgs.slug"],
            name=op.f("fk_scores_weekly_org_orgs"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org", "week", name=op.f("pk_scores_weekly")),
    )
    op.create_table(
        "newcomers",
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("login_hash", sa.String(length=40), nullable=False),
        sa.Column("first_pr_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo"],
            ["repos.full_name"],
            name=op.f("fk_newcomers_repo_repos"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repo", "login_hash", name=op.f("pk_newcomers")),
    )
    op.create_table(
        "open_issues",
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("comments", sa.Integer(), nullable=False),
        sa.Column("assigned", sa.Boolean(), nullable=False),
        sa.Column("linked_pr", sa.Boolean(), nullable=False),
        sa.Column(
            "labels",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo"],
            ["repos.full_name"],
            name=op.f("fk_open_issues_repo_repos"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repo", "number", name=op.f("pk_open_issues")),
    )
    op.create_table(
        "repo_snapshots",
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("issues_enabled", sa.Boolean(), nullable=False),
        sa.Column("open_gfi_count", sa.Integer(), nullable=True),
        sa.Column("open_gfi_unclaimed", sa.Integer(), nullable=True),
        sa.Column("gfi_median_claim_hours", sa.Float(), nullable=True),
        sa.Column("new_contributors_30d", sa.Integer(), nullable=True),
        sa.Column("open_newcomer_prs", sa.Integer(), nullable=True),
        sa.Column("median_first_response_hours", sa.Float(), nullable=True),
        sa.Column("unanswered_pr_share", sa.Float(), nullable=True),
        sa.Column("prs_sampled", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["repo"],
            ["repos.full_name"],
            name=op.f("fk_repo_snapshots_repo_repos"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repo", "date", name=op.f("pk_repo_snapshots")),
    )


def downgrade() -> None:

    op.drop_table("repo_snapshots")
    op.drop_table("open_issues")
    op.drop_table("newcomers")
    op.drop_table("scores_weekly")
    op.drop_table("repos")
    op.drop_table("projects_history")
    op.drop_table("program_years")
    op.drop_table("program_cycles")
    op.drop_table("org_programs")
    op.drop_table("ideas")
    op.drop_table("watched_pages")
    op.drop_table("programs")
    op.drop_table("page_snapshots")
    op.drop_table("orgs")
    op.drop_table("my_activity")
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_runs_job"))

    op.drop_table("job_runs")
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_events_occurred_at"))

    op.drop_table("events")
