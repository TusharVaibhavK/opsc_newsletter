---
title: Set up Git and GitHub
summary: Install Git, set up a GitHub profile mentors can read at a glance, and practise the fork, branch and pull request loop once before it matters.
order: 1
section: start
reading_minutes: 8
---

You'll use the same handful of Git commands for every contribution. Learn them once, on a throwaway repository, so your first real pull request isn't also your first time using Git.

## 1. Install and configure Git

Install Git from [git-scm.com](https://git-scm.com/) (on macOS, `xcode-select --install` also works). Then tell Git who you are. Use the same email as your GitHub account, so commits link to your profile:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
git config --global pull.rebase true
```

`pull.rebase true` keeps your branches tidy when you pull, which many projects prefer.

## 2. Make your GitHub profile work for you

Mentors click your username before they read your proposal. Make it easy for them:

- A real name or a consistent handle, and a photo or avatar.
- A short profile README (create a repo named exactly like your username) that says what you focus on, for example “Backend and ML: Go, Python, Java”.
- Pin two or three repositories that show real work.

Then set up authentication. Either [add an SSH key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh), or use HTTPS with the [GitHub CLI](https://cli.github.com/) (`gh auth login`) or Git Credential Manager. Turn on two-factor authentication; some orgs require it.

## 3. The fork workflow

Almost every open source project uses the same loop:

1. **Fork** the project on GitHub (your copy, called `origin`).
2. **Clone** your fork and add the original project as `upstream`.
3. **Branch** for each change.
4. **Commit** and **push** to your fork.
5. Open a **pull request** from your branch to the project.

```bash
git clone git@github.com:YOU/project.git
cd project
git remote add upstream https://github.com/ORG/project.git
git fetch upstream

git switch -c fix-typo-in-readme upstream/main
# ...edit files...
git add README.md
git commit -m "docs: fix broken link in installation section"
git push -u origin fix-typo-in-readme
```

GitHub prints a link to open the pull request after the push.

## 4. Keep your branch up to date

Projects move while you work. Before asking for review, and whenever there's a conflict, rebase on the latest upstream:

```bash
git fetch upstream
git rebase upstream/main
# fix any conflicts, then: git add <files> && git rebase --continue
git push --force-with-lease
```

`--force-with-lease` is the safe version of force-pushing: it refuses if someone else pushed to your branch.

## 5. Signing off and CLAs

Two things trip up first-time contributors:

- **DCO sign-off.** If the project uses the Developer Certificate of Origin (Kubernetes, many CNCF projects), every commit needs `git commit -s`. Forgot? `git rebase --signoff upstream/main` fixes the whole branch.
- **CLA.** Some projects ask you to sign a Contributor License Agreement once. A bot comments on your first PR with a link.

## 6. Practise once

Before touching a real project, run the whole loop on your own throwaway repo: fork it from a second account or a friend, branch, commit, open a PR, push a fix after “review”, and merge it. Twenty minutes now saves a stressful evening later.

## Done when

- `git config --global --list` shows your name and email.
- Your GitHub profile says what you work on.
- You've opened and merged one practice pull request.

Next: [learn how selection really works](../honest-expectations/).
