"""
discovery.py — Core contact discovery pipeline.

Pipeline stages:
  1. domain_inference      company name  →  domain string
  2. email_pattern         domain        →  pattern string (e.g. '{first}.{last}@acme.com')
  3. name_discovery        company + roles → [{name, role, source}]
  4. email_construction    names + pattern → [email strings]
  5. smtp_verification     emails         → [{email, verified}]

All public data sources only. No login, no paid APIs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional — raises rate limit to 5000/hr
_GH_HEADERS: dict[str, str] = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if _GITHUB_TOKEN:
    _GH_HEADERS["Authorization"] = f"Bearer {_GITHUB_TOKEN}"

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
}

# ---------------------------------------------------------------------------
# Stage 1 — Domain Inference
# ---------------------------------------------------------------------------

async def domain_inference(company: str, client: httpx.AsyncClient) -> Optional[str]:
    """
    Infer the company's primary email domain.

    Strategy (tried in order):
      A. Clearbit Autocomplete (free, no auth) — most reliable.
      B. Direct probe of {slug}.com / {slug}.io / {slug}.co.in.
    """
    slug = re.sub(r"[^a-z0-9]+", "", company.lower())

    # A. Clearbit autocomplete
    try:
        url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={quote_plus(company)}"
        resp = await client.get(url, timeout=8)
        resp.raise_for_status()
        suggestions = resp.json()
        if suggestions and isinstance(suggestions, list):
            domain = suggestions[0].get("domain")
            if domain:
                logger.info("[Domain] Clearbit suggests: %s → %s", company, domain)
                return domain
    except Exception as exc:
        logger.debug("[Domain] Clearbit lookup failed: %s", exc)

    # B. Direct probe
    for suffix in ("com", "io", "co.in", "in"):
        candidate = f"{slug}.{suffix}"
        try:
            resp = await client.get(
                f"https://{candidate}", timeout=5, follow_redirects=True
            )
            if resp.status_code < 400:
                logger.info("[Domain] Direct probe succeeded: %s", candidate)
                return candidate
        except Exception:
            continue

    logger.warning("[Domain] Could not infer domain for company: %s", company)
    return None


# ---------------------------------------------------------------------------
# Stage 2 — Email Pattern Detection
# ---------------------------------------------------------------------------

_PATTERN_REGEXES = [
    # First.Last@domain  or  first.last@domain
    (re.compile(r"^([a-z]+)\.([a-z]+)@"), "{first}.{last}@{domain}"),
    # flast@domain (first initial + last name)
    (re.compile(r"^([a-z])([a-z]{3,})@"), "{fi}{last}@{domain}"),
    # firstl@domain (first name + last initial)
    (re.compile(r"^([a-z]{3,})([a-z])@"), "{first}{li}@{domain}"),
    # first@domain
    (re.compile(r"^([a-z]{3,})@"), "{first}@{domain}"),
]


def _infer_pattern_from_email(email: str, domain: str) -> Optional[str]:
    local = email.split("@")[0].lower()
    for regex, template in _PATTERN_REGEXES:
        if regex.match(local + "@"):
            return template.replace("{domain}", domain)
    return None


async def email_pattern_detection(
    domain: str, client: httpx.AsyncClient
) -> Optional[str]:
    """
    Detect the email pattern for *domain* by mining GitHub commit emails.

    Tries:
      1. Search GitHub for repositories whose push email contains the domain.
      2. GitHub org members' public emails (if the org name can be guessed).
    """
    org_slug = domain.split(".")[0]  # e.g. 'razorpay' from 'razorpay.com'
    found_emails: list[str] = []

    # 1. GitHub code search — commits exposing email with this domain
    try:
        search_url = (
            "https://api.github.com/search/commits"
            f"?q={quote_plus(domain)}+committer-email:{domain}&per_page=10"
        )
        resp = await client.get(search_url, headers=_GH_HEADERS, timeout=10)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            for item in items:
                commit = item.get("commit", {})
                for role in ("author", "committer"):
                    email = commit.get(role, {}).get("email", "")
                    if f"@{domain}" in email and "noreply" not in email:
                        found_emails.append(email)
    except Exception as exc:
        logger.debug("[Pattern] GitHub commit search failed: %s", exc)

    # 2. GitHub org members — check public emails
    if not found_emails:
        try:
            members_url = f"https://api.github.com/orgs/{org_slug}/members?per_page=10"
            resp = await client.get(members_url, headers=_GH_HEADERS, timeout=8)
            if resp.status_code == 200:
                members = resp.json()
                for member in members[:5]:
                    user_url = f"https://api.github.com/users/{member['login']}"
                    uresp = await client.get(user_url, headers=_GH_HEADERS, timeout=5)
                    if uresp.status_code == 200:
                        email = uresp.json().get("email") or ""
                        if f"@{domain}" in email:
                            found_emails.append(email)
        except Exception as exc:
            logger.debug("[Pattern] GitHub org member lookup failed: %s", exc)

    # Deduplicate and vote on most common pattern
    pattern_votes: dict[str, int] = {}
    for email in found_emails:
        p = _infer_pattern_from_email(email, domain)
        if p:
            pattern_votes[p] = pattern_votes.get(p, 0) + 1

    if pattern_votes:
        best = max(pattern_votes, key=lambda k: pattern_votes[k])
        logger.info("[Pattern] Detected pattern for %s: %s", domain, best)
        return best

    # Fallback — most common Western enterprise pattern
    fallback = f"{{first}}.{{last}}@{domain}"
    logger.info("[Pattern] No pattern detected for %s — using fallback: %s", domain, fallback)
    return fallback


# ---------------------------------------------------------------------------
# Stage 3 — Name Discovery
# ---------------------------------------------------------------------------

async def _github_org_names(org_slug: str, client: httpx.AsyncClient) -> list[dict]:
    """Pull public member display names from the GitHub org."""
    results = []
    try:
        url = f"https://api.github.com/orgs/{org_slug}/members?per_page=30"
        resp = await client.get(url, headers=_GH_HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        members = resp.json()

        tasks = [
            client.get(
                f"https://api.github.com/users/{m['login']}",
                headers=_GH_HEADERS,
                timeout=5,
            )
            for m in members[:20]   # cap to avoid burning rate limit
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for r in responses:
            if isinstance(r, Exception):
                continue
            data = r.json()
            name = data.get("name") or ""
            bio  = data.get("bio")  or ""
            if name:
                results.append({
                    "name":   name.strip(),
                    "role":   _guess_role_from_bio(bio),
                    "source": "github",
                })
    except Exception as exc:
        logger.debug("[Names] GitHub org names failed: %s", exc)
    return results


def _guess_role_from_bio(bio: str) -> str:
    bio_lower = bio.lower()
    for keyword in ("engineer", "developer", "sre", "devops", "backend", "frontend"):
        if keyword in bio_lower:
            return "Engineer"
    for keyword in ("recruit", "talent", "hr", "people"):
        if keyword in bio_lower:
            return "Recruiter"
    return "Unknown"


async def _linkedin_public_names(
    company: str, roles: list[str]
) -> list[dict]:
    """
    Extract visible names from LinkedIn's public directory search.

    Uses Playwright to render the page; exits gracefully if blocked.
    We only read publicly visible names — no login or session tokens.
    """
    results = []
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=_HTTP_HEADERS["User-Agent"],
                locale="en-IN",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            for role in roles[:2]:   # limit to 2 roles to be polite
                query_role = quote_plus(role)
                query_co   = quote_plus(company)
                url = (
                    f"https://www.linkedin.com/pub/dir/"
                    f"?keywords={query_role}&company={query_co}"
                )
                logger.info("[Names] LinkedIn public dir: %s", url)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)

                    if "/authwall" in page.url or "/login" in page.url:
                        logger.warning("[Names] LinkedIn returned authwall — skipping.")
                        break

                    # ── Selector notes (last verified March 2026) ────────────
                    # Name card:   li.result-card  or  div.base-search-card
                    # Name text:   span.actor-name  or  span.name
                    # Subtitle:    p.subline-level-1  (title / company)
                    # ────────────────────────────────────────────────────────
                    try:
                        await page.wait_for_selector(
                            "li.result-card, div.base-search-card", timeout=10_000
                        )
                    except PWTimeout:
                        logger.debug("[Names] No LinkedIn cards found for role=%s", role)
                        continue

                    cards = await page.query_selector_all(
                        "li.result-card, div.base-search-card"
                    )
                    for card in cards[:15]:
                        name_el = await card.query_selector(
                            "span.actor-name, span.name, h3.base-search-card__title"
                        )
                        sub_el  = await card.query_selector(
                            "p.subline-level-1, h4.base-search-card__subtitle"
                        )
                        if not name_el:
                            continue
                        name     = (await name_el.inner_text()).strip()
                        subtitle = (await sub_el.inner_text()).strip() if sub_el else ""
                        if name and "LinkedIn" not in name:
                            results.append({
                                "name":   name,
                                "role":   subtitle or role,
                                "source": "linkedin",
                            })

                    await asyncio.sleep(2)   # polite delay between role queries

                except Exception as exc:
                    logger.debug("[Names] LinkedIn page error for role=%s: %s", role, exc)
                    continue

            await browser.close()
    except ImportError:
        logger.warning("[Names] Playwright not available — skipping LinkedIn name discovery.")
    except Exception as exc:
        logger.exception("[Names] LinkedIn discovery error: %s", exc)

    return results


async def name_discovery(
    company: str, domain: str, roles: list[str], client: httpx.AsyncClient
) -> list[dict[str, Any]]:
    """Discover employee names from GitHub org and LinkedIn public search."""
    org_slug = domain.split(".")[0]

    gh_names, li_names = await asyncio.gather(
        _github_org_names(org_slug, client),
        _linkedin_public_names(company, roles),
        return_exceptions=True,
    )

    all_names: list[dict] = []
    for result in (gh_names, li_names):
        if isinstance(result, list):
            all_names.extend(result)

    # Deduplicate by name (case-insensitive)
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in all_names:
        key = entry["name"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(entry)

    logger.info("[Names] Discovered %d unique names for %s", len(unique), company)
    return unique


# ---------------------------------------------------------------------------
# Stage 4 — Email Construction
# ---------------------------------------------------------------------------

def _name_parts(name: str) -> tuple[str, str, str, str]:
    """Return (first, last, fi, li) from a display name."""
    parts = name.strip().lower().split()
    first = parts[0] if parts else ""
    last  = parts[-1] if len(parts) > 1 else ""
    fi    = first[:1]
    li    = last[:1]
    return first, last, fi, li


def construct_email(name: str, pattern: str) -> Optional[str]:
    """
    Apply an email pattern template to a person's display name.

    Supported placeholders: {first}, {last}, {fi}, {li}
    Example: '{first}.{last}@acme.com' + 'Alice Smith' → 'alice.smith@acme.com'
    """
    first, last, fi, li = _name_parts(name)
    if not first:
        return None
    try:
        email = pattern.format(first=first, last=last, fi=fi, li=li)
        # Strip any leftover placeholder braces (e.g. if last is empty)
        if "{" in email or not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            return None
        return email
    except (KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Stage 5 — Full pipeline orchestration
# ---------------------------------------------------------------------------

async def run_pipeline(
    company: str,
    roles: list[str],
    provided_domain: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Run the full contact discovery pipeline and return a list of contact dicts.
    Each dict has: name, role, source, email, verified, domain, company.
    """
    from verifier import verify_email

    async with httpx.AsyncClient(
        headers=_HTTP_HEADERS,
        follow_redirects=True,
    ) as client:
        # 1. Domain
        domain = provided_domain or await domain_inference(company, client)
        if not domain:
            logger.error("[Pipeline] No domain found for '%s' — aborting.", company)
            return []

        # 2. Email pattern
        pattern = await email_pattern_detection(domain, client)

        # 3. Names  (concurrent)
        names = await name_discovery(company, domain, roles, client)
        if not names:
            logger.warning("[Pipeline] No names found for %s.", company)

        # 4. Construct emails
        contacts: list[dict[str, Any]] = []
        for person in names:
            email = construct_email(person["name"], pattern) if pattern else None
            contacts.append({
                "company":  company,
                "domain":   domain,
                "name":     person["name"],
                "role":     person.get("role"),
                "source":   person.get("source"),
                "email":    email,
                "verified": "unverified",
            })

        # 5. SMTP verify (non-aggressive — honours per-domain rate limit)
        verify_tasks = [
            verify_email(c["email"]) if c["email"] else asyncio.sleep(0)
            for c in contacts
        ]
        verification_results = await asyncio.gather(*verify_tasks, return_exceptions=True)
        for contact, result in zip(contacts, verification_results):
            if isinstance(result, str):
                contact["verified"] = result

        logger.info(
            "[Pipeline] Done for '%s': %d contacts found.", company, len(contacts)
        )
        return contacts
