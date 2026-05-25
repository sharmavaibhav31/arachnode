"""
ollama_client.py — Async client for a locally running Ollama server.

The service calls the Ollama REST API to generate a personalized
observation sentence about a company's product for use in cold emails.

If candidate context is provided (from a parsed resume), the prompt
is enriched so the generated sentence connects the candidate's
background to the company's product — making the email feel personal.

If Ollama is unreachable, this module returns None and the caller
falls back to static observations from fallbacks.yaml.
"""

from __future__ import annotations
import logging
import os
from typing import Optional

import httpx

# I'm importing CandidateContext here so we can optionally
# enrich the prompt with resume info when it's available
from resume_parser import CandidateContext

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PREFERRED_MODELS = ["mistral", "llama3", "llama2"]
_TIMEOUT = 10  # seconds

# Default system prompt — used when no resume is provided
# Same as before so existing /generate flows are not affected
_SYSTEM_PROMPT = (
    "You are a professional software engineer writing a cold email "
    "for a job application. "
    "Write exactly ONE sentence — no more, no less — that is specific, "
    "genuine, and technically credible about the company's product. "
    "Do NOT start with 'I' or use filler phrases like 'I noticed' "
    "or 'I found'. "
    "Output only the sentence, nothing else."
)

# Enhanced system prompt — used when resume context is available
# This tells Ollama to connect the candidate's background
# to the company's product in one sentence
_PERSONALIZED_SYSTEM_PROMPT = (
    "You are a professional software engineer writing a cold email "
    "for a job application. "
    "Write exactly ONE sentence — no more, no less — that connects "
    "the candidate's background to the company's product. "
    "Make it specific, genuine, and technically credible. "
    "Do NOT start with 'I' or use filler phrases. "
    "Output only the sentence, nothing else."
)


async def _detect_available_model(
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Return the first available model from PREFERRED_MODELS, or None."""
    try:
        resp = await client.get(
            f"{OLLAMA_BASE_URL}/api/tags", timeout=3
        )
        if resp.status_code == 200:
            available = {
                m["name"].split(":")[0]
                for m in resp.json().get("models", [])
            }
            for model in PREFERRED_MODELS:
                if model in available:
                    return model
    except Exception:
        pass
    return None


async def generate_observation(
    product_description: str,
    candidate_context: Optional[CandidateContext] = None,
) -> Optional[str]:
    """
    Ask Ollama to write one specific sentence about the company's product.

    If candidate_context is provided and not empty, the prompt is
    enriched with the candidate's skills, experience, and role so
    the output feels personal rather than generic.

    If candidate_context is None or empty, behavior is exactly the
    same as before — so existing flows keep working unchanged.

    Returns the generated sentence, or None on any failure.
    """

    if not product_description or not product_description.strip():
        return None

    # Check if we have useful resume info to work with
    has_candidate_info = (
        candidate_context is not None
        and not candidate_context.is_empty()
    )

    if has_candidate_info:
        # Build an enriched prompt that mentions the candidate
        candidate_snippet = candidate_context.to_prompt_snippet()
        prompt = (
            f"Candidate background: {candidate_snippet}. "
            f"In one sentence, write something specific about how this "
            f"candidate's background connects to this company's product "
            f"in a cold email: {product_description}"
        )
        system_prompt = _PERSONALIZED_SYSTEM_PROMPT
        logger.info(
            "[Ollama] Using personalized prompt with candidate context."
        )
    else:
        # Fall back to original behavior — no resume provided
        prompt = (
            f"In one sentence, write something specific and impressive "
            f"about this company's product that a software engineer "
            f"would say in a cold email: {product_description}"
        )
        system_prompt = _SYSTEM_PROMPT
        logger.info(
            "[Ollama] No candidate context — using default prompt."
        )

    async with httpx.AsyncClient() as client:
        model = await _detect_available_model(client)
        if model is None:
            logger.info(
                "[Ollama] No models available or Ollama not running."
            )
            return None

        logger.info(
            "[Ollama] Using model '%s' for observation generation.", model
        )

        try:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "system": system_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.4,
                        "num_predict": 80,
                    },
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            observation = data.get("response", "").strip()

            # Clean up any trailing newlines or quotes the model adds
            observation = observation.strip(' "\n')

            if observation:
                logger.info(
                    "[Ollama] Generated: %s", observation[:100]
                )
                return observation

        except httpx.TimeoutException:
            logger.warning(
                "[Ollama] Request timed out after %ds.", _TIMEOUT
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[Ollama] HTTP error %s.", exc.response.status_code
            )
        except Exception as exc:
            logger.warning("[Ollama] Unexpected error: %s", exc)

    return None
