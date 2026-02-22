"""
src/cover_letter.py – Generate cover letter and "Why [Company]" answer via Claude CLI.

Outputs two plain-text files per job:
  - Zihan Wang-CoverLetter-{Company}.txt
  - Zihan Wang-Why{Company}.txt
"""
import logging
import os
import re
import subprocess
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/Users/zihanwang/.local/bin/claude"
# Once Claude reports quota limit in this process, skip further Claude calls.
_CLAUDE_LIMIT_HIT = False

# ── Candidate Background (static context) ─────────────────────────────────────
CANDIDATE_BIO = """
Candidate: Zihan Wang (Bella)
Education: B.S. Computer Science + Mathematics, Lehigh University, May 2025. GPA 3.9/4.0. Dean's List.
Selected Courses: Algorithms, Operating Systems, Machine Learning, NLP, Computer Vision.

Research:
- LUNAR Lab @ Lehigh (Jan 2024 – May 2025): Published NeurIPS 2025 workshop paper on video LLM temporal reasoning ("Video Finetuning Improves Reasoning Between Frames", CogInterp @ NeurIPS 2025).

Work Experience:
- Software Engineering Intern @ Oracle (May–Aug 2024): Extended CBDC scalability using Oracle Blockchain Tables. Added REST endpoint & UI components (Java/Spring, Oracle DB).
- Teaching Assistant @ Lehigh (Jan–May 2025): Graded DSA coursework, held office hours.

Key Projects:
- EcoForge: Full-stack sustainability platform. RAG pipeline with hybrid search + cross-encoder reranking (LangChain, Claude API, PostgreSQL pgvector). Next.js/FastAPI. Context management for long multi-turn sessions.
- MediScheduler: HIPAA-compliant healthcare scheduling app. Firebase Firestore + Cloud Scheduler agentic loop for conflict resolution. Full-stack (React/FastAPI).

Tech Stack: Python, TypeScript, React, Next.js, FastAPI, PostgreSQL, GCP, Firebase, LangChain, Claude API, Playwright, Docker.

Portfolio: zihanwang.dev
LinkedIn: linkedin.com/in/zihanwang
""".strip()


# ── Prompts ────────────────────────────────────────────────────────────────────

COVER_LETTER_PROMPT = """You are an expert career coach writing a cover letter for Zihan Wang.

CANDIDATE BACKGROUND:
{bio}

ROLE: {title} at {company} ({location})

JOB DESCRIPTION:
{jd}

Write a polished, specific cover letter body (3–4 paragraphs, under 320 words total):
- Paragraph 1: Open with genuine enthusiasm for THIS specific company and role. Reference something real about the company's product/mission from the JD.
- Paragraph 2: Highlight 2 of the most relevant experiences/projects from her background that directly map to the JD requirements.
- Paragraph 3: Connect her research or a unique skill to what this company needs. Make it feel non-generic.
- Paragraph 4 (short): Express excitement to contribute, call to action.

Tone: Warm, confident, and specific — not stiff corporate language. Sound like a real person.

IMPORTANT:
- Do NOT include "Dear Hiring Manager" or any header — only the 3–4 paragraph body.
- Do NOT include sign-off / signature lines.
- Plain text only, no markdown, no bullet points.
- Keep it under 320 words.
"""

WHY_COMPANY_PROMPT = """Write a "Why do you want to work at {company}?" answer for Zihan Wang applying for {title}.

CANDIDATE BACKGROUND:
{bio}

JOB DESCRIPTION (read carefully — the answer must stay grounded in THIS specific role):
{jd_excerpt}

Follow this formula STRICTLY — 3–5 sentences total, no more:

SENTENCE 1–2 (Company highlight): Pick ONE specific and concrete thing about {company} that directly relates to THE ACTUAL WORK described in the JD for this {title} role — the specific tech stack, engineering problems, team structure, or product decisions mentioned in the responsibilities/requirements section. Must come from what Zihan will actually DO day-to-day, not the company's overall product or mission. Include a specific detail that shows you actually read the JD. Keep it brief.

SENTENCE 2–3 (Why it matters): Explain WHY that specific thing is meaningful — what real problem does it solve, who does it affect, what's hard about it from an engineering perspective. Go one level deeper than the obvious. Show analytical thinking, not just "it's impressive."

SENTENCE 3–5 (Link to You — MOST IMPORTANT): Connect that company/role strength DIRECTLY to Zihan's growth as a {title}. Be specific: what skill will she develop in THIS role at THIS company that she can't develop elsewhere? What from her background (specific projects, research, internship) makes her genuinely care about THIS engineering problem? Must feel personal and earned — NOT "I'll learn a lot" or "I'm passionate about software."

CRITICAL RULES:
- Stay grounded in what Zihan will ACTUALLY DO in this role — if it's fullstack SWE, talk about fullstack engineering challenges; if it's backend, talk about backend; do NOT bring up AI/ML/research unless the JD explicitly lists them as job responsibilities
- If the company happens to have AI features but the role itself is fullstack/SWE, focus on the SWE engineering work, not the AI product
- No superlatives or generic praise ("best", "leading", "innovative", "cutting-edge")
- No facts everyone knows ("used by millions", "top company", "fast-growing")
- The link-to-you section must name specific projects or experiences from Zihan's background
- Plain text, no markdown, no bullet points
- Output ONLY the answer — no intro phrases, no labels
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run_claude(prompt: str, label: str) -> str | None:
    """Run Claude CLI with fallback to OpenClaw model routing when Claude is unavailable."""
    try:
        global _CLAUDE_LIMIT_HIT
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)

        if _CLAUDE_LIMIT_HIT:
            logger.warning(f"  Claude quota already hit in this run — skipping Claude for {label}.")
            result = None
        else:
            result = subprocess.run(
                [CLAUDE_BIN, "--dangerously-skip-permissions", "--print"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        if result is None or result.returncode != 0:
            if result is not None:
                err_full = (result.stderr or result.stdout or "")
                if "hit your limit" in err_full.lower() or "resets" in err_full.lower():
                    _CLAUDE_LIMIT_HIT = True
                err = err_full[:500]
                logger.error(f"  Claude CLI failed for {label} (code {result.returncode}): {err}")
            logger.warning(f"  Falling back to OpenClaw model routing for {label} ...")
            fb = subprocess.run(
                [
                    "openclaw", "agent", "--local",
                    "--agent", "coding",
                    "--message", prompt,
                ],
                capture_output=True,
                text=True,
                timeout=240,
            )
            if fb.returncode != 0:
                logger.error(f"  OpenClaw fallback failed for {label} (code {fb.returncode}): {(fb.stderr or '')[:300]}")
                return None
            output = fb.stdout.strip()
        else:
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
    today = date.today().strftime("%B %d, %Y")
    company = job.get("company", "")
    title   = job.get("title", "")
    header = f"""{today}

Hiring Team
{company}

Re: {title}

Dear Hiring Manager,

"""
    footer = "\n\nSincerely,\nZihan Wang\nzihan.b.wang@gmail.com | zihanwang.dev | linkedin.com/in/zihanwang\n"
    return header + body + footer


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_cover_letter(job: dict, output_dir: Path) -> dict[str, Path | None]:
    """
    Generate cover letter and "Why [Company]" answer for a job.

    Args:
        job: dict with keys title, company, location, description
        output_dir: directory to save files (same as resume output dir)

    Returns:
        {
            "cover_letter": Path | None,
            "why_company":  Path | None,
        }
    """
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
        bio=CANDIDATE_BIO,
        title=title,
        company=company,
        location=location,
        jd=jd[:5000],
    )
    cl_body = _run_claude(cl_prompt, f"cover_letter:{company}")
    if cl_body:
        full_letter = _format_cover_letter(cl_body, job)
        cl_path = output_dir / f"Zihan Wang-CoverLetter-{company}.txt"
        cl_path.write_text(full_letter, encoding="utf-8")
        logger.info(f"  ✅ Cover letter saved → {cl_path.name}")
        results["cover_letter"] = cl_path
    else:
        logger.warning(f"  ⚠️ Cover letter generation failed for {company}")

    # ── 2. Why [Company] ──────────────────────────────────────────────────────
    logger.info(f"  Generating 'Why {company}' answer …")
    why_prompt = WHY_COMPANY_PROMPT.format(
        company=company,
        title=title,
        bio=CANDIDATE_BIO,
        jd_excerpt=jd[:2500],
    )
    why_text = _run_claude(why_prompt, f"why:{company}")
    if why_text:
        why_path = output_dir / f"Zihan Wang-Why{company_slug}.txt"
        why_path.write_text(why_text, encoding="utf-8")
        logger.info(f"  ✅ Why-{company} saved → {why_path.name}")
        results["why_company"] = why_path
    else:
        logger.warning(f"  ⚠️ Why-company generation failed for {company}")

    return results
