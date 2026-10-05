---
title: Choosing an org
summary: How to shortlist orgs where your hours count, using signals you can check yourself, and how to read the crowding levels on this site.
order: 4
section: start
reading_minutes: 8
---

The org you pick matters more than any other decision. A good pick is one where your skills fit, maintainers respond, and the crowd is small enough that your work is noticed.

## Start from your track

Pick the kind of work you want to get good at, then find orgs that need it:

- **Backend (Go, Java, Python):** Kubernetes-ecosystem projects, transit data APIs, health platforms, databases, license and security scanners.
- **AI / ML:** applied ML libraries in science, ML infrastructure (pipelines, training, serving), research software.
- **Data:** knowledge graphs, metadata platforms, data pipelines and storage.
- **Tooling:** static analysis, parsers, developer tools.

The [orgs page](../../orgs/) filters by track and language.

## Signals you can check yourself

No public source says how many people apply to each org, but these signals track crowding well:

| Signal | Room for you looks like | Crowded looks like |
| --- | --- | --- |
| Slots vs. visible applicants | 4+ slots, under ~30 people asking in chat | 1–3 slots, hundreds of “I want to work on this” messages |
| Entry barrier | Needs domain knowledge: compilers, databases, networking, scientific computing, Go/Java/C++ | Pure web frontend, beginner Python, generic chatbot ideas |
| Brand | Unknown outside its niche | Household name, trendy AI brand |
| Beginner issue turnover | Issues stay open for days | Claimed within minutes, many duplicate PRs |
| Newcomer PR backlog | Maintainers review within a week | 50+ unreviewed newcomer PRs |
| GSoC streak | 3+ consecutive years | First year, or skipped last year |
| Mentors per idea | Several mentors per idea, 15+ ideas | One mentor covering many ideas |

## The sweet spot

Look for an org with **a consistent GSoC streak, a technical barrier you can climb, and a niche brand**. A steep learning curve is your friend: it filters out people who aren't willing to put in the weeks you will.

Competition is also per idea, not just per org. Inside a crowded org, ideas needing Go, Java, C++ or a specific domain usually draw far fewer proposals than “build an AI assistant”.

## Check that maintainers are responsive

Before investing weeks, spend an evening checking the org is healthy:

- Read 20 recently merged pull requests. How long did newcomers wait for a first reply? The “first maintainer reply” signal on each org page measures exactly this.
- Is there recent activity in the chat channel, and do questions get answered?
- Does the contributor guide work? Can you build the project and run the tests?

## How to read crowding on this site

Each curated org shows a crowding level of Low, Medium or High:

- **“est.”** means it's a hand estimate from research notes.
- Without “est.”, it's computed from public GitHub signals, **relative to the other tracked orgs**.

It's deliberately a coarse band, never a ranking. Crowded isn't bad: popular orgs also tend to have more slots, and a community you love is worth some competition. See [the methodology](../../about/#crowding).

## Shortlist, then narrow

1. Shortlist **five** orgs.
2. For each, build the project, run the tests, join the chat, and read recent merged PRs.
3. Narrow to **two or three** for your first contributions.
4. By mid-December, pick **one** primary org and go deep.

Next: [find a first issue](../finding-a-first-issue/).
