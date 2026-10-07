"""
classifier.py — Contact classification logic based on LinkedIn Position field.
"""

from __future__ import annotations

import re
from typing import Optional

HR_KEYWORDS = [
    "talent acquisition", "recruiter", "hr", "human resource", "hiring",
    "people ops", "people partner", "talent partner", "staffing",
    "recruitment", "talent management", "human resources"
]

LEADERSHIP_KEYWORDS = [
    "founder", "ceo", "cto", "coo", "co-founder", "president",
    "vp of", "vice president", "director", "head of"
]

TECHNICAL_KEYWORDS = [
    "engineer", "developer", "architect", "sde", "swe", "programmer",
    "backend", "frontend", "fullstack", "devops", "data", "ml", "ai",
    "software", "technical", "tech lead", "staff engineer",
    "principal", "member of technical staff"
]


def _matches_any(position_lower: str, keywords: list[str]) -> bool:
    for kw in keywords:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, position_lower):
            return True
    return False


def classify_position(position: Optional[str]) -> str:
    """
    Classify a connection position into hr, leadership, technical, other, or unknown.
    Priority order: hr > leadership > technical > other
    """
    if not position or not position.strip():
        return "unknown"

    pos_lower = position.strip().lower()

    if _matches_any(pos_lower, HR_KEYWORDS):
        return "hr"
    if _matches_any(pos_lower, LEADERSHIP_KEYWORDS):
        return "leadership"
    if _matches_any(pos_lower, TECHNICAL_KEYWORDS):
        return "technical"

    return "other"
