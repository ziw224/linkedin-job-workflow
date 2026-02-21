"""
src/cover_letter.py – Generate cover letter and "Why [Company]" answer via Claude CLI.

Outputs two plain-text files per job:
  - {Name}-CoverLetter-{Company}.txt
  - {Name}-Why{Company}.txt
"""
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Project root ───────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


# ── Auto-detect Claude CLI binary ─────────────────────────────────────────────
def _find_claude_bin() -> str:
    """Return the path to the Claude CLI binary, or raise if not found."""
    # 1. Already on PATH
    found = shutil.which("claude")
    if found:
        return found
    # 2. Common install locations
    for candidate in [
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "Claude CLI not found. Install it from https://docs.anthropic.com/en/docs/claude-code "
        "and make sure it's on your PATH."
    )

CLAUDE_BIN = _find_claude_bin()


# ── Load candidate profile ─────────────────────────────────────────────────────
def _load_profile() -> dict:
    profile_path = _PROJECT_ROOT / "config" / "candidate_profile.json"
    if not profile_path.exists():
        raise FileNotFoundError(
            f"Candidate profile not found at {profile_path}.\n"
            "Copy config/candidate_profile.example.json → config/candidate_profile.json "
            "and fill in your details."
        )
    with open(profile_path, encoding="utf-8") as f:
        return json.load(f)

_PROFILE = _load_profile()
CANDIDATE_BIO   = _PROFILE.get("bio", "").strip()
CANDIDATE_NAME  = _PROFILE.get("name", "Candidate")
CANDIDATE_EMAIL = _PROFILE.get("email", "")
CANDIDATE_PORTFOLIO = _PROFILE.get("portfolio", "")
CANDIDATE_LINKEDIN  = _PROFILE.get("linkedin", "")


# ── Prompts ────────────────────────────────────────────────────────────────────

COVER_LETTER_PROMPT = """You are an expert career coach writing a cover letter for {candidate_name}.

CANDIDATE BACKGROUND:
{bio}

ROLE: {title} at {company} ({location})

JOB DESCRIPTION:
{jd}

Write a polished, specific cover letter body (3–4 paragraphs, under 320 words total):
- Paragraph 1: Open with genuine enthusiasm for THIS specific company and role. Reference something real about the company's product/mission from the JD.
- Paragraph 2: Highlight 2 of the most relevant experiences/projects from the candidate's background that directly map to the JD requirements.
- Paragraph 3: Connect their research or a unique skill to what this company needs. Make it feel non-generic.
- Paragraph 4 (short): Express excitement to contribute, call to action.

Tone: Warm, confident, and specific — not stiff corporate language. Sound like a real person.

IMPORTANT:
- Do NOT include "Dear Hiring Manager" or any header — only the 3–4 paragraph body.
- Do NOT include sign-off / signature lines.
- Plain text only, no markdown, no bullet points.
- Keep it under 320 words.
"""

WHY_COMPANY_PROMPT = """Write a "Why do you want to work at {company}?" answer for {candidate_name} applying for {title}.

CANDIDATE BACKGROUND:
{bio}

JOB DESCRIPTION (read carefully — the answer must stay grounded in THIS specific role):
{jd_excerpt}

Follow this formula STRICTLY — 3–5 sentences total, no more:

SENTENCE 1–2 (Company highlight): Pick ONE specific and concrete thing about {company} that directly relates to THE ACTUAL WORK described in the JD for this {title} role — the specific tech stack, engineering problems, team structure, or product decisions mentioned in the responsibilities/requirements section. Must come from what the candidate will actually DO day-to-day, not the company's overall product or mission. Include a specific detail that shows you actually read the JD. Keep it brief.

SENTENCE 2–3 (Why it matters): Explain WHY that specific thing is meaningful — what real problem does it solve, who does it affect, what's hard about it from an engineering perspective. Go one level deeper than the obvious. Show analytical thinking, not just "it's impressive."

SENTENCE 3–5 (Link to You — MOST IMPORTANT): Connect that company/role strength DIRECTLY to the candidate's growth as a {title}. Be specific: what skill will they develop in THIS role at THIS company that they can't develop elsewhere? What from their background (specific projects, research, internship) makes them genuinely care about THIS engineering problem? Must feel personal and earned — NOT "I'll learn a lot" or "I'm passionate about software."

CRITICAL RULES:
- Stay grounded in what the candidate will ACTUALLY DO in this role — if it's fullstack SWE, talk about fullstack engineering challenges; if it's backend, talk about backend; do NOT bring up AI/ML/research unless the JD explicitly lists them as job responsibilities
- If the company happens to have AI features but the role itself is fullstack/SWE, focus on the SWE engineering work, not the AI product
- No superlatives or generic praise ("best", "leading", "innovative", "cutting-edge")
- No facts everyone knows ("used by millions", "top company", "fast-growing")
- The link-to-you section must name specific projects or experiences from the candidate's background
- Plain text, no markdown, no bullet points
- Output ONLY the answer — no intro phrases, no labels
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run_claude(prompt: str, label: str) -> str | None:
    """Run Claude CLI with prompt via stdin. Returns output text or None on failure."""
    try:
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        result = subprocess.run(
            [CLAUDE_BIN, "--dangerously-skip-permissions", "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
        if result.returncode != 0:
            logger.error(f"  Claude CLI failed for {label} (code {result.returncode}): {result.stderr[:300]}")
            return None
        output = result.stdout.strip()
        if not output:
            logger.error(f"  Claude returned empty output for {label}")
            return None

        # Strip common preamble phrases Claude sometimes adds
        for preamble in [
            "Here's the answer:",
            "Here's the cover letter:",
            "Here's the cover letter body:",
            "Here is the answer:",
            "Here is the cover letter:",
        ]:
            if output.startswith(preamble):
                output = output[len(preamble):].strip()

        return output
    except subprocess.TimeoutExpired:
        logger.error(f"  Claude CLI timed out for {label}")
        return None
    except Exception as e:
        logger.error(f"  Claude CLI exception for {label}: {e}")
        return None


def _sanitize_company(name: str) -> str:
    """Remove special chars for filenames."""
    return re.sub(r"[^a-zA-Z0-9]", "", name)


def _format_cover_letter(body: str, job: dict) -> str:
    """Wrap the Claude-generated body with a proper header and sign-off."""
    today   = date.today().strftime("%B %d, %Y")
    company = job.get("company", "")
    title   = job.get("title", "")
    contact_parts = [p for p in [CANDIDATE_EMAIL, CANDIDATE_PORTFOLIO, CANDIDATE_LINKEDIN] if p]
    contact_line  = " | ".join(contact_parts)
    header = f"""{today}

Hiring Team
{company}

Re: {title}

Dear Hiring Manager,

"""
    footer = f"\n\nSincerely,\n{CANDIDATE_NAME}\n{contact_line}\n"
    return header + body + footer


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_cover_letter(job: dict, output_dir: Path,
                          bio: str | None = None,
                          candidate_name: str | None = None) -> dict[str, Path | None]:
    """
    Generate cover letter and "Why [Company]" answer for a job.

    Args:
        job: dict with keys title, company, location, description
        output_dir: directory to save files (same as resume output dir)
        bio: candidate bio string (overrides module-level CANDIDATE_BIO)
        candidate_name: candidate name (overrides module-level CANDIDATE_NAME)

    Returns:
        {
            "cover_letter": Path | None,
            "why_company":  Path | None,
        }
    """
    # Allow per-user overrides
    _bio  = bio           if bio           is not None else CANDIDATE_BIO
    _name = candidate_name if candidate_name is not None else CANDIDATE_NAME
    company   = job.get("company", "Company")
    title     = job.get("title", "Software Engineer")
    location  = job.get("location", "")
    jd        = job.get("description", "").strip()

    if not jd:
        jd = f"Role: {title} at {company}, {location}."

    company_slug = _sanitize_company(company)
    results: dict[str, Path | None] = {"cover_letter": None, "why_company": None}

    # ── 1. Cover Letter ────────────────────────────────────────────────────────
    logger.info(f"  Generating cover letter for {title} @ {company} …")
    cl_prompt = COVER_LETTER_PROMPT.format(
        candidate_name=_name,
        bio=_bio,
        title=title,
        company=company,
        location=location,
        jd=jd[:5000],
    )
    cl_body = _run_claude(cl_prompt, f"cover_letter:{company}")
    if cl_body:
        full_letter = _format_cover_letter(cl_body, job)
        cl_path = output_dir / f"{_name}-CoverLetter-{company}.txt"
        cl_path.write_text(full_letter, encoding="utf-8")
        logger.info(f"  ✅ Cover letter saved → {cl_path.name}")
        results["cover_letter"] = cl_path
    else:
        logger.warning(f"  ⚠️ Cover letter generation failed for {company}")

    # ── 2. Why [Company] ──────────────────────────────────────────────────────
    logger.info(f"  Generating 'Why {company}' answer …")
    why_prompt = WHY_COMPANY_PROMPT.format(
        candidate_name=_name,
        company=company,
        title=title,
        bio=_bio,
        jd_excerpt=jd[:2500],
    )
    why_text = _run_claude(why_prompt, f"why:{company}")
    if why_text:
        why_path = output_dir / f"{_name}-Why{company_slug}.txt"
        why_path.write_text(why_text, encoding="utf-8")
        logger.info(f"  ✅ Why-{company} saved → {why_path.name}")
        results["why_company"] = why_path
    else:
        logger.warning(f"  ⚠️ Why-company generation failed for {company}")

    return results
