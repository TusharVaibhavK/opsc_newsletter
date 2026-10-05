---
title: Your first contribution, step by step
summary: From cloning the project to a merged pull request, with the commands and the habits that make maintainers want to review your work.
order: 6
section: contribute
reading_minutes: 10
---

This is the whole loop for one contribution. The first time takes a few evenings; by the fifth it takes an hour.

## 1. Build and run the project

Before you change anything, get the project working as-is:

1. Read `CONTRIBUTING.md` (or the contributor guide linked from the org page) end to end.
2. Fork, clone, and add the upstream remote (see [setting up Git](../setup-git-github/)).
3. Follow the development setup exactly: the right language version, the container or virtual environment they use, the database they expect.
4. **Run the test suite** and make sure it passes on a clean checkout. If it doesn't, that's worth asking about in chat; you might have found your first contribution.

Then read **20 recently merged pull requests**. You'll learn the code style, how big PRs usually are, what reviewers push back on, and who reviews what.

## 2. Make the change on a branch

```bash
git fetch upstream
git switch -c fix-date-parsing upstream/main
```

- Keep the change **small and focused**: one issue, one PR. Resist fixing unrelated things you notice; open separate issues or PRs for those.
- **Write or update a test** that fails before your change and passes after it. Reviewers trust a fix with a test far more than one without.
- Run the formatter, linter and tests locally, the same way CI will. Many projects provide `make lint`, `pre-commit run --all-files`, or similar.

## 3. Commit with a message that explains why

```bash
git add -p            # review each hunk before staging it
git commit -s -m "Handle naive datetimes in parse_dates

Dates without a timezone were assumed to be local time, which broke
parsing for users east of UTC. Treat them as UTC, matching the API docs.

Fixes #1234"
```

- First line: what changed, under ~72 characters, in the style the project uses (some prefix like `fix:` or `[component]`).
- Body: why.
- `-s` adds a DCO sign-off; include it if the project requires it.

## 4. Open the pull request

```bash
git push -u origin fix-date-parsing
```

Then open the PR on GitHub. A good description has:

```markdown
## What
Treat naive datetimes in `parse_dates()` as UTC.

## Why
Fixes #1234. Users east of UTC got dates shifted by their offset.

## How I tested
- Added `test_parse_dates_naive_is_utc` (fails on main, passes here)
- `make test-unit` passes locally

## Notes
Not sure whether `parse_dates_legacy()` should change too; happy to do it here or separately.
```

- Fill in the project's PR template if it has one.
- Link the issue with `Fixes #1234` so it closes on merge.
- Open as a **draft** if you want early feedback on the approach.

## 5. Get CI green

If checks fail, read the logs, fix, and push again. A red CI usually means no one will review yet. If a failure looks unrelated to your change (a flaky test), say so in a comment with a link to the failing job.

## 6. Handle review

Review is where maintainers get to know you. Do it well:

- **Reply to every comment**, even if just “Done in abc123”.
- Push fixes as new commits during review so reviewers can see what changed. Squash at the end only if the project asks.
- If you disagree, explain your reasoning once, briefly, then go with the maintainer's call.
- After addressing everything, leave one comment: “Thanks! I've addressed all comments, PTAL.”
- If nobody has replied in a week, a single polite ping is fine. Many maintainers are volunteers.

## 7. After it merges

- Delete the branch and sync your fork's main.
- Thank the reviewer. Note what you learned.
- Pick the next issue, ideally a little bigger, in the same area. Momentum in one part of the codebase is how you become the person mentors think of.

Next: [working with mentors and maintainers](../working-with-mentors/).
