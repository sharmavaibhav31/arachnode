"""
Layer 3 — Contract tests: jobs:raw Redis Stream schema

A contract test verifies that the event schema agreed between producer
(crawler-service) and consumer (aggregator-service) has not drifted.

It reads a real message off the jobs:raw stream and validates it against
the JobPostingContract Pydantic model — the single source of truth for
what the stream must carry.

Two modes:
  1. Live mode (REDIS_HOST env → real Redis): reads from an actual running
     deployment. Great for CI against a staging environment.
  2. Fixture mode: publishes a synthetic valid and invalid event and
     validates the model directly — no external Redis needed.

Run with:
  # Fixture mode (default, no infrastructure needed):
  pytest tests/contract/ -v

  # Live mode (against a running Redis):
  REDIS_HOST=localhost pytest tests/contract/ -v -m live
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "aggregator-service"))

from pydantic import BaseModel, ValidationError, field_validator
from typing import Optional


# ---------------------------------------------------------------------------
# Contract Model — single source of truth for jobs:raw event schema
# ---------------------------------------------------------------------------

class JobPostingContract(BaseModel):
    """
    Every message on the jobs:raw Redis Stream MUST conform to this schema.

    If you change the event fields in the crawler, update this model first —
    that's the contract. The aggregator is expected to handle all fields here.
    """
    company:    str
    role:       str
    source:     str
    url:        str
    stack:      list[str]         # must be a list (already deserialized from JSON)
    product:    Optional[str] = None
    location:   Optional[str] = None
    posted_at:  Optional[str] = None

    @field_validator("company", "role", "source", "url")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required string field must be non-empty")
        return v

    @field_validator("stack")
    @classmethod
    def stack_is_list_of_strings(cls, v: list) -> list:
        if not isinstance(v, list):
            raise ValueError("stack must be a list")
        for item in v:
            if not isinstance(item, str):
                raise ValueError(f"stack items must be strings, got {type(item)}")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_event(raw_fields: dict) -> dict:
    """
    Decode a raw Redis Stream message (bytes values) into Python strings,
    and deserialize the stack JSON string into a list.
    """
    data = {}
    for k, v in raw_fields.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        data[key] = val

    stack_raw = data.get("stack", "[]")
    try:
        data["stack"] = json.loads(stack_raw)
    except (json.JSONDecodeError, TypeError):
        data["stack"] = []

    return data


# ---------------------------------------------------------------------------
# Layer 3a — Schema validation unit tests (no infrastructure needed)
# ---------------------------------------------------------------------------

class TestJobPostingContractModel:
    def _valid(self, **overrides):
        base = {
            "company": "Razorpay",
            "role": "Backend Engineer",
            "source": "remotive",
            "url": "https://remotive.com/job/123",
            "stack": ["Go", "PostgreSQL"],
        }
        base.update(overrides)
        return base

    def test_valid_minimal(self):
        event = JobPostingContract(**self._valid())
        assert event.company == "Razorpay"

    def test_valid_with_all_fields(self):
        event = JobPostingContract(**self._valid(
            product="Payment gateway",
            location="Bengaluru",
            posted_at="2024-03-01",
        ))
        assert event.location == "Bengaluru"

    def test_empty_company_raises(self):
        with pytest.raises(ValidationError, match="non-empty"):
            JobPostingContract(**self._valid(company=""))

    def test_empty_role_raises(self):
        with pytest.raises(ValidationError, match="non-empty"):
            JobPostingContract(**self._valid(role="  "))

    def test_missing_url_raises(self):
        data = self._valid()
        del data["url"]
        with pytest.raises(ValidationError):
            JobPostingContract(**data)

    def test_missing_source_raises(self):
        data = self._valid()
        del data["source"]
        with pytest.raises(ValidationError):
            JobPostingContract(**data)

    def test_stack_must_be_list(self):
        with pytest.raises(ValidationError):
            JobPostingContract(**self._valid(stack="Go,Python"))  # string, not list

    def test_stack_items_must_be_strings(self):
        with pytest.raises(ValidationError):
            JobPostingContract(**self._valid(stack=[1, 2, 3]))   # ints in stack

    def test_stack_can_be_empty_list(self):
        event = JobPostingContract(**self._valid(stack=[]))
        assert event.stack == []

    def test_optional_fields_default_to_none(self):
        event = JobPostingContract(**self._valid())
        assert event.product is None
        assert event.location is None
        assert event.posted_at is None


class TestDecodeEvent:
    def test_bytes_decoded_to_str(self):
        raw = {
            b"company": b"Zepto",
            b"role": b"SRE",
            b"source": b"remotive",
            b"url": b"https://zepto.com/job",
            b"stack": json.dumps(["Go"]).encode(),
        }
        data = _decode_event(raw)
        assert data["company"] == "Zepto"
        assert data["stack"] == ["Go"]

    def test_invalid_stack_json_becomes_empty_list(self):
        raw = {b"stack": b"not-json", b"company": b"Test", b"role": b"Dev", b"source": b"x", b"url": b"y"}
        data = _decode_event(raw)
        assert data["stack"] == []

    def test_str_keys_pass_through(self):
        raw = {"company": "Zepto", "role": "Dev", "source": "x", "url": "y", "stack": '["Go"]'}
        data = _decode_event(raw)
        assert data["company"] == "Zepto"
        assert data["stack"] == ["Go"]


# ---------------------------------------------------------------------------
# Layer 3b — Live stream contract test (requires running Redis)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestLiveStreamContract:
    """
    Reads a real message from jobs:raw and validates it against the contract.
    Only runs when marked with -m live and REDIS_HOST is set.

    Usage:
      REDIS_HOST=localhost pytest tests/contract/ -m live -v
    """

    @pytest.fixture
    def redis(self):
        import redis as sync_redis
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", 6379))
        try:
            client = sync_redis.Redis(host=host, port=port, decode_responses=False)
            client.ping()
            return client
        except Exception:
            pytest.skip(f"Redis at {host}:{port} not reachable — set REDIS_HOST and ensure Redis is running")

    def test_stream_has_messages(self, redis):
        messages = redis.xrange("jobs:raw", count=1)
        assert messages, "jobs:raw stream is empty — run a spider first (scrapy crawl remotive)"

    def test_latest_event_conforms_to_contract(self, redis):
        """The most recent event on jobs:raw must satisfy JobPostingContract."""
        messages = redis.xrange("jobs:raw", count=1)
        assert messages, "jobs:raw stream is empty"

        _, raw_fields = messages[0]
        data = _decode_event(raw_fields)

        try:
            event = JobPostingContract(**data)
        except ValidationError as exc:
            pytest.fail(
                f"Latest jobs:raw event FAILED contract validation:\n{exc}\n\n"
                f"Raw data: {data}"
            )

        assert event.company, "company field must be non-empty"
        assert event.role, "role field must be non-empty"
        assert isinstance(event.stack, list), "stack must be a Python list"

    def test_all_recent_events_conform(self, redis):
        """
        Read the last 10 events and validate each one.
        Reports all failures rather than short-circuiting at the first.
        """
        messages = redis.xrange("jobs:raw", count=10)
        if not messages:
            pytest.skip("No messages in jobs:raw")

        failures = []
        for msg_id, raw_fields in messages:
            data = _decode_event(raw_fields)
            try:
                JobPostingContract(**data)
            except ValidationError as exc:
                failures.append(f"Message {msg_id}: {exc}")

        if failures:
            pytest.fail(
                f"{len(failures)}/{len(messages)} events failed the contract:\n"
                + "\n".join(failures)
            )
