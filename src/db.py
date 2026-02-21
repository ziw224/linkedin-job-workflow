"""
src/db.py — SQLite database helpers for job-workflow-oss.

SQLite is used by default (zero-config, built-in Python, no server needed).
DB file: ~/Projects/job-workflow-oss/data/job_workflow.db

To use MySQL instead, set USE_MYSQL=true in .env and provide DB_* credentials.
"""

from __future__ import annotations
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.resolve()
_SQLITE_PATH = _ROOT / "data" / "job_workflow.db"

# ── Backend selection ──────────────────────────────────────────────────────────
_USE_MYSQL = os.getenv("USE_MYSQL", "false").lower() == "true"


def _sqlite_conn() -> sqlite3.Connection:
    _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_sqlite(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist (SQLite version of schema.sql)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id        TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            email             TEXT,
            linkedin          TEXT,
            portfolio         TEXT,
            bio               TEXT,
            resume_pdf_prefix TEXT DEFAULT 'Resume',
            notify_channel_id TEXT,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_search_configs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id        TEXT NOT NULL,
            category          TEXT NOT NULL CHECK(category IN ('sde','ai')),
            keywords          TEXT NOT NULL,
            experience_levels TEXT NOT NULL,
            target_count      INTEGER DEFAULT 5,
            locations         TEXT DEFAULT NULL,
            FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE,
            UNIQUE (discord_id, category)
        );

        CREATE TABLE IF NOT EXISTS seen_jobs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT NOT NULL,
            job_id     TEXT NOT NULL,
            seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE,
            UNIQUE (discord_id, job_id)
        );

        CREATE INDEX IF NOT EXISTS idx_seen_discord ON seen_jobs(discord_id);

        CREATE TABLE IF NOT EXISTS job_runs (
            run_id       TEXT PRIMARY KEY,
            discord_id   TEXT NOT NULL,
            started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            duration_ms  INTEGER,
            status       TEXT DEFAULT 'running',
            jobs_total   INTEGER DEFAULT 0,
            jobs_ok      INTEGER DEFAULT 0,
            FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS job_results (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id             TEXT NOT NULL,
            discord_id         TEXT NOT NULL,
            job_id             TEXT NOT NULL,
            title              TEXT,
            company            TEXT,
            location           TEXT,
            url                TEXT,
            success            INTEGER DEFAULT 0,
            html_path          TEXT,
            pdf_path           TEXT,
            cover_letter_path  TEXT,
            why_company_path   TEXT,
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES job_runs(run_id) ON DELETE CASCADE
        );
    """)
    conn.commit()


@contextmanager
def get_conn():
    """Yield a database connection (SQLite or MySQL)."""
    if _USE_MYSQL:
        yield from _mysql_conn()
        return

    conn = _sqlite_conn()
    _init_sqlite(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _mysql_conn():
    """MySQL fallback (requires pymysql + DB_* env vars)."""
    try:
        import pymysql.cursors
        import pymysql
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "job_workflow"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        try:
            yield conn
        finally:
            conn.close()
    except ImportError:
        raise RuntimeError("pymysql not installed. Run: pip install pymysql")


def db_available() -> bool:
    """Always True for SQLite; checks connection for MySQL."""
    if _USE_MYSQL:
        try:
            with _mysql_conn() as conn:
                conn.cursor().execute("SELECT 1")
            return True
        except Exception:
            return False
    return True  # SQLite always works


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)  # pymysql DictRow


# ── Users ──────────────────────────────────────────────────────────────────────

def get_user(discord_id: str) -> dict | None:
    with get_conn() as conn:
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE discord_id = %s", (discord_id,))
                return cur.fetchone()
        else:
            row = conn.execute("SELECT * FROM users WHERE discord_id = ?",
                               (discord_id,)).fetchone()
            return _row_to_dict(row)


def upsert_user(discord_id: str, **fields) -> None:
    allowed = {"name", "email", "linkedin", "portfolio", "bio",
               "resume_pdf_prefix", "notify_channel_id"}
    data = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not data:
        return

    with get_conn() as conn:
        if _USE_MYSQL:
            cols = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            updates = ", ".join(f"{k} = VALUES({k})" for k in data)
            sql = (f"INSERT INTO users (discord_id, {cols}) VALUES (%s, {placeholders}) "
                   f"ON DUPLICATE KEY UPDATE {updates}")
            with conn.cursor() as cur:
                cur.execute(sql, [discord_id] + list(data.values()))
        else:
            cols = ", ".join(["discord_id"] + list(data.keys()))
            placeholders = ", ".join(["?"] * (len(data) + 1))
            updates = ", ".join(f"{k} = excluded.{k}" for k in data)
            sql = (f"INSERT INTO users ({cols}) VALUES ({placeholders}) "
                   f"ON CONFLICT(discord_id) DO UPDATE SET {updates}, "
                   f"updated_at = CURRENT_TIMESTAMP")
            conn.execute(sql, [discord_id] + list(data.values()))


def user_exists(discord_id: str) -> bool:
    row = get_user(discord_id)
    return row is not None and bool(row.get("name"))


# ── Search configs ─────────────────────────────────────────────────────────────

def get_user_search_config(discord_id: str) -> dict | None:
    with get_conn() as conn:
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user_search_configs WHERE discord_id = %s",
                            (discord_id,))
                rows = cur.fetchall()
        else:
            rows = [_row_to_dict(r) for r in
                    conn.execute("SELECT * FROM user_search_configs WHERE discord_id = ?",
                                 (discord_id,)).fetchall()]
    if not rows:
        return None
    result = {}
    for row in rows:
        cat = row["category"]
        result[cat] = {
            "keywords":          json.loads(row["keywords"]),
            "experience_levels": json.loads(row["experience_levels"]),
            "target_count":      row["target_count"],
            "locations":         json.loads(row["locations"]) if row.get("locations") else None,
        }
    return result


def upsert_search_config(discord_id: str, category: str, keywords: list,
                          experience_levels: list, target_count: int,
                          locations: list | None = None) -> None:
    with get_conn() as conn:
        if _USE_MYSQL:
            sql = """
                INSERT INTO user_search_configs
                    (discord_id, category, keywords, experience_levels, target_count, locations)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    keywords=VALUES(keywords), experience_levels=VALUES(experience_levels),
                    target_count=VALUES(target_count), locations=VALUES(locations)
            """
            with conn.cursor() as cur:
                cur.execute(sql, [discord_id, category, json.dumps(keywords),
                                  json.dumps(experience_levels), target_count,
                                  json.dumps(locations) if locations else None])
        else:
            sql = """
                INSERT INTO user_search_configs
                    (discord_id, category, keywords, experience_levels, target_count, locations)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(discord_id, category) DO UPDATE SET
                    keywords=excluded.keywords, experience_levels=excluded.experience_levels,
                    target_count=excluded.target_count, locations=excluded.locations
            """
            conn.execute(sql, [discord_id, category, json.dumps(keywords),
                               json.dumps(experience_levels), target_count,
                               json.dumps(locations) if locations else None])


# ── Seen jobs ──────────────────────────────────────────────────────────────────

def get_seen_job_ids(discord_id: str) -> set[str]:
    with get_conn() as conn:
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute("SELECT job_id FROM seen_jobs WHERE discord_id = %s", (discord_id,))
                return {r["job_id"] for r in cur.fetchall()}
        else:
            rows = conn.execute("SELECT job_id FROM seen_jobs WHERE discord_id = ?",
                                (discord_id,)).fetchall()
            return {r["job_id"] for r in rows}


def mark_jobs_seen(discord_id: str, job_ids: list[str]) -> None:
    if not job_ids:
        return
    with get_conn() as conn:
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT IGNORE INTO seen_jobs (discord_id, job_id) VALUES (%s, %s)",
                    [(discord_id, jid) for jid in job_ids]
                )
        else:
            conn.executemany(
                "INSERT OR IGNORE INTO seen_jobs (discord_id, job_id) VALUES (?, ?)",
                [(discord_id, jid) for jid in job_ids]
            )


def reset_seen_jobs(discord_id: str) -> int:
    with get_conn() as conn:
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM seen_jobs WHERE discord_id = %s", (discord_id,))
                return cur.rowcount
        else:
            cur = conn.execute("DELETE FROM seen_jobs WHERE discord_id = ?", (discord_id,))
            return cur.rowcount


# ── Job runs ───────────────────────────────────────────────────────────────────

def start_run(run_id: str, discord_id: str) -> None:
    with get_conn() as conn:
        ph = "%s" if _USE_MYSQL else "?"
        sql = f"INSERT INTO job_runs (run_id, discord_id, status) VALUES ({ph},{ph},'running')"
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute(sql, (run_id, discord_id))
        else:
            conn.execute(sql, (run_id, discord_id))


def finish_run(run_id: str, duration_ms: int, status: str,
               jobs_total: int, jobs_ok: int) -> None:
    with get_conn() as conn:
        ph = "%s" if _USE_MYSQL else "?"
        sql = (f"UPDATE job_runs SET completed_at=CURRENT_TIMESTAMP, duration_ms={ph}, "
               f"status={ph}, jobs_total={ph}, jobs_ok={ph} WHERE run_id={ph}")
        args = (duration_ms, status, jobs_total, jobs_ok, run_id)
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute(sql, args)
        else:
            conn.execute(sql, args)


def save_job_result(run_id: str, discord_id: str, result: dict) -> None:
    job = result["job"]
    ph = "%s" if _USE_MYSQL else "?"
    sql = (f"INSERT INTO job_results "
           f"(run_id,discord_id,job_id,title,company,location,url,success,"
           f"html_path,pdf_path,cover_letter_path,why_company_path) "
           f"VALUES ({','.join([ph]*12)})")
    args = [run_id, discord_id, job.get("job_id",""), job.get("title"),
            job.get("company"), job.get("location"), job.get("url"),
            int(result.get("success", False)),
            str(result.get("html_path") or ""), str(result.get("pdf_path") or ""),
            str(result.get("cover_letter") or ""), str(result.get("why_company") or "")]
    with get_conn() as conn:
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute(sql, args)
        else:
            conn.execute(sql, args)


def get_today_results(discord_id: str) -> list[dict]:
    with get_conn() as conn:
        if _USE_MYSQL:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT jr.title, jr.company, jr.location, jr.success, jr.created_at
                    FROM job_results jr
                    WHERE jr.discord_id = %s AND DATE(jr.created_at) = CURDATE()
                    ORDER BY jr.created_at DESC
                """, (discord_id,))
                return cur.fetchall()
        else:
            rows = conn.execute("""
                SELECT title, company, location, success, created_at
                FROM job_results
                WHERE discord_id = ? AND DATE(created_at) = DATE('now')
                ORDER BY created_at DESC
            """, (discord_id,)).fetchall()
            return [_row_to_dict(r) for r in rows]
