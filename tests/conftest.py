"""
Shared pytest configuration for the jobCrawler test suite.
"""
import pytest


def pytest_configure(config):
    """Register custom markers so -m live works without warnings."""
    config.addinivalue_line("markers", "live: mark test as requiring real infrastructure (Redis/Postgres)")


def pytest_collection_modifyitems(config, items):
    """
    Skip 'live' tests unless -m live is explicitly passed.
    This means 'pytest tests/' always runs clean without a running Redis.
    """
    if "live" not in (config.getoption("-m", default="") or ""):
        skip_live = pytest.mark.skip(reason="Live tests skipped — pass -m live to run")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
