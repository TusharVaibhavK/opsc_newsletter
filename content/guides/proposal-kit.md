---
title: Proposal kit
summary: The structure of a strong proposal, an outline to copy, how to build a believable week-by-week timeline, the mistakes mentors see most, and a pre-submit checklist.
order: 10
section: apply
reading_minutes: 12
---

A proposal is a plan a mentor can believe. The best ones read like the next step of work the applicant has already started, because it is.

## Before you write

- **Talk to the idea's mentor first**, in public, with specific questions (see the [templates](../working-with-mentors/#templates)).
- **Build a small proof of concept.** A draft PR that implements a thin slice of the idea answers the mentor's biggest question: can this person actually do it?
- **Check the project size.** GSoC projects have come in sizes of roughly 90, 175 and 350 hours in recent years; confirm the current options in the official FAQ and plan to the hours you pick.

## The structure

1. **Title and one-paragraph summary.** What you'll build and why it matters, in plain words.
2. **The problem.** What's missing or painful today, with links: issues, benchmarks, user reports.
3. **Proposed solution.** The technical plan. Name real modules, files and functions. Show the design, the alternatives you considered, and why you chose this one. Diagrams help.
4. **Deliverables.** What will exist at the end: code, tests, docs, benchmarks. Separate must-haves from stretch goals.
5. **Timeline.** Week by week (see below).
6. **Risks and mitigations.** What could go wrong and what you'll do about it.
7. **About you.** Your merged PRs and reviews in this org (with links), relevant experience, and why this project.
8. **Availability.** Hours per week, time zone, exams or other commitments. Be honest; mentors plan around it.
9. **After the program.** How you'll keep contributing. Mentors are recruiting future maintainers.

## An outline to copy

```markdown
# <Project title>

## Summary
<3–4 sentences: what, why it matters, what exists at the end>

## The problem
<what's broken or missing today, with links to issues and evidence>

## Proposed solution
### Design
<approach, the modules it touches, a diagram if useful>
### Alternatives considered
<other approaches and why not>
### Proof of concept
<link to draft PR or branch, what it shows>

## Deliverables
- Must have: <...>
- Stretch: <...>

## Timeline
| Week | Work | Milestone |
| --- | --- | --- |
| Bonding | Finalise design with mentors, land warm-up PRs | Design doc agreed |
| 1–2 | <...> | <...> |
| ... | ... | ... |
| Midterm | | <something merged and usable> |
| ... | ... | ... |
| Final | Docs, cleanup, final report | <all must-haves merged> |

## Risks
| Risk | Mitigation |
| --- | --- |
| <...> | <...> |

## About me
- Merged: <PR links with one-line descriptions>
- Reviews and other contributions: <links>
- Relevant experience: <...>

## Availability
<hours/week, time zone, any exams or holidays with dates>

## After the program
<how you'll stay involved>
```

## Building a believable timeline

- **Work backwards from the deliverables.** List the pieces, estimate each, then add 20–30% for review and surprises.
- **Make every 2–3 weeks end in something mergeable.** Small reviewed PRs, not one giant PR at the end.
- **Put the riskiest part early**, so there's time to change course.
- **Show the midterm milestone clearly**: something merged and usable by the midpoint evaluation.
- **Leave the last week for docs, tests and the final report.**
- **Name the weeks you'll be less available.** Mentors respect honesty; they don't forgive surprises.

## Mistakes mentors see most

- A generic plan that could apply to any project: no file names, no trade-offs.
- Copying the ideas page back with “I will implement this”.
- A timeline with one line per month, or all the hard work in the last three weeks.
- No links to your contributions, or contributions that are all typo fixes.
- Proposing everything on the ideas list. Scope down; stretch goals are fine.
- Submitting at the last minute with no mentor feedback.

## Pre-submit checklist

- [ ] Shared a draft with the mentor **10+ days before the deadline**, and incorporated feedback.
- [ ] Every claim about the codebase is checked against the actual code.
- [ ] Timeline is week by week, with a midterm milestone and mergeable chunks.
- [ ] Merged PRs and reviews are linked.
- [ ] Availability and commitments are stated honestly.
- [ ] Proof of concept linked, if you have one.
- [ ] Follows the org's proposal template and AI-use policy.
- [ ] Spell-checked, readable on a phone, links work, comments open on the doc.
- [ ] Submitted to **1–2 orgs (3 at most)**, well before the deadline.

## After you submit

Keep contributing. Activity during the review period is visible to mentors and often decides close calls. Answer any mentor questions about your proposal quickly.

Next: [during the program](../during-the-program/), or [if you're not selected](../if-not-selected/).
