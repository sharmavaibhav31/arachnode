"""
resume_parser.py

A simple resume parser for the Arachnode email generator.
It reads a PDF or text resume and pulls out the candidate's
skills, experience, and job title using basic regex patterns.

I kept this lightweight on purpose — no heavy NLP libraries,
just straightforward pattern matching that gets the job done.
"""

from __future__ import annotations
import re
import io
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Skills I'm scanning for — covering most common tech stacks
KNOWN_SKILLS = [
    # Programming languages
    "python", "javascript", "typescript", "java", "c++", "c#",
    "go", "rust", "ruby", "php", "swift", "kotlin", "scala",

    # Web frameworks
    "react", "vue", "angular", "nextjs", "html", "css",
    "fastapi", "flask", "django", "express", "nodejs",

    # ML / Data
    "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy",
    "machine learning", "deep learning", "nlp",

    # DevOps and Cloud
    "docker", "kubernetes", "aws", "gcp", "azure", "terraform",
    "linux", "git", "ci/cd", "github actions",

    # Databases
    "postgresql", "mysql", "mongodb", "redis", "sqlite",

    # General
    "rest", "graphql", "microservices", "agile", "scrum",
]

# Ways people write experience in resumes
EXPERIENCE_PATTERNS = [
    r"(\d+)\+?\s*years?\s*of\s*experience",
    r"(\d+)\+?\s*yrs?\s*of\s*experience",
    r"experience\s*of\s*(\d+)\+?\s*years?",
    r"(\d+)\+?\s*years?\s*experience",
    # handles casual phrasing like "worked with X for 2 years"
    r"for\s*(\d+)\+?\s*years?",
    # handles "2+ years in backend development"
    r"(\d+)\+?\s*years?\s*in\s*\w+",
    # handles "over 2 years" or "around 3 years"
    r"(?:over|around|about|nearly)\s*(\d+)\s*years?",
]

# Common job title patterns
TITLE_PATTERNS = [
    r"(?:software|senior|junior|lead|staff|principal)\s+"
    r"(?:engineer|developer|architect|scientist|analyst)",
    r"(?:full[\s-]?stack|backend|frontend|devops|ml|ai|data)\s+"
    r"(?:engineer|developer)",
    r"(?:engineering|product|technical)\s+(?:lead|manager|director)",
]


@dataclass
class CandidateContext:
    """Holds the parsed info we extract from the resume."""
    skills: list[str] = field(default_factory=list)
    years_experience: Optional[int] = None
    recent_role: Optional[str] = None
    resume_preview: str = ""

    def is_empty(self) -> bool:
        """Returns True if we couldn't extract anything useful."""
        return not self.skills and not self.recent_role

    def to_prompt_snippet(self) -> str:
        """
        Converts extracted info into a short string
        that can be injected into the Ollama prompt.
        Keeping it concise so we don't bloat the context window.
        """
        parts = []
        if self.recent_role:
            parts.append(f"Role: {self.recent_role.title()}")
        if self.years_experience:
            parts.append(f"Experience: {self.years_experience}+ years")
        if self.skills:
            # Only pass top 8 skills to keep prompt size manageable
            parts.append(f"Skills: {', '.join(self.skills[:8])}")
        return " | ".join(parts) if parts else ""


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Pull raw text out of a PDF file."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(pages)
    except Exception as exc:
        logger.warning("[ResumeParser] Could not read PDF: %s", exc)
        return ""


def _extract_skills(text: str) -> list[str]:
    """Scan the resume text for known tech skills."""
    text_lower = text.lower()
    found = []
    for skill in KNOWN_SKILLS:
        if skill in text_lower:
            found.append(skill)
    return found


def _extract_experience(text: str) -> Optional[int]:
    """Try to find how many years of experience the candidate has."""
    text_lower = text.lower()
    for pattern in EXPERIENCE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            try:
                return int(match.group(1))
            except (IndexError, ValueError):
                continue
    return None


def _extract_recent_role(text: str) -> Optional[str]:
    """Try to find the candidate's most recent job title."""
    text_lower = text.lower()
    for pattern in TITLE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return match.group(0).strip()
    return None


def parse_resume(
    file_bytes: bytes,
    file_type: str = "pdf"
) -> CandidateContext:
    """
    Main function — takes resume file bytes and returns
    a CandidateContext with everything we could extract.

    Supports PDF and plain text files.
    If extraction fails for any reason, returns an empty
    CandidateContext so the rest of the pipeline still works.
    """

    # Step 1 — get the raw text out of the file
    if file_type == "pdf":
        text = _extract_text_from_pdf(file_bytes)
    else:
        try:
            text = file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

    if not text.strip():
        logger.warning("[ResumeParser] Resume came back empty.")
        return CandidateContext()

    # Step 2 — extract what we need
    skills = _extract_skills(text)
    years = _extract_experience(text)
    role = _extract_recent_role(text)

    # Step 3 — package it up and return
    context = CandidateContext(
        skills=skills,
        years_experience=years,
        recent_role=role,
        resume_preview=text[:300],
    )

    logger.info(
        "[ResumeParser] Done — role: %s | exp: %s yrs | skills found: %s",
        role, years, skills[:5]
    )

    return context