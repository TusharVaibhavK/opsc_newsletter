# 0004: One GraphQL query per repo; same-day runs skip

**Status:** accepted, October 2026

## Context
Claim time for beginner issues needs each issue's timeline (assignments, linked PRs, first outside comment). Over REST that is one request per issue, hundreds a day. The plan also called for ETags to make re-runs cheap, but GraphQL requests are POSTs, which HTTP caches don't apply to.

## Decision
- One GraphQL query per repo fetches open and recent beginner issues with their timelines, the last 100 PRs, and open PRs with reviews: about one rate-limit point each.
- Idempotency comes from the data instead of HTTP: a repo with a snapshot dated today is skipped unless `--force`.
- Conditional GETs (ETag / If-Modified-Since) are still used for the GSoC dataset and watched pages.
- A rate-limit error stops the loop, keeps what was collected, and marks the run as an error.

## Consequences
- ~30 queries a day, well within the Actions token's limits; no personal token required.
- New-contributor counts accumulate from daily sightings, so they undercount during the first 30 days. The site says so.
