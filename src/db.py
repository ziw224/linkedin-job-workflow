"""
src/db.py — MySQL connection and query helpers for job-workflow-oss.

Environment variables (set in .env):
    DB_HOST     default: 127.0.0.1
    DB_PORT     default: 3306
    DB_USER     default: root
    DB_PASSWORD required
    DB_NAME     default: job_workflow
"""

from __future__ import annotations
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    import pymysql
    import pymysql.cursors
    _HAS_PYMYSQL = True
except ImportError:
    _HAS_PYMYSQL = False
    logger.warning("pymysql not installed — DB features disabled. Run: pip install pymysql")


def _get_conn_params() -> dict:
    return {
        "host":     os.getenv("DB_HOST", "127.0.0.1"),
        "port":     int(os.getenv("DB_PORT", "3306")),
        "user":     os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "job_workflow"),
        "charset":  "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor if _HAS_PYMYSQL else None,
        "autocommit": True,
    }


@contextmanager
def get_conn():
    """Context manager yielding a pymysql connection."""
    if not _HAS_PYMYSQL:
        raise RuntimeError("pymysql not installed. Run: pip install pymysql")
    conn = pymysql.connect(**_get_conn_params())
    try:
        yield conn
    finally:
        conn.close()


def db_available() -> bool:
    """Return True if MySQL is reachable."""
    if not _HAS_PYMYSQL:
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False


# ── Users ──────────────────────────────────────────────────────────────────────

def get_user(discord_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE discord_id = %s", (discord_id,))
            return cur.fetchone()


def upsert_user(discord_id: str, **fields) -> None:
    """Insert or update a user record."""
    allowed = {"name", "email", "linkedin", "portfolio", "bio",
                "resume_pdf_prefix", "notify_channel_id"}
    data = {k: v for k, v in fields.items() if k in allowed}
    if not data:
        return
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["%s"] * len(data))
    updates = ", ".join(f"{k} = VALUES({k})" for k in data)
    sql = (
        f"INSERT INTO users (discord_id, {cols}) VALUES (%s, {placeholders}) "
        f"ON DUPLICATE KEY UPDATE {updates}"
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [discord_id] + list(data.values()))


def user_exists(discord_id: str) -> bool:
    row = get_user(discord_id)
    return row is not None and bool(row.get("name"))


# ── Search configs ─────────────────────────────────────────────────────────────

def get_user_search_config(discord_id: str) -> dict | None:
    """Return merged {sde: {...}, ai: {...}} or None if not set."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM user_search_configs WHERE discord_id = %s",
                (discord_id,)
            )
            rows = cur.fetchall()
    if not rows:
        return None
    result = {}
    for row in rows:
        cat = row["category"]
        result[cat] = {
            "keywords":         json.loads(row["keywords"]) if isinstance(row["keywords"], str) else row["keywords"],
            "experience_levels": json.loads(row["experience_levels"]) if isinstance(row["experience_levels"], str) else row["experience_levels"],
            "target_count":     row["target_count"],
            "locations":        json.loads(row["locations"]) if row["locations"] and isinstance(row["locations"], str) else row["locations"],
        }
    return result


def upsert_search_config(discord_id: str, category: str,
                          keywords: list, experience_levels: list,
                          target_count: int, locations: list | None = None) -> None:
    sql = """
        INSERT INTO user_search_configs
            (discord_id, category, keywords, experience_levels, target_count, locations)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            keywords = VALUES(keywords),
            experience_levels = VALUES(experience_levels),
            target_count = VALUES(target_count),
            locations = VALUES(locations)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [
                discord_id, category,
                json.dumps(keywords),
                json.dumps(experience_levels),
                target_count,
                json.dumps(locations) if locations else None,
            ])


# ── Seen jobs ──────────────────────────────────────────────────────────────────

def get_seen_job_ids(discord_id: str) -> set[str]:
    """Return set of job IDs already seen by this user."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT job_id FROM seen_jobs WHERE discord_id = %s",
                (discord_id,)
            )
            rows = cur.fetchall()
    return {row["job_id"] for row in rows}


def mark_jobs_seen(discord_id: str, job_ids: list[str]) -> None:
    """Bulk-insert new seen job IDs, ignoring duplicates."""
    if not job_ids:
        return
    sql = "INSERT IGNORE INTO seen_jobs (discord_id, job_id) VALUES (%s, %s)"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, [(discord_id, jid) for jid in job_ids])


def reset_seen_jobs(discord_id: str) -> int:
    """Clear seen jobs for a user. Returns count deleted."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM seen_jobs WHERE discord_id = %s", (discord_id,))
            return cur.rowcount


# ── Job runs ───────────────────────────────────────────────────────────────────

def start_run(run_id: str, discord_id: str) -> None:
    sql = "INSERT INTO job_runs (run_id, discord_id, status) VALUES (%s, %s, 'running')"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id, discord_id))


def finish_run(run_id: str, duration_ms: int, status: str,
               jobs_total: int, jobs_ok: int) -> None:
    sql = """
        UPDATE job_runs
        SET completed_at = NOW(), duration_ms = %s, status = %s,
            jobs_total = %s, jobs_ok = %s
        WHERE run_id = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (duration_ms, status, jobs_total, jobs_ok, run_id))


def save_job_result(run_id: str, discord_id: str, result: dict) -> None:
    job = result["job"]
    sql = """
        INSERT INTO job_results
            (run_id, discord_id, job_id, title, company, location, url,
             success, html_path, pdf_path, cover_letter_path, why_company_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [
                run_id, discord_id, job.get("job_id", ""),
                job.get("title"), job.get("company"),
                job.get("location"), job.get("url"),
                result.get("success", False),
                str(result.get("html_path") or ""),
                str(result.get("pdf_path") or ""),
                str(result.get("cover_letter") or ""),
                str(result.get("why_company") or ""),
            ])


def get_today_results(discord_id: str) -> list[dict]:
    """Get today's job results for status command."""
    sql = """
        SELECT jr.title, jr.company, jr.location, jr.success,
               jr.html_path, jr.pdf_path, jr.created_at
        FROM job_results jr
        JOIN job_runs runs ON jr.run_id = runs.run_id
        WHERE jr.discord_id = %s
          AND DATE(jr.created_at) = CURDATE()
        ORDER BY jr.created_at DESC
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (discord_id,))
            return cur.fetchall()
