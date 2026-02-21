"""
src/notifier.py – Send job-hunt summary to Discord via webhook or bot API.
Handles Discord's 2000-char message limit by splitting into multiple posts.

Routing priority:
  1. channel_id + DISCORD_BOT_TOKEN  → Discord REST API (per-user channel)
  2. DISCORD_WEBHOOK_URL              → webhook (global fallback)
"""
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

DISCORD_LIMIT = 1900  # leave some headroom below 2000


def _post_webhook(webhook_url: str, content: str) -> None:
    """POST a single message via webhook. Logs warning on non-2xx."""
    try:
        import requests
        resp = requests.post(webhook_url, json={"content": content}, timeout=15)
        if resp.status_code in (200, 204):
            logger.info(f"Discord webhook sent ({len(content)} chars).")
        else:
            logger.warning(f"Webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Webhook failed: {e}")


def _post_channel(channel_id: str, bot_token: str, content: str) -> None:
    """POST a single message to a Discord channel via bot API."""
    try:
        import requests
        resp = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {bot_token}",
                "Content-Type": "application/json",
            },
            json={"content": content},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            logger.info(f"Discord channel {channel_id} message sent ({len(content)} chars).")
        else:
            logger.warning(f"Channel API returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Channel API post failed: {e}")


def _make_poster(channel_id: str | None = None):
    """
    Return a callable that posts a single message string.
    Picks the best available transport automatically.
    """
    bot_token   = os.getenv("DISCORD_BOT_TOKEN", "")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")

    if channel_id and bot_token:
        return lambda content: _post_channel(channel_id, bot_token, content)
    if webhook_url:
        return lambda content: _post_webhook(webhook_url, content)
    logger.error("No Discord transport configured (set DISCORD_BOT_TOKEN+channel or DISCORD_WEBHOOK_URL).")
    return lambda content: None


def _send_chunked(post_fn, lines: list[str]) -> None:
    """
    Join lines and send via post_fn, splitting on newlines if > DISCORD_LIMIT chars.
    Never splits a single line mid-way; sends each oversized line as its own message.
    """
    chunk: list[str] = []
    chunk_len = 0

    def flush():
        nonlocal chunk, chunk_len
        if chunk:
            post_fn("\n".join(chunk))
        chunk = []
        chunk_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if chunk_len + line_len > DISCORD_LIMIT:
            flush()
        if line_len > DISCORD_LIMIT:
            post_fn(line[:DISCORD_LIMIT])
            continue
        chunk.append(line)
        chunk_len += line_len

    flush()


def send_discord_report(results: list[dict], channel_id: str | None = None) -> None:
    """
    Send a formatted (chunked) job-hunt report.

    Args:
        results:    list of dicts with keys job, html_path, pdf_path,
                    cover_letter, why_company, success.
        channel_id: Discord channel ID for bot-API routing.
                    Falls back to DISCORD_WEBHOOK_URL if not set or no bot token.
    """
    post_fn = _make_poster(channel_id)

    today  = date.today().strftime("%B %d, %Y")
    ok     = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    if not results:
        post_fn(
            f"🔍 **Daily Job Hunt** — {today}\nNo new jobs found today. Checking again tomorrow!"
        )
        return

    lines: list[str] = [
        f"🔍 **Daily Job Hunt Report** — {today}",
        f"Found **{len(results)}** new job(s) · ✅ {len(ok)} tailored · ❌ {len(failed)} failed",
        "",
    ]

    for i, r in enumerate(results, 1):
        job    = r["job"]
        status = "✅ Resume ready" if r["success"] else "❌ Resume failed"
        cl_ok  = "✅" if r.get("cover_letter") else "❌"
        why_ok = "✅" if r.get("why_company")  else "❌"
        lines += [
            f"**{i}. {job['title']}** @ {job['company']} | {job['location']}",
            f"<{job['url']}>",
            f"{status} · Cover Letter {cl_ok} · Why {job['company']} {why_ok}",
            "",
        ]

    _send_chunked(post_fn, lines)
