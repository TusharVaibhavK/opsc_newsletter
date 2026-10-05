---
title: Working with mentors and maintainers
summary: How to ask questions that get answered, follow up without pestering, and handle review, plus copy-paste templates for the messages you'll send most.
order: 7
section: contribute
reading_minutes: 8
---

Maintainers and mentors are busy, often volunteers, often in another time zone. The contributors they remember make it easy to help them.

## Ask in public, never by private message

Ask questions in the project's public channels: the issue, the pull request, the chat channel, the mailing list. Others can answer faster, the answer helps the next newcomer, and mentors can see you're engaged. Private messages to mentors asking for help or for proposal reviews are the most common way applicants annoy the people choosing them.

## Ask questions that are easy to answer

A good question shows what you tried:

- What you're trying to do, and why.
- What you did (commands, code), and what happened (the exact error, logs).
- What you expected instead.
- What you've already tried or read.

Then wait. A day or two for a reply is normal, longer across time zones and weekends.

## Summarise decisions back

When a discussion in chat or a call settles something, write a short summary in the issue or PR (“Decided with @maintainer: we'll keep the old flag but deprecate it”). It creates a record and shows you're careful.

## Follow up politely

If a pull request or question gets no reply, wait about a week, then ping once in the same thread. Don't tag five people, and don't cross-post the same question to every channel.

## Use AI tools within the project's rules

Many orgs now publish AI-use policies. Read your org's before using AI tools, and never submit code or text you can't explain line by line. See [using AI tools responsibly](../ai-tools/).

## Templates

Edit these to fit; copying them word for word reads like a template.

### Claiming an issue

```text
Hi! I'd like to work on this. I've reproduced it on main (<commit>): <one-line symptom>.
My plan is to <approach in one or two sentences>, and add a test for <case>.
Does that sound right, or is there a constraint I'm missing?
```

### Asking for help when stuck

```text
I'm working on #<issue>. I'm trying to <goal>.
I ran `<command>` and got:
<paste the exact error, trimmed>
I expected <expectation>. I've checked <what you read or tried>.
Could someone point me to where <thing> is handled?
```

### Following up on a pull request

```text
Hi @<reviewer>, gentle ping on this when you have time. CI is green and I've
rebased on main. Happy to split it up if it's easier to review in parts.
```

### Responding to review

```text
Thanks for the review! I've addressed everything:
- Renamed `parse` to `parse_dates` (abc123)
- Added the timezone test you suggested (def456)
- Kept the early return; I explained why inline. Happy to change it if you prefer.
PTAL.
```

### Introducing yourself in chat

```text
Hi everyone, I'm <name>, a <background> interested in <area of the project>.
I've set up the dev environment and run the tests. I'm planning to start with
#<issue>. Any pointers on <specific part> are welcome!
```

### Asking a mentor about a program idea

```text
Hi @<mentor>, I'm interested in the "<idea title>" idea. I've contributed
#<pr1> and #<pr2> in <area>. I've read <relevant code/docs> and I'm thinking
of approaching it by <rough approach>. Two questions: <question 1>? <question 2>?
```

### Asking for proposal feedback

```text
Hi @<mentor>, I've drafted my proposal for "<idea title>": <link, comments enabled>.
I'd especially value feedback on the timeline in weeks 4–8 and the approach
to <hard part>. The deadline is <date>, so any time in the next week works. Thanks!
```

Next: [go deeper in one org](../going-deeper/).
