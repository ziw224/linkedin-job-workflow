"""
src/notion_tracker.py – Add scraped jobs to Notion Job Application Tracker.

Required env vars:
    NOTION_TOKEN   – ntn_xxxx (Internal Integration token)
    NOTION_DB_ID   – 32-char database ID from the tracker page URL

Install: pip install notion-client
"""
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


def add_jobs_to_notion(results: list[dict]) -> None:
    token = os.getenv("NOTION_TOKEN", "")
    db_id = os.getenv("NOTION_DB_ID", "")

    if not token or not db_id:
        logger.warning("NOTION_TOKEN or NOTION_DB_ID not set — skipping Notion sync")
        return

    try:
        from notion_client import Client
    except ImportError:
        logger.error("notion-client not installed. Run: pip install notion-client")
        return

    notion = Client(auth=token)
    today = date.today().isoformat()  # e.g. "2026-02-22"

    ok, failed = 0, 0
    for r in results:
        job = r.get("job", {})
        if not job:
            continue
        title   = job.get("title", "")
        company = job.get("company", "")
        url     = job.get("url") or None
        loc     = job.get("location", "").split(",")[0].strip()  # "San Francisco, CA" → "San Francisco"

        try:
            props = {
                "Job Title": {
                    "title": [{"text": {"content": title}}]
                },
                "Application Status": {
                    "status": {"name": "Not started"}
                },
                "Company": {
                    "rich_text": [{"text": {"content": company}}]
                },
                "Location": {
                    "select": {"name": loc} if loc else None
                },
                "URL": {
                    "url": url
                },
                "Application Date": {
                    "date": {"start": today}
                },
            }

            # Remove None-valued properties (Notion rejects null selects)
            props = {k: v for k, v in props.items() if v is not None}
            # Also strip url if empty
            if "URL" in props and props["URL"]["url"] is None:
                del props["URL"]

            notion.pages.create(
                parent={"database_id": db_id},
                properties=props,
            )
            ok += 1
            logger.info(f"  ✅ Notion: {title} @ {company}")

        except Exception as e:
            failed += 1
            logger.warning(f"  ❌ Notion failed [{title} @ {company}]: {e}")

    logger.info(f"Notion sync — {ok} added, {failed} failed")
