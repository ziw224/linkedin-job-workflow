"""
src/resume_tailor.py – Tailor the HTML resume to a specific JD using local Claude Code CLI.

Uses `claude -p "..."` (Claude Code Max subscription, no API billing).
"""
import logging
import os
import re
import subprocess
import threading
from pathlib import Path

from config.settings import BASE_RESUME_HTML, BASE_RESUME_HTML_AI, AI_ROLE_KEYWORDS, AI_TITLE_KEYWORDS, FS_TITLE_KEYWORDS, OUTPUT_DIR

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/Users/zihanwang/.local/bin/claude"
LLM_MODE = os.getenv("LLM_MODE", "claude").strip().lower()  # claude | codex | openclaw
OPENCLAW_AGENT = os.getenv("OPENCLAW_AGENT", "coding").strip() or "coding"
CODEX_BIN = os.getenv("CODEX_BIN", "/Users/zihanwang/.nvm/versions/node/v22.12.0/bin/codex").strip()
CODEX_MODEL = os.getenv("CODEX_MODEL", "gpt-5.3-codex").strip() or "gpt-5.3-codex"
# Once Claude reports quota limit in this process, skip further Claude calls.
_CLAUDE_LIMIT_HIT = False
_FALLBACK_LOCK = threading.Lock()

PROMPT_TEMPLATE = """You are an ATS optimization specialist making surgical edits to a resume for a specific job.
Role type: {role_type}

YOUR MANDATE: Make the MINIMUM changes needed to align keywords with the JD.
Two resumes for similar JDs should look nearly identical — the output is a lightly edited base resume, NOT a bespoke rewrite.

─── STRICT RULES ───────────────────────────────────────────────────────────────

LOCKED BULLETS — data-lock="1":
  Any <li data-lock="1"> is the headline bullet of that experience. It MUST stay in position 1.
  → Never move it down. Never swap it with another bullet. Never rewrite it from scratch.
  → You may add 1–2 keywords to its wording, but keep the structure intact.

REORDERING (bullets WITHOUT data-lock):
  You may move non-locked bullets ONLY if a lower bullet is a clearly stronger match for
  an explicit requirement in the JD. Limit to ONE swap per role/project. If in doubt, don't move.

KEYWORD WEAVING:
  Weave 2–4 exact JD keywords into existing bullets by substituting synonyms or appending a phrase.
  Maximum 3 wording edits per section. Do NOT rewrite a bullet entirely.

DO NOT CHANGE:
  - Locked bullets' position
  - Section order, headers, education
  - Skills section content or order
  - Any bullet's core meaning

OUTPUT — THIS IS THE MOST IMPORTANT RULE:
  ⚠️  Return ONLY the raw HTML body content, starting with the first <div>.
  ⚠️  NO explanations. NO summaries. NO markdown tables. NO "Here's what I changed".
  ⚠️  NO <html>, <head>, or <body> tags. NO code fences (```).
  If you output anything other than raw HTML, the resume will be corrupted.
  The very first character of your response must be "<".

HTML PRESERVATION:
  - Preserve ALL HTML tags, attributes, data-skills, data-lock, and comments exactly.

─── INPUT ──────────────────────────────────────────────────────────────────────

JOB DESCRIPTION:
{jd}

RESUME BODY HTML:
{resume_body}
"""


def _sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:40].strip("_")


def _inject_locks(html: str) -> str:
    """Add data-lock="1" to the first <li> in each <ul> block.

    This prevents Claude from moving the headline bullet of any experience/project.
    The lock is injected into the body HTML sent to Claude, not the base file.
    """
    def lock_first(m: re.Match) -> str:
        # Replace only the FIRST <li> in this <ul> with a locked version
        return re.sub(r'<li(?![\w\s]*data-lock)', '<li data-lock="1"', m.group(0), count=1)
    return re.sub(r'<ul[^>]*>[\s\S]*?</ul>', lock_first, html)


def _is_ai_role(job: dict) -> bool:
    """Return True if the job is an AI/ML Engineer role.

    Priority order:
    1. If title clearly contains Full Stack / SWE keywords → False (FS resume)
    2. If title clearly contains AI/ML keywords → True (AI resume)
    3. Ambiguous title → scan JD body for AI keywords
    """
    title = job.get("title", "").lower()

    # Step 1: Explicit FS/SWE title → always FS resume
    if any(kw in title for kw in FS_TITLE_KEYWORDS):
        return False

    # Step 2: Explicit AI/ML title → always AI resume
    if any(kw in title for kw in AI_TITLE_KEYWORDS):
        return True

    # Step 3: Ambiguous title (e.g. just "Engineer") → scan JD
    jd = job.get("description", "").lower()
    return any(kw in jd for kw in AI_ROLE_KEYWORDS)


def tailor_resume(job: dict, output_dir: Path | None = None) -> Path | None:
    """
    Generate a tailored HTML resume for the given job dict via Claude CLI.
    Returns path to saved HTML file, or None on failure.
    """
    out_dir = output_dir if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    ai_role = _is_ai_role(job)
    base    = BASE_RESUME_HTML_AI if ai_role else BASE_RESUME_HTML
    full_html = base.read_text(encoding="utf-8")
    role_type = "AI/ML Engineer" if ai_role else "Full Stack/Software Engineer"
    logger.info(f"  Detected role type: {role_type} → using {base.name}")

    # Extract only the <body> content to keep prompt small
    body_match = re.search(r"<body[^>]*>([\s\S]*)</body>", full_html, re.IGNORECASE)
    resume_body = body_match.group(1).strip() if body_match else full_html
    # Also extract the HTML shell (everything up to and including <body>)
    shell_start = full_html[:body_match.start(1)] if body_match else "<body>"
    shell_end   = full_html[body_match.end(1):]   if body_match else "</body></html>"

    jd = job.get("description", "").strip()
    if not jd:
        logger.warning(f"  Job {job['job_id']} has empty description – using title/company as hint.")
        jd = f"Role: {job['title']} at {job['company']}, {job['location']}."

    # Mark first bullet of each experience with data-lock="1" so Claude can't move it
    locked_body = _inject_locks(resume_body)
    prompt = PROMPT_TEMPLATE.format(jd=jd[:6000], resume_body=locked_body, role_type=role_type)

    logger.info(f"  Tailoring ({LLM_MODE}): {job['title']} @ {job['company']} …")

    try:
        global _CLAUDE_LIMIT_HIT
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)

        if LLM_MODE == "openclaw":
            with _FALLBACK_LOCK:
                fb = subprocess.run(
                    [
                        "openclaw", "agent", "--local",
                        "--agent", OPENCLAW_AGENT,
                        "--message", prompt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=360,
                )
            if fb.returncode != 0:
                logger.error(f"  OpenClaw call failed (code {fb.returncode}): {(fb.stderr or '')[:300]}")
                return None
            tailored_html = fb.stdout.strip()
        elif LLM_MODE == "codex":
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tf:
                out_file = tf.name
            try:
                cx = subprocess.run(
                    [
                        CODEX_BIN, "exec",
                        "--model", CODEX_MODEL,
                        "--sandbox", "read-only",
                        "--skip-git-repo-check",
                        "--output-last-message", out_file,
                        "-",
                    ],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=420,
                )
                if cx.returncode != 0:
                    logger.error(f"  Codex call failed (code {cx.returncode}): {(cx.stderr or cx.stdout or '')[:300]}")
                    return None
                tailored_html = Path(out_file).read_text(encoding="utf-8").strip()
            finally:
                try:
                    Path(out_file).unlink(missing_ok=True)
                except Exception:
                    pass
        else:
            if _CLAUDE_LIMIT_HIT:
                logger.error("  Claude quota already hit in this run. Set LLM_MODE=codex to continue.")
                return None
            result = subprocess.run(
                [CLAUDE_BIN, "--dangerously-skip-permissions", "--print"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "")
                if "hit your limit" in err.lower() or "resets" in err.lower():
                    _CLAUDE_LIMIT_HIT = True
                logger.error(f"  Claude CLI failed (code {result.returncode}): {err[:400]}")
                return None
            tailored_html = result.stdout.strip()

    except subprocess.TimeoutExpired:
        logger.error("  Claude CLI timed out.")
        return None
    except Exception as e:
        logger.error(f"  Claude CLI exception: {e}")
        return None

    if not tailored_html:
        logger.error("  Claude returned empty output.")
        return None

    # Strip markdown fences if present
    if "```" in tailored_html:
        m = re.search(r"```(?:html)?\n?([\s\S]+?)```", tailored_html)
        if m:
            tailored_html = m.group(1).strip()

    # Strip any leading explanation text before first HTML tag
    first_tag = re.search(r"<(div|section|header|ul|li|span|p)\b", tailored_html)
    if first_tag and first_tag.start() > 0:
        logger.warning(f"  Claude returned {first_tag.start()} chars of explanation — stripping.")
        tailored_html = tailored_html[first_tag.start():]

    # ── Validate output looks like HTML ──────────────────────────────────────
    # If there's no HTML at all (e.g. Claude returned only a markdown summary),
    # bail out rather than embed plain text inside <body>.
    if not re.search(r"<(div|li|span|ul|section)\b", tailored_html):
        logger.error(
            f"  Claude output doesn't look like HTML (got: {tailored_html[:120]!r}). "
            "Skipping this job."
        )
        return None

    # Re-wrap into full HTML with original shell (preserves CSS)
    tailored_html = shell_start + tailored_html + shell_end

    # Save HTML
    company_slug = _sanitize(job['company'])
    fname        = f"{job['job_id']}_{company_slug}"
    html_path    = out_dir / f"{fname}.html"
    html_path.write_text(tailored_html, encoding="utf-8")
    logger.info(f"  ✅ Saved → {html_path.name}")

    return html_path
