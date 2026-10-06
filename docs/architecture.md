# Architecture

OSS Map is a static site plus a scheduled data pipeline. Everything is either a file in git or a build artifact; nothing runs between builds.

```
                 ┌──────────────────────── GitHub Actions: collect.yml (daily) ────────────────────────┐
 content/*.yaml ─┤ sync ─► SQLite (rebuilt from data/db/*.jsonl)  or  Postgres (DATABASE_URL)          │
                 │          ▲            │                                                            │
 GSoC API ───────┤ import_gsoc           │                                                            │
 GitHub GraphQL ─┤ collect_github        ├─► score_and_notify ─► Telegram                             │
 ideas pages ────┤ watch_pages           │                                                            │
 program pages ──┤ scrape_programs       ▼                                                            │
                 │                    export ─► site/src/data/*.json + data/db/*.jsonl ─► git commit  │
                 └──────────────────────────────────────────────┬─────────────────────────────────────┘
                                                                ▼
                                    deploy.yml: Astro build ─► link + privacy checks ─► GitHub Pages
```

## Components

| Path | Role |
| --- | --- |
| `content/` | Hand-curated YAML and Markdown. The source of truth for programs, orgs, the watchlist and the guides. Never written by code. |
| `collectors/content.py` | Pydantic schemas and cross-file validation (`ossmap validate`). Mirrored by Zod schemas in `site/src/content.config.ts`. |
| `collectors/sync.py` | Reconciles `content/` into the database on every run. YAML wins. |
| `collectors/jobs/` | The five jobs. Each runs in its own transaction and records a `job_runs` row; a failure rolls back that job only. |
| `collectors/http.py` | One HTTP client: retries with capped backoff, conditional GETs, robots.txt, request counting. |
| `collectors/db/` | SQLAlchemy models, Alembic migrations, the dialect-aware upsert, and the JSONL history store. |
| `collectors/export.py` | The public contract with the site: eleven JSON files in `site/src/data/`. |
| `site/` | Astro 7, static output. Pages read collections and the exported JSON at build time. |
| `scripts/` | CI gates: internal link check and privacy check. |

## Data model

Every table is keyed by natural keys (org slug, repo full name, program slug) so the history can be dumped and reloaded without integer IDs drifting. Raw facts are append-only snapshots by date; everything else is derived.

| Table | Holds | Written by |
| --- | --- | --- |
| `programs`, `program_cycles`, `org_programs`, `repos` | Mirror of `content/` | sync |
| `orgs` | Curated orgs plus every GSoC org from the last 3 years | sync, import_gsoc |
| `program_years`, `projects_history` | GSoC slots per year, project titles (no contributor names) | import_gsoc |
| `repo_snapshots` | One row per repo per day of contributor signals | collect_github |
| `newcomers` | Hashed logins of new contributors (no merged PR yet), with first-PR time | collect_github |
| `open_issues` | Current open beginner issues (replaced each run) | collect_github |
| `my_activity` | Your PRs and reviews | collect_github |
| `watched_pages`, `page_snapshots`, `ideas` | Page state, change history (headings and dates only), idea titles | watch_pages, scrape_programs |
| `events` | The change feed; deduplicated by key | all jobs |
| `scores_weekly` | Bands and fit per org per week; recomputed every run, never in the history | score_and_notify |
| `job_runs` | Status, summary and request count of every job run | job runner |

## Schedule

One cron (`30 0 * * *`, 06:00 IST). `ossmap daily` decides what is due:

| Job | When |
| --- | --- |
| `collect_github`, `watch_pages`, `score_and_notify` | Every day |
| `import_gsoc` | Mondays; every day from Jan 15 to May 15; and on the first run |
| `scrape_programs` | Mondays, and on the first run |

A single run avoids concurrent commits and keeps the data commit atomic. Same-day re-runs are cheap: `collect_github` skips repos that already have today's snapshot, and HTTP fetches use `ETag`/`If-Modified-Since`.

## Failure handling

- A failing job is rolled back and recorded; the jobs after it still run, and the data that did come in is committed.
- `Partial` results (for example, rate-limited after 20 of 26 repos) are kept and marked as errors.
- Two failures in a row for the same job raise a `job_failing` alert.
- The site never reads the database, only committed JSON, so a broken collector means stale data, never a broken site. Stale values are labelled with their age.

## Where this differs from the original build plan

| Plan | Built | Why |
| --- | --- | --- |
| FastAPI + Jinja + HTMX | Astro static site, no server | No accounts and a daily cadence: a server adds hosting and uptime work for nothing. See ADR 0001. |
| Postgres required | Postgres optional; committed JSONL history by default | Zero external accounts to deploy, and every day's change is a reviewable diff. See ADR 0002. |
| Cloudflare Pages | GitHub Pages (Cloudflare still works) | Deploys in the same workflow as collection, with no extra account or secrets. |
| Five separate crons | One cron, schedule decided in code | One atomic commit per day, no races between jobs. |
| ETags for GitHub | GraphQL plus same-day skip | GraphQL is POST, so HTTP caching doesn't apply. See ADR 0004. |
| Chat activity (`P`) in the score | Dropped | Needs admin-installed bots; risky for community trust. Weights rescaled. See ADR 0003. |
| Chart.js | Server-rendered SVG with table views | Works without JavaScript, nothing to download. |
| `contributor_name`, raw logins | Not stored / hashed | The history is public. See ADR 0005. |
