"""
src/linkedin_scraper.py – Scrape LinkedIn job postings via Playwright (no login required).

Two-phase approach:
  Phase 1 – collect job cards from public LinkedIn search result pages
  Phase 2 – visit each job detail page to fetch the full JD text
"""
import json
import logging
import re
import time
import random
from datetime import datetime, timezone
from pathlib import Path

from config.settings import (
    SEARCH_LOCATIONS,
    SORT_BY,
    MAX_DAYS_OLD,
    MAX_JOBS_PER_RUN,
    SEEN_JOBS_FILE,
    SDE_KEYWORDS, SDE_EXPERIENCE_LEVELS, TARGET_SDE_JOBS,
    AI_KEYWORDS,  AI_EXPERIENCE_LEVELS,  TARGET_AI_JOBS,
    FALLBACK_STAGES,
)

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_seen(path: Path) -> set[str]:
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return set(data.get("seen_ids", []))
    return set()


def _save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        with open(path) as f:
            existing = json.load(f)
    existing["seen_ids"] = list(seen)
    existing["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)


def _safe_sleep(base: float = 1.5, jitter: float = 1.0) -> None:
    """Polite delay to avoid rate limiting."""
    time.sleep(base + random.uniform(0, jitter))


def _sanitize(text: str) -> str:
    """Slug-safe string."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:40].strip("_")


# ── Playwright Scraper ─────────────────────────────────────────────────────────

def _days_ago(posted_date_str: str) -> int | None:
    """Parse a LinkedIn datetime string → how many days ago.

    LinkedIn gives date-only strings like '2026-02-20' (no time, no tz).
    Returns None if unparseable — callers treat None as 'age unknown, keep it'.
    """
    if not posted_date_str:
        return None
    try:
        # Date-only: "YYYY-MM-DD"
        if len(posted_date_str) == 10:
            posted = datetime.strptime(posted_date_str, "%Y-%m-%d")
            return max(0, (datetime.utcnow() - posted).days)
        # Full ISO with timezone: "2026-02-20T12:00:00Z" etc.
        posted = datetime.fromisoformat(posted_date_str.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - posted).days)
    except Exception:
        return None


def scrape_with_playwright(
    seen: set[str],
    max_days_old: int | None = None,
    sde_exp_levels: list[int] | None = None,
    ai_exp_levels:  list[int] | None = None,
    sde_keywords: list[str] | None = None,
    ai_keywords:  list[str] | None = None,
) -> list[dict]:
    """
    Two-phase scrape using per-category experience levels and keywords.

    Params override the defaults from search_config.json for fallback retries:
      max_days_old    – None means use config default
      sde_exp_levels  – None means use config default
      ai_exp_levels   – None means use config default
      sde_keywords    – None means use config default
      ai_keywords     – None means use config default
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        logger.error("playwright not installed.")
        return []

    effective_max_days  = MAX_DAYS_OLD if max_days_old is None else max_days_old
    effective_sde_exp   = SDE_EXPERIENCE_LEVELS if sde_exp_levels is None else sde_exp_levels
    effective_ai_exp    = AI_EXPERIENCE_LEVELS  if ai_exp_levels  is None else ai_exp_levels
    effective_sde_kw    = SDE_KEYWORDS if sde_keywords is None else sde_keywords
    effective_ai_kw     = AI_KEYWORDS  if ai_keywords  is None else ai_keywords

    # Build search plan: (keyword, location, experience_levels, category)
    search_plan = (
        [(kw, loc, effective_sde_exp, "sde") for kw in effective_sde_kw for loc in SEARCH_LOCATIONS] +
        [(kw, loc, effective_ai_exp,  "ai")  for kw in effective_ai_kw  for loc in SEARCH_LOCATIONS]
    )

    # ── Phase 1: collect metadata ──────────────────────────────────────────────
    candidates: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        for keyword, location, exp_levels, category in search_plan:
            if len(candidates) >= MAX_JOBS_PER_RUN:
                break

            query   = keyword.replace(" ", "%20")
            loc     = location.replace(" ", "%20").replace(",", "%2C")
            exp_str = "%2C".join(str(e) for e in exp_levels)
            url     = (
                f"https://www.linkedin.com/jobs/search/"
                f"?keywords={query}&location={loc}"
                f"&f_E={exp_str}&sortBy={SORT_BY}"
            )
            days_label = f"≤{effective_max_days}d" if effective_max_days > 0 else "any age"
            logger.info(f"  Searching [exp={','.join(map(str,exp_levels))} {days_label}]: {keyword} in {location}")
            try:
                page.goto(url, timeout=30_000)
                page.wait_for_timeout(3500)
            except Exception as e:
                logger.warning(f"  Page load failed: {e}")
                continue

            cards = page.query_selector_all(".job-search-card")
            logger.info(f"  Found {len(cards)} cards on page")

            for card in cards:
                if len(candidates) >= MAX_JOBS_PER_RUN:
                    break
                try:
                    link_el  = card.query_selector("a")
                    title_el = card.query_selector(".base-search-card__title")
                    comp_el  = card.query_selector(".base-search-card__subtitle")
                    loc_el   = card.query_selector(".job-search-card__location")
                    time_el  = card.query_selector("time")

                    href        = link_el.get_attribute("href") if link_el else ""
                    title       = title_el.inner_text().strip() if title_el else ""
                    company     = comp_el.inner_text().strip()  if comp_el  else ""
                    loc_str     = loc_el.inner_text().strip()   if loc_el   else location
                    posted_date = (time_el.get_attribute("datetime") or "") if time_el else ""

                    m = re.search(r"[/-](\d{7,})", href or "")
                    if not m:
                        continue
                    job_id = m.group(1)
                    if job_id in seen:
                        continue
                    if any(c["job_id"] == job_id for c in candidates):
                        continue

                    # Filter by recency (None = date unknown → keep, don't penalise)
                    days_old = _days_ago(posted_date)
                    if effective_max_days > 0 and days_old is not None and days_old > effective_max_days:
                        logger.debug(f"  Skip (too old, {days_old}d): {title} @ {company}")
                        continue

                    candidates.append({
                        "job_id":      job_id,
                        "title":       title,
                        "company":     company,
                        "location":    loc_str,
                        "url":         href.split("?")[0],
                        "keyword":     keyword,
                        "category":    category,
                        "posted_date": posted_date,
                        "days_old":    days_old if days_old is not None else -1,
                    })
                    seen.add(job_id)
                except Exception as e:
                    logger.debug(f"  Card parse error: {e}")

        # Sort newest-first; -1 (unknown date) goes after confirmed recent jobs
        candidates.sort(key=lambda c: c["days_old"] if c["days_old"] >= 0 else 999)
        logger.info(f"  Total candidates after recency filter: {len(candidates)}")

        # ── Phase 2: fetch full JD for each candidate ──────────────────────────
        jobs: list[dict] = []
        for c in candidates:
            age_label = f"{c['days_old']}d ago" if c["days_old"] >= 0 else "unknown age"
            logger.info(f"  Fetching JD: {c['title']} @ {c['company']} ({age_label})")
            description = ""
            try:
                page.goto(c["url"], timeout=25_000)
                page.wait_for_timeout(3000)
                for sel in [
                    ".show-more-less-html__markup",
                    "#job-details",
                    ".description__text",
                ]:
                    el = page.query_selector(sel)
                    if el:
                        description = el.inner_text().strip()
                        break
            except Exception as e:
                logger.warning(f"  JD fetch failed for {c['job_id']}: {e}")

            jobs.append({**c, "description": description})
            logger.info(f"  ✅ {c['title']} @ {c['company']} (JD: {len(description)} chars)")
            _safe_sleep(1.5, 1)

        browser.close()

    return jobs


# ── Helpers ────────────────────────────────────────────────────────────────────

def _split_by_category(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split jobs into (sde_jobs, ai_jobs).
    Uses the 'category' field written by scrape_with_playwright (preferred),
    falls back to keyword-based detection for jobs scraped by older code.
    """
    ai_kw_set = set(kw.lower() for kw in AI_KEYWORDS)
    sde, ai = [], []
    for j in jobs:
        cat = j.get("category")
        if cat == "ai" or (cat is None and j.get("keyword", "").lower() in ai_kw_set):
            ai.append(j)
        else:
            sde.append(j)
    return sde, ai


# ── Public Entry Point ─────────────────────────────────────────────────────────

def get_new_jobs(
    seen: set[str] | None = None,
    sde_keywords: list[str] | None = None,
    ai_keywords:  list[str] | None = None,
    target_sde:   int | None = None,
    target_ai:    int | None = None,
) -> tuple[list[dict], set[str]]:
    """
    Return (new_jobs, updated_seen_set).
    Implements multi-stage fallback: if primary filters don't yield enough
    SDE or AI jobs, retries with progressively relaxed settings from
    search_config.json → fallback.stages.

    Args:
        seen:         pre-loaded seen job IDs (e.g. from DB). If None, loads from SEEN_JOBS_FILE.
        sde_keywords: per-user SDE keywords override. None = use global defaults.
        ai_keywords:  per-user AI keywords override. None = use global defaults.
        target_sde:   per-user SDE target count override. None = use global default.
        target_ai:    per-user AI target count override. None = use global default.
    """
    if seen is None:
        seen = _load_seen(SEEN_JOBS_FILE)
    logger.info(f"Already seen {len(seen)} jobs. Searching for new ones …")

    _target_sde = target_sde if target_sde is not None else TARGET_SDE_JOBS
    _target_ai  = target_ai  if target_ai  is not None else TARGET_AI_JOBS

    # ── Primary scrape ─────────────────────────────────────────────────────────
    jobs     = scrape_with_playwright(seen, sde_keywords=sde_keywords, ai_keywords=ai_keywords)
    sde, ai  = _split_by_category(jobs)

    logger.info(
        f"Primary: {len(sde)} SDE (need {_target_sde}) + "
        f"{len(ai)} AI (need {_target_ai})"
    )

    # ── Fallback stages ────────────────────────────────────────────────────────
    for stage in FALLBACK_STAGES:
        sde_short = max(0, _target_sde - len(sde))
        ai_short  = max(0, _target_ai  - len(ai))

        if sde_short == 0 and ai_short == 0:
            break  # targets met, no fallback needed

        label   = stage.get("label", "fallback")
        days    = stage.get("max_days_old", 0)
        sde_exp = stage.get("sde_experience_levels") or None
        ai_exp  = stage.get("ai_experience_levels")  or None

        logger.warning(
            f"⚠️  Fallback [{label}]: short {sde_short} SDE + {ai_short} AI — "
            f"retrying (max_days_old={days or '∞'}, "
            f"sde_exp={sde_exp or 'default'}, ai_exp={ai_exp or 'default'})"
        )

        more = scrape_with_playwright(
            seen, max_days_old=days, sde_exp_levels=sde_exp, ai_exp_levels=ai_exp,
            sde_keywords=sde_keywords, ai_keywords=ai_keywords,
        )
        more_sde, more_ai = _split_by_category(more)

        # Only take what we still need
        sde += more_sde[:sde_short]
        ai  += more_ai[:ai_short]

        logger.info(f"  After [{label}]: {len(sde)} SDE + {len(ai)} AI")

    # ── Final summary ──────────────────────────────────────────────────────────
    sde_short = max(0, _target_sde - len(sde))
    ai_short  = max(0, _target_ai  - len(ai))
    if sde_short or ai_short:
        logger.warning(
            f"⚠️  All fallback stages exhausted — "
            f"proceeding with {len(sde)} SDE + {len(ai)} AI "
            f"(short {sde_short} SDE + {ai_short} AI)"
        )

    final = sde[:_target_sde] + ai[:_target_ai]
    logger.info(f"Total selected: {len(final)} jobs ({len(sde[:_target_sde])} SDE + {len(ai[:_target_ai])} AI)")
    return final, seen
