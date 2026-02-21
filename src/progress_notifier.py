"""
src/progress_notifier.py — Send real-time progress updates to Discord during a run.

Routing priority (same as notifier.py):
  1. channel_id + DISCORD_BOT_TOKEN  → Discord REST API (per-user channel)
  2. DISCORD_WEBHOOK_URL              → webhook (global fallback)

Call set_notify_target(channel_id=...) at the start of main.run() to route
all notifications for that run to the correct Discord channel.

Stages:
  started    → "🚀 Job hunt started — scraping LinkedIn..."
  scraped    → "📡 Scraped N jobs, starting tailoring..."
  job_done   → (accumulated, sent in batches)
  finished   → final summary embed

Fails silently — never disrupts the main workflow.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

BATCH_INTERVAL = 60  # seconds between batch job-done updates

# ── Per-run notify target (set by main.py before each run) ────────────────────
_notify_channel_id: str = ""


def set_notify_target(channel_id: str | None = None) -> None:
    """
    Configure the Discord channel for this run.
    Call this at the top of main.run() before any notify_* calls.
    """
    global _notify_channel_id
    _notify_channel_id = channel_id or ""
    if _notify_channel_id:
        logger.info(f"[progress_notifier] routing to channel {_notify_channel_id}")
    else:
        logger.info("[progress_notifier] routing via webhook (no channel_id set)")


def _post(content: str, embeds: Optional[list] = None) -> None:
    """Fire-and-forget Discord POST. Never raises."""
    bot_token   = os.getenv("DISCORD_BOT_TOKEN", "")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")

    try:
        import requests
        payload: dict = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds

        if _notify_channel_id and bot_token:
            requests.post(
                f"https://discord.com/api/v10/channels/{_notify_channel_id}/messages",
                headers={
                    "Authorization": f"Bot {bot_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
        elif webhook_url:
            requests.post(webhook_url, json=payload, timeout=10)
        # else: silently skip (no transport configured)
    except Exception as e:
        logger.debug(f"[progress_notifier] post failed: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def notify_started() -> None:
    """Call at the very beginning of main.run()."""
    today = date.today().strftime("%b %d, %Y")
    _post(f"🚀 **Job Hunt starting** — {today}\n📡 Scraping LinkedIn...")


def notify_scraped(n_jobs: int) -> None:
    """Call after Phase 1 (scraping) completes."""
    if n_jobs == 0:
        _post("🔍 No new jobs found today. Stopping early.")
    else:
        _post(f"📋 Found **{n_jobs}** new job(s) — starting resume tailoring...")


class BatchProgressReporter:
    """
    Collects job-done events and sends them to Discord in batches.
    Call `.job_done(label, success)` from any thread.
    Call `.flush()` to force a send.
    Call `.close()` when done.
    """

    def __init__(self, total: int):
        self._total = total
        self._done: list[tuple[str, bool]] = []
        self._lock = threading.Lock()
        self._last_sent = time.time()
        self._closed = False
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def job_done(self, label: str, success: bool) -> None:
        with self._lock:
            self._done.append((label, success))

    def _flush_loop(self) -> None:
        while not self._closed:
            time.sleep(5)
            with self._lock:
                if self._done and (time.time() - self._last_sent) >= BATCH_INTERVAL:
                    self._send_batch()

    def _send_batch(self) -> None:
        """Must be called with self._lock held."""
        if not self._done:
            return
        done_count = len(self._done)
        ok = sum(1 for _, s in self._done if s)
        lines = [
            f"⚙️ **Progress** — {done_count}/{self._total} jobs done · ✅ {ok} ready",
        ]
        for label, success in self._done:
            icon = "✅" if success else "❌"
            lines.append(f"  {icon} {label}")
        _post("\n".join(lines))
        self._done = []
        self._last_sent = time.time()

    def flush(self) -> None:
        with self._lock:
            self._send_batch()

    def close(self) -> None:
        self._closed = True
        self.flush()


def notify_finished(results: list[dict], elapsed_s: int) -> None:
    """Call after all jobs are done (before send_discord_report)."""
    ok = sum(r["success"] for r in results)
    total = len(results)
    mins, secs = divmod(elapsed_s, 60)
    dur = f"{mins}m {secs}s" if mins else f"{secs}s"
    _post(
        f"✅ **Job Hunt complete** — {dur}\n"
        f"**{ok}/{total}** resumes ready — full report below 👇"
    )
