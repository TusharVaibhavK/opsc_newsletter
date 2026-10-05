---
title: Finding a first issue
summary: How to pick an issue nobody else is working on, claim it politely, and turn it into a pull request before the claim goes stale.
order: 5
section: contribute
reading_minutes: 6
---

Your first issue should be small enough to finish in a week and real enough to teach you the codebase. Here's how to find one without stepping on anyone's toes.

## Where to look

- **Beginner labels.** “good first issue” is the most common, but labels vary: `good-first-issue`, `Good First Contribution`, `beginner`, or `help wanted` (Zulip uses this one). The [first issues board](../../issues/) knows each tracked repo's labels.
- **The project's own guidance.** Many contributor guides say exactly where newcomers should start.
- **Outside GitHub.** OpenMRS and MetaBrainz track issues in Jira, Django in Trac, PostgreSQL on its mailing list. Their contributor guides point to beginner tickets there.

## Skip issues that are already taken

Before you get attached, check the whole thread:

- Is someone **assigned**?
- Is there a **linked pull request**, open or recent? (Look in the right sidebar and the timeline.)
- Did someone **claim it in the last two weeks**? A claim from two months ago with no PR is usually fair game; ask politely.
- Is the issue still **valid**? Reproduce it on the latest main branch.

## Good first contributions that aren't labelled

When labelled issues are claimed within minutes (common in crowded orgs), these are often better first contributions anyway:

- **A failing or flaky test** you can reproduce and fix.
- **Missing tests** for code that has none.
- **Docs that come with code**: a broken example in the docs, fixed and tested.
- **Reproducing bug reports**: comment with exact steps, versions and logs. Maintainers love this, and it's real triage work.
- **Error messages** that confuse users.

## Claim it with a plan, not just “can I work on this?”

One short comment that shows you've read the issue does more than a bare request. Many projects ask you to wait for a maintainer's go-ahead before starting; follow the contributor guide.

```text
Hi! I'd like to work on this. I can reproduce it on main (commit abc1234):
running `make test-unit` fails in test_parse_dates with the timezone error above.

My plan: handle naive datetimes in parse_dates() and add a test for the
UTC+05:30 case from the report. Does that sound right?
```

More ready-to-use messages are in [working with mentors](../working-with-mentors/#templates).

## Then move quickly

- Open a **draft pull request within a few days**, even if it's not finished. It shows progress and stops your claim from going stale.
- If you get stuck, ask in the issue or the project chat, describing what you tried.
- If you can't continue, say so in the issue so someone else can pick it up. That's respected; vanishing isn't.

## One at a time

Claim one issue, finish it, then claim the next. People who claim five issues at once and finish none get noticed, for the wrong reason.

Next: [open your first pull request](../first-contribution/).
