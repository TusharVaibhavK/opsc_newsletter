"""Privacy gate, run in CI after the site build. Exits non-zero if anything private could ship.

Checks that:
- content/notes.private.yaml is gitignored and not tracked, and none of its notes are in the build;
- the built site contains no token-shaped strings, nor the values of the configured secrets;
- the committed history holds no raw contributor logins or GSoC contributor names;
- the site data never includes the numeric competition score (bands only).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "site" / "dist"
PRIVATE_NOTES = ROOT / "content" / "notes.private.yaml"
TOKEN_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),  # classic GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),  # fine-grained GitHub tokens
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),  # Telegram bot tokens
]


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def built_text() -> str:
    parts = []
    for path in DIST.rglob("*"):
        if path.is_file() and path.suffix in {
            ".html",
            ".xml",
            ".ics",
            ".js",
            ".css",
            ".json",
            ".txt",
        }:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def main() -> int:
    problems: list[str] = []

    if git("rev-parse", "--is-inside-work-tree").returncode == 0:
        if git("check-ignore", "-q", "content/notes.private.yaml").returncode != 0:
            problems.append("content/notes.private.yaml is not gitignored")
        if git("ls-files", "--error-unmatch", "content/notes.private.yaml").returncode == 0:
            problems.append("content/notes.private.yaml is tracked by git")
        tracked = git("ls-files").stdout.splitlines()
        for name in tracked:
            if name == ".env" or name.endswith("/local.db") or name == "data/local.db":
                problems.append(f"{name} must not be committed")

    if DIST.exists():
        text = built_text()
        for pattern in TOKEN_PATTERNS:
            if pattern.search(text):
                problems.append(f"token-shaped string in site/dist matching {pattern.pattern}")
        for var in ("GITHUB_TOKEN", "GH_TOKEN", "TELEGRAM_BOT_TOKEN", "DATABASE_URL"):
            value = os.environ.get(var, "")
            if len(value) >= 8 and value in text:
                problems.append(f"the value of {var} appears in site/dist")
        if PRIVATE_NOTES.exists():
            import yaml

            notes = yaml.safe_load(PRIVATE_NOTES.read_text(encoding="utf-8")) or {}
            for slug, note in notes.items():
                snippet = str(note).strip()[:40]
                if len(snippet) >= 12 and snippet in text:
                    problems.append(f"the private note for '{slug}' appears in site/dist")
    else:
        print("site/dist not found: skipping build checks (run the site build first)")

    history = ROOT / "data" / "db"
    newcomers = history / "newcomers.jsonl"
    if newcomers.exists():
        for line in newcomers.read_text(encoding="utf-8").splitlines()[:50]:
            if '"login"' in line:
                problems.append("data/db/newcomers.jsonl contains raw logins")
                break
    projects = history / "projects_history.jsonl"
    if projects.exists() and "contributor" in projects.read_text(encoding="utf-8")[:20000]:
        problems.append("data/db/projects_history.jsonl contains contributor names")

    scores = ROOT / "site" / "src" / "data" / "scores.json"
    if scores.exists() and "competition_score" in json.dumps(
        json.loads(scores.read_text(encoding="utf-8"))
    ):
        problems.append("site/src/data/scores.json exposes the numeric competition score")

    for problem in problems:
        print(f"PRIVACY: {problem}", file=sys.stderr)
    if not problems:
        print("privacy checks passed")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
