# OSS Map

A website for getting into open source through mentorship programs: every program in one place (GSoC, Outreachy, LFX and 19 more), the orgs inside them with live contributor signals, and a step-by-step beginner path from setting up Git to writing a proposal.

It is a static site rebuilt every day by a small Python data pipeline. There is no server and no required database or paid service: GitHub Actions runs the collectors, commits the results, and publishes the site to GitHub Pages.

## What's on the site

| Page | What it does |
| --- | --- |
| `/` | This month's move (from the playbook), next deadlines, recent changes |
| `/start/` | A numbered, checkable path for beginners; progress saved in the browser |
| `/flow/` | The whole journey on one page, with a guide for every step |
| `/guides/` | Twelve short guides: Git setup, honest expectations, choosing a program and an org, first issue, first PR, working with mentors (with message templates), going deeper, AI tools, proposal kit, during the program, if not selected |
| `/programs/` | 22 programs with filters (paid, beginner friendly, students, worldwide, track) |
| `/timeline/` | Every program's windows month by month, confirmed vs. estimated; iCal feed at `/deadlines.ics` |
| `/finder/` | Seven questions, then the programs you can apply to, ranked, with reasons |
| `/orgs/` | 29 curated orgs with crowding levels and live signals, plus every GSoC org from the last three years |
| `/orgs/<slug>/` | Contributor signals with 12-week trends, ideas page (what changed, whether next year's is up), GSoC history |
| `/issues/` | Open beginner issues across tracked repos, capped and rotated daily |
| `/dashboard/` | The author's daily view: watchlist, fit vs. crowding, deadlines, checklist, own PRs |
| `/changes/`, `/rss.xml` | What the collectors noticed: orgs announced, ideas added, program pages changed |
| `/glossary/`, `/about/`, `/admin/` | Jargon buster, methodology, collector status |

## How it works

```
GitHub Actions, daily 00:30 UTC
  ossmap daily ─┬─ import_gsoc       GSoC history for ~250 orgs (weekly; daily Jan 15 – May 15)
                ├─ collect_github    one GraphQL query per tracked repo + your own PRs
                ├─ watch_pages       ideas pages, plus next year's page as soon as it appears
                ├─ scrape_programs   program pages (weekly); new dates flagged for a human
                └─ score_and_notify  crowding bands, fit, deadline alerts → Telegram (optional)
                        │
                        ├─► data/db/*.jsonl        full history, committed (the database)
                        └─► site/src/data/*.json   what the site reads, committed
content/*.yaml, content/guides/*.md ──► Astro ──► GitHub Pages
```

Without `DATABASE_URL`, each run rebuilds a SQLite database from `data/db/*.jsonl`, runs the jobs, and writes the history back. Git is the database, and every day's change is a readable diff. Set `DATABASE_URL` to use Postgres instead (Neon or Supabase free tier); the JSONL files then become a backup.

More detail: [docs/architecture.md](docs/architecture.md) and the decision records in [docs/adr/](docs/adr/).

## Run it locally

Needs Python 3.12+ and Node 22.12+.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip
.venv/bin/ossmap validate                  # check content/ against the schemas

# Optional: pull fresh data (no token needed for these)
.venv/bin/ossmap run import_gsoc watch_pages scrape_programs score_and_notify

cd site
npm install
npm run dev                                # http://localhost:4321
```

To collect GitHub signals locally, put a token in `.env` or the environment: `GITHUB_TOKEN=... ossmap run collect_github`. A fine-grained token with no extra permissions is enough; everything it reads is public.

## Deploy (one time)

1. Push this repository to GitHub.
2. **Settings → Pages → Source: GitHub Actions.**
3. **Actions → Collect → Run workflow** for the first run. It runs daily after that.

Optional settings (**Settings → Secrets and variables → Actions**):

| Name | Kind | Why |
| --- | --- | --- |
| `GH_PAT` | secret | A personal token, if the built-in Actions token ever isn't enough |
| `DATABASE_URL` | secret | Use Postgres instead of the committed history |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | secrets | Alerts on your phone (create a bot with @BotFather) |
| `SITE_URL` | variable | Your site's URL, so alerts can link to it |

Prefer Cloudflare Pages or Netlify? Point them at this repo with root `site`, build command `npm run build`, output `dist`.

## Edit the content

Everything hand-curated lives in `content/` and is validated in CI (`ossmap validate`):

| File | What it holds |
| --- | --- |
| `content/profile.yaml` | Your GitHub username (turns on PR tracking), languages, interests |
| `content/watchlist.yaml` | Orgs you're evaluating: status, priority, next action |
| `content/playbook.yaml` | The month-by-month plan and checklist (`done: true` to tick) |
| `content/applications.yaml`, `content/log.yaml` | Applications, and contributions GitHub can't see |
| `content/programs/*.yaml` | One file per program, with dated cycles (`confirmed: false` = estimate) |
| `content/orgs/*.yaml` | Curated orgs: editorial notes, crowding estimate, repos to track and their beginner labels |
| `content/guides/*.md`, `glossary.yaml`, `flow.yaml` | The beginner guide |
| `content/notes.private.yaml` | Gitignored. Candid notes, shown only by `npm run dev` |

Adding an org's repos to `content/orgs/<slug>.yaml` is all it takes for the collectors to start tracking it the next day.

## Commands

```
ossmap validate                 validate content/
ossmap run JOB [JOB ...]        run jobs now: import_gsoc collect_github watch_pages
                                scrape_programs score_and_notify (--dry-run, --force, --repo)
ossmap daily [--jobs a,b]       the scheduled pipeline: whatever is due today, then export
ossmap export                   rewrite site/src/data/*.json and data/db/*.jsonl
ossmap migrate                  apply migrations (Postgres mode)
```

## Quality

```bash
pytest                          # 52 tests, no network; set TEST_DATABASE_URL for Postgres
ruff check . && ruff format --check . && mypy collectors
cd site && npm run check && npm run build
python scripts/check_links.py site/dist /     # every internal link resolves
python scripts/check_privacy.py               # nothing private in the build or history
```

CI runs all of it on every push, with the test suite against both SQLite and Postgres.

## Principles

- **Estimates are labelled as estimates.** Unconfirmed dates show “est.”; crowding shows its source.
- **Bands, not rankings.** Crowding is Low / Medium / High relative to the tracked orgs. The numeric score never leaves the database, and nothing is sorted by it: a public “least competitive orgs” list would send everyone to the top of it.
- **Polite collection.** One request per page per day, robots.txt honoured, no logins bypassed, no chat scraping.
- **Data minimisation.** No GSoC contributor names; new contributors are counted by one-way hash.
- **Nothing private ships.** Tokens stay in Actions secrets; CI checks the build for them.

## Credits

GSoC history from [gsocorganizations.dev](https://www.gsocorganizations.dev/). The program list started from the [Open source programs directory](https://open-source-mv.vercel.app/). Research behind the content: the *Open Source Starting Map* and *OSS Program Tracker Build Plan* notes (October 2026).

MIT licensed; see [LICENSE](LICENSE).
