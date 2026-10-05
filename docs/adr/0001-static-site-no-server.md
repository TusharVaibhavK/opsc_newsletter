# 0001: A static site, no application server

**Status:** accepted, October 2026

## Context
The build plan proposed FastAPI with Jinja and HTMX. The decisions made since: no user accounts at launch, data refreshed once a day, and a hard budget of about 8 hours a week for the whole project.

## Decision
Generate the whole site at build time with Astro. Collectors export JSON into the repository; the site reads only that JSON and the YAML in `content/`. Interactivity (filters, the program finder, checklists) is small client-side scripts on top of complete HTML.

## Consequences
- Free hosting anywhere static files are served; nothing to keep alive or patch.
- A broken collector produces stale data, never a broken site.
- No per-visitor API calls, so no visitor can exhaust a rate limit or see a token.
- Personal data in the UI is limited to what's committed. Accounts would need a backend; deferred until someone asks.
- A read-only JSON API remains possible later by serving `site/src/data/` as-is.
