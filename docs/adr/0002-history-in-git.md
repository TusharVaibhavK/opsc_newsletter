# 0002: Keep the history in git; Postgres optional

**Status:** accepted, October 2026

## Context
Trends and re-scoring need append-only history. The plan proposed a free-tier Postgres (Neon), which adds an account, a secret, and a dependency that can sleep or expire.

## Decision
Dump every history table to sorted JSONL in `data/db/` after each run, and commit it. Without `DATABASE_URL`, each run rebuilds a scratch SQLite database from those files first. With `DATABASE_URL`, Postgres is the source of truth and the JSONL is a readable backup. The same Alembic migrations serve both.

## Consequences
- Deploying needs no account beyond GitHub.
- Each day's data change is a small, reviewable diff; history survives the loss of any hosted database.
- Rows are sorted by key and keys are sorted, so diffs stay small. Job runs are capped at 400; derived tables (`scores_weekly`) are recomputed instead of stored.
- At the planned scale (~30 repos, one snapshot a day) the files grow by a few kilobytes a day. If that changes, move to Postgres by setting one secret.
- The history is public, which drives ADR 0005.
