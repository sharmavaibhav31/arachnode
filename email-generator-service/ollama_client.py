"""
ollama_client.py — Async client for a locally running Ollama server.

The service calls the Ollama REST API to generate a single personalized
observation sentence about a company's product for use in cold emails.

If Ollama is unreachable (service not running, timeout), this module returns
None and the caller falls back to static observations from fallbacks.yaml.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PREFERRED_MODELS = ["mistral", "llama3", "llama2"]
_TIMEOUT = 10   # seconds


_SYSTEM_PROMPT = (
    "You are a professional software engineer writing a cold email for a job application. "
    "Write exactly ONE sentence — no more, no less — that is specific, genuine, "
    "and technically credible about the company's product. "
    "Do NOT start with 'I' or use filler phrases like 'I noticed' or 'I found'. "
    "Output only the sentence, nothing else."
)


async def _detect_available_model(client: httpx.AsyncClient) -> Optional[str]:
    """Return the first available model from PREFERRED_MODELS, or None."""
    try:
        resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code == 200:
            available = {m["name"].split(":")[0] for m in resp.json().get("models", [])}
            for model in PREFERRED_MODELS:
                if model in available:
                    return model
    except Exception:
        logger.warning(
            "[Ollama] Could not reach Ollama at %s. "
            "Is Ollama installed and running? Install it from https://ollama.com",
            OLLAMA_BASE_URL,
        )
    return None


async def generate_observation(product_description: str) -> Optional[str]:
    """
    Ask Ollama to write one specific sentence about the company's product.

    Returns the generated sentence string, or None on any failure.
    The caller should substitute a static fallback when None is returned.
    """
    if not product_description or not product_description.strip():
        return None

    prompt = (
        f"In one sentence, write something specific and impressive about this company's "
        f"product that a software engineer would say in a cold email: {product_description}"
    )

    async with httpx.AsyncClient() as client:
        model = await _detect_available_model(client)
        if model is None:
            logger.warning(
                "[Ollama] No models available. Run 'ollama pull mistral' to install one, "
                "or visit https://ollama.com to set up Ollama. Falling back to static observations."
            )
            return None

        logger.info("[Ollama] Using model '%s' for observation generation.", model)
        try:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model":  model,
                    "prompt": prompt,
                    "system": _SYSTEM_PROMPT,
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
            # Strip any trailing newlines / quotation marks the model might add
            observation = observation.strip(' "\n')
            if observation:
                logger.info("[Ollama] Generated: %s", observation[:100])
                return observation
        except httpx.TimeoutException:
            logger.warning("[Ollama] Request timed out after %ds.", _TIMEOUT)
        except httpx.HTTPStatusError as exc:
            logger.warning("[Ollama] HTTP error %s.", exc.response.status_code)
        except Exception as exc:
            logger.warning("[Ollama] Unexpected error: %s", exc)

    return None
