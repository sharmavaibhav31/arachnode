"""
Layer 1 — Unit tests: Aggregator Pydantic models

Tests JobOut, StatusUpdate, and StatsOut validation from models.py.
No network, no database.
"""

import sys, os
import pytest
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "aggregator-service"))

from pydantic import ValidationError
from models import JobOut, StatusUpdate, StatsOut


# ---------------------------------------------------------------------------
# StatusUpdate validator
# ---------------------------------------------------------------------------

class TestStatusUpdate:
    def test_valid_new(self):
        s = StatusUpdate(status="new")
        assert s.status == "new"

    def test_valid_applied(self):
        assert StatusUpdate(status="applied").status == "applied"

    def test_valid_ignored(self):
        assert StatusUpdate(status="ignored").status == "ignored"

    def test_invalid_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            StatusUpdate(status="pending")
        assert "status must be one of" in str(exc_info.value)

    def test_empty_raises(self):
        with pytest.raises(ValidationError):
            StatusUpdate(status="")


# ---------------------------------------------------------------------------
# JobOut schema
# ---------------------------------------------------------------------------

class TestJobOut:
    def _base(self, **overrides):
        return {
            "id": uuid4(),
            "company": "Razorpay",
            "role": "Backend Engineer",
            "status": "new",
            "created_at": datetime.now(timezone.utc),
            **overrides,
        }

    def test_minimal_valid(self):
        job = JobOut(**self._base())
        assert job.company == "Razorpay"
        assert job.stack is None
        assert job.source is None

    def test_optional_fields_accepted(self):
        job = JobOut(**self._base(
            stack=["Go", "Kubernetes"],
            source="remotive",
            url="https://example.com/job/123",
            location="Bengaluru",
        ))
        assert job.stack == ["Go", "Kubernetes"]
        assert job.location == "Bengaluru"

    def test_missing_company_raises(self):
        data = self._base()
        del data["company"]
        with pytest.raises(ValidationError):
            JobOut(**data)

    def test_missing_role_raises(self):
        data = self._base()
        del data["role"]
        with pytest.raises(ValidationError):
            JobOut(**data)


# ---------------------------------------------------------------------------
# StatsOut schema
# ---------------------------------------------------------------------------

class TestStatsOut:
    def test_valid(self):
        s = StatsOut(by_source={"remotive": 4, "naukri": 2}, by_status={"new": 5, "applied": 1})
        assert s.by_source["remotive"] == 4

    def test_empty_dicts_valid(self):
        s = StatsOut(by_source={}, by_status={})
        assert s.by_source == {}

    def test_missing_key_raises(self):
        with pytest.raises(ValidationError):
            StatsOut(by_source={"remotive": 1})  # by_status missing
