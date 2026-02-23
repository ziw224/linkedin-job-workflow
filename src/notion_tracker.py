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


def _url_exists(notion, db_id: str, url: str) -> bool:
    """Check if a job URL already exists in the Notion DB."""
    if not url:
        return False
    try:
        res = notion.databases.query(
            database_id=db_id,
            filter={"property": "URL", "url": {"equals": url}},
        )
        return len(res.get("results", [])) > 0
    except Exception as e:
        logger.warning(f"  Notion dedup check failed: {e}")
        return False  # fail open — allow insert


def add_jobs_to_notion(results: list[dict], only_success: bool = True) -> None:
    """Add jobs to Notion tracker.

    Args:
        results:      List of result dicts from process_job().
        only_success: If True (default), only add jobs where resume was successfully generated.
                      Set False to add all scraped jobs regardless of resume status.
    """
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
    today = date.today().isoformat()

    ok, failed, skipped = 0, 0, 0
    for r in results:
        job = r.get("job", {})
        if not job:
            continue

        # Skip failed jobs unless caller opts in
        if only_success and not r.get("success", False):
            logger.info(f"  ⏭️  Skipping Notion (resume failed): {job.get('title')} @ {job.get('company')}")
            skipped += 1
            continue

        title   = job.get("title", "")
        company = job.get("company", "")
        url     = job.get("url") or None
        loc     = job.get("location", "").split(",")[0].strip()

        # Dedup by URL
        if url and _url_exists(notion, db_id, url):
            logger.info(f"  ⏭️  Already in Notion: {title} @ {company}")
            skipped += 1
            continue

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

            # Remove None-valued properties
            props = {k: v for k, v in props.items() if v is not None}
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

    logger.info(f"Notion sync — {ok} added, {skipped} skipped, {failed} failed")
