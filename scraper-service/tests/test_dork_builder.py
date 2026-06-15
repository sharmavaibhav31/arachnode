import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from discovery.dork_builder import DorkBuilder, JobDorkConfig
from discovery.dork_filter import DiscoveryFilter, RawSearchResult


def test_dork_builder_generates_platform_queries():
    config = JobDorkConfig(
        role="backend engineer",
        stack=("Go", "Kubernetes"),
        location="Bangalore",
        year=2026,
        platforms=("notion", "company_careers"),
    )

    queries = DorkBuilder().build(config)

    assert len(queries) == 2
    assert 'site:notion.so "backend engineer" "Go" "Kubernetes" "Bangalore" 2026' in queries[0]
    assert "inurl:careers" in queries[1]


def test_dork_filter_accepts_high_signal_career_result_once():
    result_filter = DiscoveryFilter(min_score=2)
    result = RawSearchResult(
        title="Backend Engineer - Open Roles",
        url="https://careers.example.com/jobs/backend?utm_source=google",
        snippet="We are hiring. Apply for this backend engineer position.",
        query="example query",
    )

    first = result_filter.evaluate(result)
    second = result_filter.evaluate(result)

    assert first.accepted is True
    assert first.candidate is not None
    assert first.candidate.url == "https://careers.example.com/jobs/backend"
    assert second.accepted is False
    assert second.reason == "duplicate_url"


def test_dork_filter_rejects_noisy_result():
    decision = DiscoveryFilter().evaluate(
        RawSearchResult(
            title="Backend engineer interview questions",
            url="https://blog.example.com/backend-interview",
            snippet="A tutorial and salary guide for candidates.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "noisy_term"
