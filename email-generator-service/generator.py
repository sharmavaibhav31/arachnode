"""
generator.py — Email generation pipeline for the Cold Email Generator Service.

Pipeline:
  1. Load job and contact records from PostgreSQL.
  2. Attempt to generate a personalized product observation via Ollama.
  3. If Ollama fails or is unavailable, select a suitable static observation
     from fallbacks.yaml based on keyword matching against job stack/product.
  4. Render the appropriate Jinja2 template.
  5. Return the rendered subject + body strings.
"""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any, Optional

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

import ollama_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    trim_blocks=True,
    lstrip_blocks=True,
)

VALID_TEMPLATES = {"cold_outreach", "recruiter_outreach", "referral_outreach", "followup"}


# ---------------------------------------------------------------------------
# Fallback observation loader
# ---------------------------------------------------------------------------

_fallbacks: Optional[dict] = None


def _load_fallbacks() -> dict:
    global _fallbacks
    if _fallbacks is not None:
        return _fallbacks
    fallback_path = Path(__file__).parent / "fallbacks.yaml"
    with open(fallback_path, "r") as f:
        _fallbacks = yaml.safe_load(f)
    return _fallbacks


def _select_fallback(
    product: Optional[str] = None,
    stack: Optional[list[str]] = None,
) -> str:
    """
    Pick the most relevant static observation from fallbacks.yaml.

    Matches keywords from product description + stack tags against each
    category's keyword list.  Falls back to the 'default' bucket.
    """
    fallbacks = _load_fallbacks()
    combined = " ".join(
        filter(None, [product or "", " ".join(stack or [])])
    ).lower()

    best_category = "default"
    best_score = 0

    for category, data in fallbacks.items():
        if category == "default":
            continue
        keywords: list[str] = data.get("keywords", [])
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_category = category

    obs_list = fallbacks[best_category]["observations"]
    chosen = random.choice(obs_list)
    logger.info(
        "[Fallback] Category='%s' (score=%d) → observation selected.", best_category, best_score
    )
    return chosen


# ---------------------------------------------------------------------------
# Subject parser
# ---------------------------------------------------------------------------

def _split_rendered(rendered: str) -> tuple[str, str]:
    """
    Jinja templates start with 'Subject: ...' on line 1.
    Split into (subject, body) stripping the 'Subject: ' prefix.
    """
    lines = rendered.strip().splitlines()
    subject = ""
    body_lines = []
    in_body = False

    for i, line in enumerate(lines):
        if i == 0 and line.lower().startswith("subject:"):
            subject = line[len("subject:"):].strip()
        elif i == 1 and not in_body:
            # Skip the blank line after Subject
            in_body = True
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return subject, body


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

async def generate_email(
    *,
    template: str,
    job: Any,                  # asyncpg Record or dict-like
    contact: Optional[Any],    # asyncpg Record or None
    your_name: str,
    your_stack: list[str],
    github_url: str,
    graduation_year: Optional[int] = None,
    availability: Optional[str] = None,
    referred_by: Optional[str] = None,
) -> tuple[str, str]:
    """
    Generate a cold email, returning (subject, body).

    Steps:
      1. Try Ollama for personalized product observation.
      2. Fall back to YAML static observation if Ollama fails.
      3. Render with Jinja2.
    """
    if template not in VALID_TEMPLATES:
        raise ValueError(f"Unknown template '{template}'. Choose from: {VALID_TEMPLATES}")

    # ── Product context ──────────────────────────────────────────────────────
    product     = job["product"] if job and job["product"] else ""
    stack_tags  = list(job["stack"] or []) if job and job["stack"] else []
    company     = job["company"] if job else "the company"
    role        = job["role"]    if job else "the role"

    product_context = " ".join(filter(None, [product, *your_stack, *stack_tags]))

    # ── 1. Ollama or fallback ────────────────────────────────────────────────
    observation = None
    if template != "followup":   # followup doesn't need a product observation
        observation = await ollama_client.generate_observation(product_context)
        if not observation:
            observation = _select_fallback(product=product, stack=stack_tags or your_stack)

    # ── 2. Contact fields ────────────────────────────────────────────────────
    contact_name  = None
    contact_email = None
    if contact:
        contact_name  = contact.get("name")
        contact_email = contact.get("email")

    # ── 3. Render ────────────────────────────────────────────────────────────
    tmpl = _jinja_env.get_template(f"{template}.j2")

    ctx: dict[str, Any] = {
        "company":             company,
        "role":                role,
        "your_name":           your_name,
        "your_stack":          your_stack,
        "github_url":          github_url,
        "product_observation": observation or "",
        "contact_name":        contact_name,
        "contact_email":       contact_email,
        "graduation_year":     graduation_year or os.environ.get("GRADUATION_YEAR", "2025"),
        "availability":        availability,
        "referred_by":         referred_by,
    }

    rendered = tmpl.render(**ctx)
    subject, body = _split_rendered(rendered)
    return subject, body
