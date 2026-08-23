"""
llm_client.py — Provider abstraction for the Job Search Agent.

Supports:
  - ollama (default, free & local)
  - openai (optional)
  - anthropic (optional)

Follows the repository pattern: gracefully handle provider unreachability,
log warnings/errors, and set SEARCH_DEGRADED=True when no LLM provider is available.
Never crash the service because an LLM is unreachable.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "ollama").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

DEFAULT_MODELS = {
    "ollama": os.getenv("AGENT_MODEL", "mistral"),
    "openai": os.getenv("AGENT_MODEL", "gpt-4o-mini"),
    "anthropic": os.getenv("AGENT_MODEL", "claude-haiku-3-5-20241022"),
}


class LLMClient:
    def __init__(self) -> None:
        self.provider: str = AGENT_PROVIDER
        self.model: str = DEFAULT_MODELS.get(self.provider, "mistral")
        self.is_degraded: bool = False
        self._openai_client = None
        self._anthropic_client = None

    async def initialize(self) -> None:
        """Check provider connectivity on startup and set fallback if needed."""
        logger.info("Initializing LLM client with provider '%s' (model: '%s')", self.provider, self.model)
        
        ok = await self._test_provider(self.provider)
        if ok:
            logger.info("Primary LLM provider '%s' is reachable and active.", self.provider)
            return

        if self.provider != "ollama":
            logger.warning("Primary LLM provider '%s' unreachable or unconfigured. Attempting fallback to Ollama...", self.provider)
            ollama_ok = await self._test_provider("ollama")
            if ollama_ok:
                self.provider = "ollama"
                self.model = DEFAULT_MODELS["ollama"]
                logger.info("Successfully fell back to Ollama model '%s'.", self.model)
                return

        logger.error("[LLMClient] Neither primary provider '%s' nor Ollama is reachable. Entering SEARCH_DEGRADED mode.", self.provider)
        self.is_degraded = True

    async def _test_provider(self, provider: str) -> bool:
        if provider == "ollama":
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                    return resp.status_code == 200
            except Exception as e:
                logger.debug("Ollama check failed: %s", e)
                return False

        elif provider == "openai":
            if not OPENAI_API_KEY:
                return False
            try:
                import openai
                self._openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
                return True
            except Exception as e:
                logger.warning("OpenAI client initialization failed: %s", e)
                return False

        elif provider == "anthropic":
            if not ANTHROPIC_API_KEY:
                return False
            try:
                import anthropic
                self._anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
                return True
            except Exception as e:
                logger.warning("Anthropic client initialization failed: %s", e)
                return False

        return False

    async def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        """
        Generates a completion string using the active provider.
        Raises RuntimeError if client is degraded.
        """
        if self.is_degraded:
            raise RuntimeError("LLM client is degraded — skipping LLM completion.")

        if self.provider == "ollama":
            return await self._complete_ollama(system, user, max_tokens)
        elif self.provider == "openai":
            return await self._complete_openai(system, user, max_tokens)
        elif self.provider == "anthropic":
            return await self._complete_anthropic(system, user, max_tokens)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    async def _complete_ollama(self, system: str, user: str, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": self.model,
                    "system": system,
                    "prompt": user,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": 0.2,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()

    async def _complete_openai(self, system: str, user: str, max_tokens: int) -> str:
        if not self._openai_client:
            import openai
            self._openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

        response = await self._openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    async def _complete_anthropic(self, system: str, user: str, max_tokens: int) -> str:
        if not self._anthropic_client:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        response = await self._anthropic_client.messages.create(
            model=self.model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        return response.content[0].text if response.content else ""
