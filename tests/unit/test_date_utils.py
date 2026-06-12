"""
pytest suite for normalize_date().
Run from repo root:
    pytest tests/unit/test_date_utils.py -v

"""

from __future__ import annotations
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "aggregator-service")
)

from utils.date_utils import normalize_date



FAKE_NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def freeze_now(monkeypatch):
    """Patch _utcnow so every relative-date assertion is deterministic."""
    monkeypatch.setattr("utils.date_utils._utcnow", lambda: FAKE_NOW)



# Helper



def utc(year, month, day, hour=0, minute=0, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)



class TestGuardCases:
    def test_none_returns_none(self):

        assert normalize_date(None) is None

    def test_empty_string_returns_none(self):

        assert normalize_date("") is None

    def test_whitespace_only_returns_none(self):

        assert normalize_date("   ") is None



# ISO 8601 strings



class TestISO8601:
    def test_date_only(self):
        assert normalize_date("2024-06-01") == utc(2024, 6, 1)

    def test_datetime_no_tz(self):
        assert normalize_date("2024-06-01T12:30:00") == utc(2024, 6, 1, 12, 30, 0)

    def test_datetime_with_z(self):
        assert normalize_date("2024-06-01T12:30:00Z") == utc(2024, 6, 1, 12, 30, 0)

    def test_datetime_with_positive_offset(self):
      
        result = normalize_date("2024-06-01T18:00:00+05:30")
        assert result == utc(2024, 6, 1, 12, 30, 0)

    def test_datetime_with_negative_offset(self):
        result = normalize_date("2024-06-01T07:00:00-05:00")
        assert result == utc(2024, 6, 1, 12, 0, 0)

    def test_datetime_utc_plus_zero(self):
        assert normalize_date("2024-06-01T12:00:00+00:00") == utc(2024, 6, 1, 12)

    def test_result_is_utc_aware(self):

        result = normalize_date("2024-06-01")
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0



# Unix timestamps



class TestUnixTimestamps:

    TS_SEC = 1_717_200_000
    TS_MS  = 1_717_200_000_000

    def test_integer_seconds(self):
        assert normalize_date(self.TS_SEC) == utc(2024, 6, 1)

    def test_float_seconds(self):
        assert normalize_date(float(self.TS_SEC)) == utc(2024, 6, 1)

    def test_integer_milliseconds(self):
        assert normalize_date(self.TS_MS) == utc(2024, 6, 1)

    def test_string_seconds(self):
        assert normalize_date(str(self.TS_SEC)) == utc(2024, 6, 1)

    def test_string_milliseconds(self):
        assert normalize_date(str(self.TS_MS)) == utc(2024, 6, 1)

    def test_negative_timestamp_returns_none(self):
        assert normalize_date(-1) is None

    def test_implausibly_far_future_returns_none(self):
       
        far_future = int(1_717_200_000 + 200 * 365.25 * 86400)
        assert normalize_date(far_future) is None

    def test_result_is_utc_aware(self):
        result = normalize_date(self.TS_SEC)
        assert result.tzinfo == timezone.utc



# Locale / human-readable strings



class TestLocaleStrings:
    def test_mon_d_year_with_comma(self):
        assert normalize_date("Jun 1, 2024") == utc(2024, 6, 1)

    def test_full_month_d_year_with_comma(self):
        assert normalize_date("June 1, 2024") == utc(2024, 6, 1)

    def test_d_mon_year(self):
        assert normalize_date("01 Jun 2024") == utc(2024, 6, 1)

    def test_d_full_month_year(self):
        assert normalize_date("01 June 2024") == utc(2024, 6, 1)

    def test_full_month_d_year_no_comma(self):
        assert normalize_date("June 1 2024") == utc(2024, 6, 1)

    def test_dmy_dashes(self):
        assert normalize_date("01-06-2024") == utc(2024, 6, 1)

    def test_slash_format_rejected(self, caplog):
       
        result = normalize_date("06/01/2024")
        assert result is None
        assert "will fall back to created_at" in caplog.text

    def test_result_is_utc_aware(self):

        result = normalize_date("Jun 1, 2024")
        assert result.tzinfo == timezone.utc



#  datetime passthrough



class TestDatetimePassthrough:
    def test_naive_datetime_gets_utc_attached(self):
        naive = datetime(2024, 6, 1, 12, 0, 0) 
        result = normalize_date(naive)
        assert result == utc(2024, 6, 1, 12)
        assert result.tzinfo == timezone.utc

    def test_offset_aware_datetime_converted_to_utc(self):
        from datetime import timedelta as td
        ist = timezone(td(hours=5, minutes=30))
        aware = datetime(2024, 6, 1, 17, 30, 0, tzinfo=ist)  
        result = normalize_date(aware)
        assert result == utc(2024, 6, 1, 12)

    def test_utc_datetime_returned_unchanged(self):

        dt = utc(2024, 6, 1, 9, 0, 0)
        assert normalize_date(dt) == dt



# Relative strings



class TestRelativeStrings:
    """All relative assertions are relative to FAKE_NOW = 2024-06-15 12:00:00 UTC."""

    def test_just_now(self):
        assert normalize_date("just now") == FAKE_NOW

    def test_today(self):
        assert normalize_date("today") == FAKE_NOW

    def test_yesterday(self):

        from datetime import timedelta
        assert normalize_date("yesterday") == FAKE_NOW - timedelta(days=1)

    def test_n_seconds_ago(self):

        from datetime import timedelta
        assert normalize_date("30 seconds ago") == FAKE_NOW - timedelta(seconds=30)

    def test_n_minutes_ago(self):
        from datetime import timedelta
        assert normalize_date("5 minutes ago") == FAKE_NOW - timedelta(minutes=5)

    def test_n_hours_ago(self):

        from datetime import timedelta
        assert normalize_date("3 hours ago") == FAKE_NOW - timedelta(hours=3)

    def test_n_days_ago(self):
        from datetime import timedelta
        assert normalize_date("3 days ago") == FAKE_NOW - timedelta(days=3)

    def test_n_weeks_ago(self):

        from datetime import timedelta
        assert normalize_date("2 weeks ago") == FAKE_NOW - timedelta(weeks=2)

    def test_n_months_ago(self):
        
        from datetime import timedelta
        assert normalize_date("1 month ago") == FAKE_NOW - timedelta(days=30)

    def test_singular_day(self):

        from datetime import timedelta
        assert normalize_date("1 day ago") == FAKE_NOW - timedelta(days=1)

    def test_singular_hour(self):
        from datetime import timedelta
        assert normalize_date("1 hour ago") == FAKE_NOW - timedelta(hours=1)

    def test_case_insensitive(self):

        from datetime import timedelta
        assert normalize_date("3 Days Ago") == FAKE_NOW - timedelta(days=3)

    def test_unknown_relative_returns_none(self, caplog):

        result = normalize_date("a while back")
        assert result is None
        assert "will fall back to created_at" in caplog.text



# Malformed / edge-case inputs

class TestMalformedInputs:
    def test_garbage_string_returns_none(self, caplog):

        result = normalize_date("not-a-date-at-all")
        assert result is None
        assert "will fall back to created_at" in caplog.text

    def test_partial_iso_no_day(self, caplog):

        result = normalize_date("2024-06")
        assert result is None

    def test_random_numbers_with_letters(self, caplog):
        result = normalize_date("abc123")
        assert result is None

    def test_unexpected_type_returns_none(self, caplog):

        result = normalize_date({"date": "2024-06-01"})  
        assert result is None
        assert "unexpected type" in caplog.text

    def test_does_not_raise(self):

        """normalize_date must never raise regardless of input."""
        bad_inputs = [object(), [], 9999999999999999999, "∞", b"bytes"]
        for inp in bad_inputs:
            try:
                normalize_date(inp) 
            except Exception as exc:
                pytest.fail(f"normalize_date raised for input {inp!r}: {exc}")



#  Logging behaviour


class TestLogging:
    def test_warning_logged_for_bad_string(self, caplog):

        import logging
        with caplog.at_level(logging.WARNING, logger="date_utils"):
            normalize_date("gibberish")
        assert any("will fall back to created_at" in r.message for r in caplog.records)

    def test_no_log_for_none(self, caplog):
        import logging
        
        with caplog.at_level(logging.WARNING, logger="date_utils"):

            normalize_date(None)
        assert caplog.records == []

    def test_no_log_for_empty_string(self, caplog):

        import logging
        with caplog.at_level(logging.WARNING, logger="date_utils"):
            normalize_date("")
        assert caplog.records == []