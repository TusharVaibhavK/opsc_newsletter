"""Scoring bands, fit, deadline and failure alerts, and alert delivery."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import httpx
import pytest
import respx
from sqlalchemy import select

from collectors.db.models import Event, JobRun
from collectors.jobs import JobContext, run_job
from collectors.jobs.score import (
    OrgInputs,
    competition,
    deadline_events,
    failing_job_events,
    fit_scores,
    score_and_notify,
)


def inputs(org: str, crowd: float, slots: float = 5.0, ideas: float = 10.0) -> OrgInputs:
    return OrgInputs(
        org=org,
        values={
            "new_contributors": crowd * 10,
            "claim_speed": crowd,
            "newcomer_backlog": crowd * 3,
            "log_stars": crowd,
            "slots": slots,
            "ideas": ideas,
        },
    )


def test_bands_are_relative_terciles() -> None:
    result = competition([inputs(f"org{i}", float(i)) for i in range(6)])
    assert [result[f"org{i}"]["band"] for i in range(6)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
    ]
    assert all(r["confidence"] == 1.0 for r in result.values())


def test_more_slots_means_less_crowded() -> None:
    result = competition(
        [
            inputs("a", 1, slots=1),
            inputs("b", 1, slots=2),
            inputs("c", 1, slots=20),
            inputs("d", 1, slots=3),
        ]
    )
    assert result["c"]["score"] == min(r["score"] for r in result.values())


def test_too_little_data_means_unknown() -> None:
    sparse = OrgInputs(
        "sparse",
        {
            k: None
            for k in ("new_contributors", "claim_speed", "newcomer_backlog", "log_stars", "ideas")
        }
        | {"slots": 3.0},
    )
    result = competition([inputs("a", 1), inputs("b", 2), inputs("c", 3), inputs("d", 4), sparse])
    assert result["sparse"]["band"] == "unknown" and result["sparse"]["score"] is None
    few = competition([inputs("a", 1), inputs("b", 2), inputs("c", 3)])
    assert {r["band"] for r in few.values()} == {"unknown"}  # fewer than 4 comparable orgs


def test_fit_rewards_language_overlap(make_ctx: Callable[..., JobContext]) -> None:
    fits = fit_scores(make_ctx())
    assert fits["kubeflow"]["languages"] == 1.0  # go + python, both in the profile
    assert fits["api-dash"]["languages"] == 0.0  # dart
    assert fits["kubeflow"]["fit"] > fits["api-dash"]["fit"]


def test_deadline_alert_a_week_out(deadline_ctx: JobContext) -> None:
    ctx = deadline_ctx
    deadline_events(ctx)
    titles = [e.title for e in ctx.session.scalars(select(Event).where(Event.kind == "deadline"))]
    assert "GSoC 2027: applications close in 6 days (Mar 31, estimated)" in titles


def test_two_failures_in_a_row_alert(make_ctx: Callable[..., JobContext]) -> None:
    ctx = make_ctx()
    for hour in (1, 2):
        ctx.session.add(
            JobRun(
                job="watch_pages",
                started_at=dt.datetime(2026, 10, 5, hour),
                status="error",
                summary="boom",
            )
        )
    ctx.session.flush()
    assert failing_job_events(ctx) == 1


def test_alerts_go_to_telegram(deadline_ctx: JobContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    ctx = deadline_ctx
    with respx.mock() as router:
        route = router.post("https://api.telegram.org/bot123456:SECRET/sendMessage").respond(
            200, json={"ok": True}
        )
        run = run_job("score_and_notify", score_and_notify, ctx)
        assert route.called
        assert "GSoC 2027" in route.calls[0].request.content.decode()
    assert run.status == "ok"
    assert all(e.notified_via == "telegram" for e in ctx.session.scalars(select(Event)))


def test_failed_delivery_retries_later_and_hides_token(
    deadline_ctx: JobContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    ctx = deadline_ctx
    with respx.mock() as router:
        router.post("https://api.telegram.org/bot123456:SECRET/sendMessage").mock(
            return_value=httpx.Response(401)
        )
        run = run_job("score_and_notify", score_and_notify, ctx)
    assert (
        run.status == "error"
        and "SECRET" not in (run.summary or "")
        and "SECRET" not in (run.error or "")
    )
    assert all(e.notified_at is None for e in ctx.session.scalars(select(Event)))


def test_without_a_channel_alerts_are_only_in_the_feed(
    deadline_ctx: JobContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    ctx = deadline_ctx
    run = run_job("score_and_notify", score_and_notify, ctx)
    assert run.status == "ok"
    assert {e.notified_via for e in ctx.session.scalars(select(Event))} == {"none"}
