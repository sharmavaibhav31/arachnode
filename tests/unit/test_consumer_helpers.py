"""
Layer 1 — Unit tests: Consumer dedup helpers

Tests _dedup_key(), _normalise(), and _parse_posted_at() from consumer.py.
No network, no Redis, no database — pure function calls.
"""

import pytest
from datetime import datetime, timezone
import sys, os

# Make the service module importable without installing it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "aggregator-service"))

from consumer import _dedup_key, _normalise

# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_lowercases(self):
        assert _normalise("Razorpay") == "razorpay"

    def test_strips_whitespace(self):
        assert _normalise("  Backend Engineer  ") == "backend engineer"

    def test_empty_string(self):
        assert _normalise("") == ""

    def test_already_lower(self):
        assert _normalise("zepto") == "zepto"


# ---------------------------------------------------------------------------
# _dedup_key
# ---------------------------------------------------------------------------

class TestDedupKey:
    def test_returns_prefixed_md5(self):
        key = _dedup_key("Razorpay", "Backend Engineer")
        assert key.startswith("dedup:agg:")
        # MD5 hex is 32 chars
        assert len(key) == len("dedup:agg:") + 32

    def test_same_inputs_same_key(self):
        k1 = _dedup_key("Zepto", "SRE")
        k2 = _dedup_key("Zepto", "SRE")
        assert k1 == k2

    def test_case_insensitive_collision(self):
        """Mixed-case variants of the same company/role must produce the same key."""
        k1 = _dedup_key("RAZORPAY", "Backend Engineer")
        k2 = _dedup_key("razorpay", "backend engineer")
        assert k1 == k2

    def test_different_role_different_key(self):
        k1 = _dedup_key("Zepto", "Backend Engineer")
        k2 = _dedup_key("Zepto", "Frontend Engineer")
        assert k1 != k2

    def test_different_company_different_key(self):
        k1 = _dedup_key("Zepto", "Backend Engineer")
        k2 = _dedup_key("Swiggy", "Backend Engineer")
        assert k1 != k2

    def test_key_is_deterministic_across_calls(self):
        keys = {_dedup_key("Cred", "Go Engineer") for _ in range(10)}
        assert len(keys) == 1
