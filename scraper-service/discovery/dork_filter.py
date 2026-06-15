"""
Lightweight filtering and deduplication for discovered search results.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}


@dataclass(frozen=True)
class RawSearchResult:
    title: str
    url: str
    snippet: str = ""
    query: str = ""


@dataclass(frozen=True)
class DiscoveryCandidate:
    title: str
    url: str
    snippet: str
    query: str
    score: int


@dataclass(frozen=True)
class FilterDecision:
    accepted: bool
    reason: str
    candidate: DiscoveryCandidate | None = None


class UrlDeduplicator:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, url: str) -> bool:
        digest = sha1(url.encode("utf-8")).hexdigest()
        if digest in self._seen:
            return True
        self._seen.add(digest)
        return False


class DiscoveryFilter:
    high_signal_terms = {
        "apply",
        "career",
        "careers",
        "hiring",
        "job",
        "jobs",
        "open role",
        "open roles",
        "position",
        "responsibilities",
    }
    noisy_terms = {
        "course",
        "interview question",
        "salary guide",
        "template",
        "tutorial",
        "webinar",
    }
    blocked_domains = {
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "instagram.com",
        "pinterest.com",
    }

    def __init__(self, min_score: int = 2) -> None:
        self.min_score = min_score
        self.deduper = UrlDeduplicator()

    def evaluate(self, result: RawSearchResult) -> FilterDecision:
        normalized_url = self.normalize_url(result.url)
        if not normalized_url:
            return FilterDecision(False, "missing_url")

        domain = urlsplit(normalized_url).netloc.lower().removeprefix("www.")
        if any(domain == bad or domain.endswith(f".{bad}") for bad in self.blocked_domains):
            return FilterDecision(False, "blocked_domain")

        if self.deduper.seen(normalized_url):
            return FilterDecision(False, "duplicate_url")

        text = f"{result.title} {result.snippet} {normalized_url}".lower()
        if any(term in text for term in self.noisy_terms):
            return FilterDecision(False, "noisy_term")

        score = sum(1 for term in self.high_signal_terms if term in text)
        if score < self.min_score:
            return FilterDecision(False, "low_signal")

        return FilterDecision(
            True,
            "accepted",
            DiscoveryCandidate(
                title=result.title.strip(),
                url=normalized_url,
                snippet=result.snippet.strip(),
                query=result.query,
                score=score,
            ),
        )

    @staticmethod
    def normalize_url(url: str) -> str:
        clean = url.strip()
        if not clean:
            return ""

        parts = urlsplit(clean)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return ""

        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key not in TRACKING_KEYS
            and not any(key.startswith(prefix) for prefix in TRACKING_PREFIXES)
        ]
        normalized_query = urlencode(query, doseq=True)
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme, parts.netloc.lower(), path, normalized_query, ""))
