"""
relevance_scorer.py — Deterministic relevance scoring engine.

Calculates a relevance score from 0.0 to 1.0 based on intent keywords, tech stack overlap,
location match, and company stage match. Uses simple, explainable string matching.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def score(job: Dict[str, Any], intent: Dict[str, Any]) -> float:
    """
    Score relevance of a job posting against parsed intent.

    Score breakdown:
      - Role keyword match: 0.4
      - Tech stack overlap: 0.3
      - Location match:     0.2
      - Company stage:      0.1
    """
    role_text = str(job.get("role", "")).lower()
    company_text = str(job.get("company", "")).lower()
    search_query = str(job.get("search_query", "")).lower()

    # 1. Role Score (0.4)
    target_role = str(intent.get("role", "")).lower()
    keywords = [k.lower() for k in intent.get("keywords", []) if k]
    if target_role and target_role in role_text:
        role_score = 0.4
    elif keywords and any(kw in role_text for kw in keywords):
        role_score = 0.4
    elif any(kw in company_text or kw in search_query for kw in keywords):
        role_score = 0.2
    else:
        role_score = 0.0

    # 2. Stack Score (0.3)
    target_stack = [s.lower() for s in intent.get("stack", []) if s]
    job_stack = [s.lower() for s in job.get("stack", [])]
    
    if target_stack:
        matching_tags = 0
        for tag in target_stack:
            if tag in job_stack or tag in role_text or tag in search_query:
                matching_tags += 1
        stack_score = 0.3 * (matching_tags / max(len(target_stack), 1))
    else:
        stack_score = 0.3  # no specific stack requested -> full stack points

    # 3. Location Score (0.2)
    target_location = str(intent.get("location") or "").lower()
    job_location = str(job.get("location") or "").lower()
    is_remote = intent.get("remote")

    if not target_location and not is_remote:
        location_score = 0.2
    elif target_location and (target_location in job_location or target_location in role_text):
        location_score = 0.2
    elif is_remote and ("remote" in job_location or "remote" in role_text):
        location_score = 0.2
    elif target_location and not job_location:
        location_score = 0.1  # unknown location fallback
    else:
        location_score = 0.0

    # 4. Stage Score (0.1)
    target_stage = str(intent.get("company_stage") or "").lower()
    if not target_stage or target_stage == "any" or target_stage == "null":
        stage_score = 0.1
    elif target_stage in company_text or target_stage in role_text or target_stage in search_query:
        stage_score = 0.1
    else:
        stage_score = 0.0

    total = role_score + stack_score + location_score + stage_score
    return round(min(1.0, max(0.0, total)), 2)
