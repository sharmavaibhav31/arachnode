"""
intent_parser.py — LLM-based natural language query understanding.

Parses unstructured search prompts and structured user filters into an intent object
containing precise targeted search queries utilizing Google dorking syntax.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a job search strategist. A user has typed a natural language 
job search query. Your job is to extract their intent and generate 
precise search queries to find relevant, recently posted jobs.

Return ONLY a JSON object — no preamble, no explanation, no markdown.

Schema:
{
  "role": "extracted job title",
  "keywords": ["keyword1", "keyword2"],
  "stack": ["Tech1", "Tech2"],
  "location": "city or region or null",
  "company_stage": "seed|series-a|series-b|growth|public|any or null",
  "remote": true or false or null,
  "search_queries": [
    "5 to 8 specific search query strings using Google dork syntax",
    "Include site: operators for specific platforms where relevant",
    "Use quotes for exact phrases",
    "Include year 2026 in at least two queries for freshness",
    "One query per line, diverse strategies"
  ]
}

Rules for search_queries:
- Query 1: broad role + location + year
- Query 2: exact role phrase + key tech + platform site filter
- Query 3: company stage + domain + role
- Query 4: site:jobs.lever.co OR site:boards.greenhouse.io + role + location
- Query 5: site:wellfound.com + role + location
- Query 6: site:cutshort.io + role + tech
- Query 7: "we're hiring" OR "join our team" + role + domain
- Query 8: role + location + "2026" (freshness signal)
"""


async def parse_intent(query: str, filters: Dict[str, Any], llm_client: Any) -> Dict[str, Any]:
    """
    Calls the configured LLM client to parse query intent and build search_queries.
    Falls back to structured keyword heuristic if LLM fails or client is degraded.
    """
    user_prompt = f"""
    User search query: "{query}"
    
    Additional filters provided:
    - Stack: {filters.get('stack', [])}
    - Location: {filters.get('location', '')}
    - Max age: {filters.get('max_age_days', 14)} days
    - Experience: {filters.get('experience_years', '')} years
    - Remote: {filters.get('remote', False)}
    
    Extract intent and generate search queries.
    """

    if getattr(llm_client, "is_degraded", False):
        logger.warning("LLM client is degraded. Using fallback intent parser.")
        return _fallback_intent(query, filters)

    try:
        raw = await llm_client.complete(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=1000,
        )
        
        # Clean markdown code blocks if present
        clean = re.sub(r'```(?:json)?\n?', '', raw).strip()
        # Find JSON object boundaries
        start = clean.find('{')
        end = clean.rfind('}')
        if start != -1 and end != -1:
            clean = clean[start:end+1]

        parsed = json.loads(clean)
        
        # Ensure search_queries is present and valid
        if not isinstance(parsed.get("search_queries"), list) or not parsed["search_queries"]:
            parsed["search_queries"] = _build_default_queries(query, filters)

        return parsed
    except Exception as e:
        logger.warning("LLM intent parsing failed (%s). Falling back to heuristic intent.", e)
        return _fallback_intent(query, filters)


def _fallback_intent(query: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    words = [w for w in query.split() if len(w) > 2]
    return {
        "role": query,
        "keywords": words,
        "stack": filters.get("stack", []),
        "location": filters.get("location"),
        "company_stage": None,
        "remote": filters.get("remote"),
        "search_queries": _build_default_queries(query, filters),
    }


def _build_default_queries(query: str, filters: Dict[str, Any]) -> list[str]:
    loc = f" {filters.get('location')}" if filters.get("location") else ""
    stack_str = " " + " ".join(filters.get("stack", [])) if filters.get("stack") else ""
    
    return [
        f"{query}{loc}{stack_str} jobs 2026",
        f'"{query}"{loc} site:wellfound.com',
        f'{query}{loc} site:jobs.lever.co OR site:boards.greenhouse.io',
        f'site:cutshort.io {query}{stack_str}',
        f'"{query}"{loc} "2026"',
    ]
