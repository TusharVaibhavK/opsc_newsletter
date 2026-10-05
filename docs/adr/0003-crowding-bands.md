# 0003: Show crowding as bands, never as a ranked number

**Status:** accepted, October 2026

## Context
The build plan defines a 0–100 competition percentile per org. That's useful privately. Published, it becomes a "least competitive orgs" leaderboard: applicants pile into the top of it within a cycle (destroying the signal), and maintainers of small communities absorb the flood.

## Decision
- Compute the score as planned, minus the chat-activity term (which needs admin-installed bots), with the remaining crowding weights rescaled to sum to 1.
- Publish only Low / Medium / High terciles, relative to the tracked orgs, labelled as estimates. Orgs missing more than half the inputs fall back to the hand estimate, marked "est.".
- Never export the number; never sort any list by crowding.
- Lead org pages with contributor-helpful facts (first-reply time, beginner issues, GSoC streak).

## Consequences
- Less precision on the site than in the database, by design.
- Facts (counts, medians) are still public and timestamped; only the composite judgement is coarsened.
- `scripts/check_privacy.py` fails the build if the numeric score ever reaches the site data.
