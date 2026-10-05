"""export_all: every file the site needs, and nothing that must stay private."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

from collectors.db.models import OpenIssue
from collectors.export import ISSUES_PER_ORG, export_all, export_issues
from collectors.jobs import JobContext
from collectors.jobs.gsoc import apply_gsoc_data
from collectors.jobs.score import score

from .test_gsoc import DATA

FILES = {
    "meta.json",
    "gsoc.json",
    "projects.json",
    "metrics.json",
    "scores.json",
    "issues.json",
    "activity.json",
    "events.json",
    "ideas.json",
    "pages.json",
    "jobs.json",
}


def test_export_writes_every_file_and_no_private_data(
    make_ctx: Callable[..., JobContext], tmp_path: Path
) -> None:
    ctx = make_ctx()
    apply_gsoc_data(ctx, DATA)
    score(ctx)
    out = tmp_path / "site-data"
    export_all(ctx.session, ctx.content, ctx.today, out)
    assert {p.name for p in out.iterdir()} == FILES
    everything = "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    assert "Someone Private" not in everything  # contributor names never leave the database
    scores = json.loads((out / "scores.json").read_text(encoding="utf-8"))
    assert "competition_score" not in json.dumps(scores)  # bands only, never the number
    assert scores["orgs"]["kubeflow"]["fit"] >= 0
    gsoc = json.loads((out / "gsoc.json").read_text(encoding="utf-8"))
    assert gsoc["latest_year"] == 2026 and any(o["slug"] == "tiny-recent-org" for o in gsoc["orgs"])


def test_issue_board_caps_and_rotates(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    seen = dt.datetime(2026, 10, 5)
    for n in range(1, 15):
        ctx.session.add(
            OpenIssue(
                repo="kubevirt/kubevirt",
                number=n,
                title=f"Issue {n}",
                url=f"https://github.com/kubevirt/kubevirt/issues/{n}",
                created_at=seen - dt.timedelta(days=n),
                comments=0,
                assigned=n == 1,  # assigned issues are never shown
                linked_pr=n == 2,  # nor are ones with a linked PR
                labels=[],
                seen_at=seen,
            )
        )
    ctx.session.flush()
    day1 = export_issues(ctx.session, dt.date(2026, 10, 5))["orgs"]["kubevirt"]
    day2 = export_issues(ctx.session, dt.date(2026, 10, 6))["orgs"]["kubevirt"]
    assert day1["total_open"] == 14 and day1["open_to_newcomers"] == 12
    assert len(day1["shown"]) == ISSUES_PER_ORG
    assert not {1, 2} & {i["number"] for i in day1["shown"]}
    assert {i["number"] for i in day1["shown"]} != {
        i["number"] for i in day2["shown"]
    }  # rotates daily
    assert (
        day1 == export_issues(ctx.session, dt.date(2026, 10, 5))["orgs"]["kubevirt"]
    )  # deterministic
