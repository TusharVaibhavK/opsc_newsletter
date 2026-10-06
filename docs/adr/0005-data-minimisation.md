# 0005: Data minimisation in a public repository

**Status:** accepted, October 2026

## Context
The history lives in a public repository (ADR 0002). The plan's data model stored GSoC contributors' names and, implicitly, the GitHub logins of new contributors to tracked repos. Both are public elsewhere, but republishing them in bulk isn't needed for anything this project does.

## Decision
- Don't store GSoC contributor names at all; keep project titles and links.
- Store a one-way hash of each new contributor's login, enough to avoid double counting.
- Keep job tracebacks (which contain file paths from the machine that ran them) in the database only; the history keeps the one-line summary.
- Never collect chat message content; don't fetch pages robots.txt disallows or that need a login.
- Candid personal notes live in a gitignored file and render only on the local dev server.

## Consequences
- `scripts/check_privacy.py` enforces these in CI on every build.
- A hashed login can still be matched by someone who guesses the login; it prevents casual listing, not determined lookup. Acceptable for public GitHub activity.
