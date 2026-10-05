"""Alert delivery. Telegram when configured; otherwise events only appear in the feed and RSS."""

from __future__ import annotations

import os
from collections.abc import Sequence

import httpx

from collectors.db.models import Event
from collectors.http import Http

MAX_LINES = 25
ICONS = {
    "deadline": "⏰",
    "ideas_published": "🆕",
    "ideas_changed": "📝",
    "org_announced": "✅",
    "org_not_listed": "⚠️",
    "gsoc_orgs_published": "📣",
    "program_page_changed": "🔎",
    "pr_merged": "🎉",
    "job_failing": "🛠",
}


def format_message(events: Sequence[Event], site_url: str | None = None) -> str:
    lines = [f"OSS Map: {len(events)} update{'s' if len(events) != 1 else ''}"]
    for event in events[:MAX_LINES]:
        line = f"{ICONS.get(event.kind, '•')} {event.title}"
        if event.url:
            line += f"\n   {event.url}"
        lines.append(line)
    if len(events) > MAX_LINES:
        lines.append(f"…and {len(events) - MAX_LINES} more")
    if site_url:
        lines.append(f"\nAll changes: {site_url.rstrip('/')}/changes/")
    return "\n".join(lines)


def send_alerts(http: Http, events: Sequence[Event]) -> tuple[str, str | None]:
    """Returns (channel, error). Never puts the bot token in an error message or log line."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "none", None
    if not events:
        return "telegram", None
    text = format_message(events, os.environ.get("SITE_URL"))
    try:
        resp = http.request(
            "POST",
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
        )
    except httpx.HTTPError as exc:
        return "telegram", f"Telegram request failed ({type(exc).__name__})"
    if resp.status_code != 200:
        return "telegram", f"Telegram returned HTTP {resp.status_code}"
    return "telegram", None
