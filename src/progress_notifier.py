"""
src/progress_notifier.py — Send real-time progress updates to Discord during a run.

Stages:
  started    → "🚀 Job hunt started — scraping LinkedIn..."
  scraped    → "📡 Scraped N jobs, starting tailoring..."
  job_done   → (accumulated, sent in batches)
  finished   → final summary embed

Uses DISCORD_WEBHOOK_URL (same as notifier.py).
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

WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
BATCH_INTERVAL = 60  # seconds between batch job-done updates


def _post(content: str, embeds: Optional[list] = None) -> None:
    """Fire-and-forget webhook POST. Never raises."""
    if not WEBHOOK_URL:
        return
    try:
        import requests
        payload: dict = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        logger.debug(f"[progress_notifier] webhook failed: {e}")


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
        # Start background flush thread
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
