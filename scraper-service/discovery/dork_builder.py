"""
Configurable Google dork query generation for high-signal job discovery.

The builder intentionally stays small: it creates a bounded list of search
queries from role, stack, location, platform, and optional date constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


DEFAULT_PLATFORMS: tuple[str, ...] = (
    "company_careers",
    "notion",
    "github",
    "linkedin_jobs",
    "greenhouse",
    "lever",
)


@dataclass(frozen=True)
class JobDorkConfig:
    role: str
    stack: tuple[str, ...] = field(default_factory=tuple)
    location: str | None = None
    year: int | None = None
    after: date | None = None
    platforms: tuple[str, ...] = DEFAULT_PLATFORMS
    max_queries: int = 12


def _quote(value: str) -> str:
    clean = " ".join(value.strip().split())
    return f'"{clean}"'


def _or_group(values: list[str]) -> str:
    return "(" + " OR ".join(_quote(value) for value in values if value.strip()) + ")"


class DorkBuilder:
    """
    Builds Google search queries without hardcoding feature-specific strings
    in scraper code.
    """

    hiring_terms = ["hiring", "we are hiring", "open roles", "careers", "jobs"]

    def build(self, config: JobDorkConfig) -> list[str]:
        role = _quote(config.role)
        stack_terms = " ".join(_quote(term) for term in config.stack if term.strip())
        location = _quote(config.location) if config.location else ""
        year = str(config.year) if config.year else ""
        after = f"after:{config.after.isoformat()}" if config.after else ""

        context = " ".join(
            part for part in (role, stack_terms, location, year, after) if part
        )

        templates = {
            "company_careers": (
                'inurl:careers ("open roles" OR jobs OR hiring) {context}'
            ),
            "notion": (
                'site:notion.so {context} {hiring_terms}'
            ),
            "github": (
                'site:github.com {context} {hiring_terms}'
            ),
            "linkedin_jobs": (
                'site:linkedin.com/jobs {context}'
            ),
            "greenhouse": (
                'site:greenhouse.io {context}'
            ),
            "lever": (
                'site:jobs.lever.co {context}'
            ),
        }

        queries: list[str] = []
        seen: set[str] = set()
        hiring_terms = _or_group(self.hiring_terms)

        for platform in config.platforms:
            template = templates.get(platform)
            if not template:
                continue

            query = " ".join(
                template.format(context=context, hiring_terms=hiring_terms).split()
            )
            if query and query not in seen:
                queries.append(query)
                seen.add(query)

            if len(queries) >= config.max_queries:
                break

        return queries
