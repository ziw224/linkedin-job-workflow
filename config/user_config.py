"""
config/user_config.py — Per-user paths and config loader.

Each Discord user gets an isolated directory:
  config/users/{discord_user_id}/
    profile.json    ← name, email, linkedin, bio, resume_pdf_prefix
    resume.html     ← SDE / full-stack resume
    resume_ai.html  ← AI/ML resume (optional, falls back to resume.html)

If no user_id is provided (e.g. cron/single-user mode), falls back to the
legacy root-level config/candidate_profile.json + resume/base_resume.html.
"""

from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
USERS_DIR = ROOT / "config" / "users"


def get_user_dir(user_id: str | None) -> Path:
    if user_id:
        d = USERS_DIR / str(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d
    # Legacy single-user fallback
    return ROOT / "config"


def get_user_profile(user_id: str | None) -> dict:
    """Load candidate profile for the given user. Returns empty dict if missing."""
    user_dir = get_user_dir(user_id)

    # New multi-user path
    profile_path = user_dir / "profile.json" if user_id else user_dir / "candidate_profile.json"
    if profile_path.exists():
        with open(profile_path) as f:
            return json.load(f)

    # Fallback: root-level candidate_profile.json
    fallback = ROOT / "config" / "candidate_profile.json"
    if fallback.exists():
        with open(fallback) as f:
            return json.load(f)

    return {}


def get_user_resume_path(user_id: str | None, ai_role: bool = False) -> Path:
    """Return the resume HTML path for this user."""
    if user_id:
        user_dir = get_user_dir(user_id)
        if ai_role:
            ai_path = user_dir / "resume_ai.html"
            if ai_path.exists():
                return ai_path
        resume_path = user_dir / "resume.html"
        if resume_path.exists():
            return resume_path
        # Check env var overrides (user-level)
        env_key = f"RESUME_HTML_PATH_{user_id.upper()}"
        env_val = os.getenv(env_key, "")
        if env_val:
            return Path(env_val).expanduser()

    # Legacy single-user: respect RESUME_HTML_PATH env var or default
    from config.settings import BASE_RESUME_HTML, BASE_RESUME_HTML_AI
    return BASE_RESUME_HTML_AI if (ai_role and BASE_RESUME_HTML_AI.exists()) else BASE_RESUME_HTML


def get_user_output_dir(user_id: str | None) -> Path:
    """Per-user output directory for generated resumes/PDFs."""
    if user_id:
        out = ROOT / "resume" / "output" / str(user_id)
    else:
        out = ROOT / "resume" / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def user_is_ready(user_id: str | None) -> bool:
    """Return True if the user has both a profile and a resume."""
    if not user_id:
        # Single-user mode: check legacy paths
        from config.settings import BASE_RESUME_HTML
        profile = ROOT / "config" / "candidate_profile.json"
        return profile.exists() and BASE_RESUME_HTML.exists()

    user_dir = get_user_dir(user_id)
    return (user_dir / "profile.json").exists() and (user_dir / "resume.html").exists()


def get_resume_pdf_prefix(user_id: str | None) -> str:
    profile = get_user_profile(user_id)
    return profile.get("resume_pdf_prefix", "Resume")
