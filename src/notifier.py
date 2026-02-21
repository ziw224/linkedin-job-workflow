"""
src/notifier.py – Send job-hunt summary to Discord via webhook.
Handles Discord's 2000-char message limit by splitting into multiple posts.
"""
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

DISCORD_LIMIT = 1900  # leave some headroom below 2000


def _post_webhook(webhook_url: str, content: str) -> None:
    """POST a single message. Logs warning on non-2xx."""
    try:
        import requests
        resp = requests.post(webhook_url, json={"content": content}, timeout=15)
        if resp.status_code in (200, 204):
            logger.info(f"Discord webhook sent ({len(content)} chars).")
        else:
            logger.warning(f"Webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Webhook failed: {e}")


def _send_chunked(webhook_url: str, lines: list[str]) -> None:
    """
    Join lines and send to Discord, splitting on newlines if > DISCORD_LIMIT chars.
    Never splits a single line mid-way; sends each oversized line as its own message.
    """
    chunk: list[str] = []
    chunk_len = 0

    def flush():
        nonlocal chunk, chunk_len
        if chunk:
            _post_webhook(webhook_url, "\n".join(chunk))
        chunk = []
        chunk_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if chunk_len + line_len > DISCORD_LIMIT:
            flush()
        # Single line too long? send it alone (truncated)
        if line_len > DISCORD_LIMIT:
            _post_webhook(webhook_url, line[:DISCORD_LIMIT])
            continue
        chunk.append(line)
        chunk_len += line_len

    flush()


def send_discord_report(results: list[dict]) -> None:
    """
    results: list of dicts with keys job, html_path, pdf_path, cover_letter, why_company, success.
    Sends a formatted (chunked) report to the Discord webhook.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL not set in .env")
        return

    today = date.today().strftime("%B %d, %Y")
    ok     = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    if not results:
        _post_webhook(
            webhook_url,
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

    _send_chunked(webhook_url, lines)
