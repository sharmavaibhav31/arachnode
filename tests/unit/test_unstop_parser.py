"""
tests/unit/test_unstop_parser.py

Unit tests for the Unstop card parser (_parse_card).
Uses real text content observed from Unstop listing pages (May 2026).
No network calls, no Playwright, no Docker needed.
"""
import os
import sys

# Add scraper-service to path (pattern matches existing unit tests)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "scraper-service"),
)

from scrapers.unstop import _parse_card

# ── Fixtures: real text observed from Unstop listings (May 2026) ─────────────

_JOB_IN_OFFICE = (
    "Accounts Executive Star Samarth International 1 - 3 years Full Time "
    "In Office | Gurgaon Accounts Executive Accounting Experienced Professionals "
    "Fresher 20 K - 25 K/Month Prize Icon Posted May 16, 2026 12 days left"
)
_JOB_IN_OFFICE_HREF = "/jobs/accounts-executive-star-samarth-international-1687225"

_INTERNSHIP_WFH = (
    "React.js Developer Internship Pragma Consulting No prior experience required "
    "Full Time Work from Home React.js Developer Internship Software Development "
    "Frontend Development Engineering Students +2 8 K - 12 K/Month Prize Icon "
    "Posted May 16, 2026 12 days left"
)
_INTERNSHIP_WFH_HREF = "/internships/reactjs-developer-internship-pragma-consulting-1687267"

_INTERNSHIP_NO_SALARY = (
    "MERN Stack Developer Internship Octalbees No prior experience required "
    "Part Time Work from Home MERN Stack Developer Internship Software Development "
    "Full Stack Development Engineering Students +3 Posted May 16, 2026 12 days left"
)
_INTERNSHIP_NO_SALARY_HREF = "/internships/mern-stack-developer-internship-octalbees-1687260"

_JOB_MULTI_CITY = (
    "HVAC Systems Sales Manager Beijer Ref India Private Limited 4 - 8 years "
    "Full Time In Office | Mumbai, Chennai, Chandigarh HVAC Systems Sales Manager "
    "B2B Sales Account Management Experienced Professionals 40 K - 70 K/Month "
    "Prize Icon Posted May 16, 2026 5 days left"
)
_JOB_MULTI_CITY_HREF = (
    "/jobs/hvac-systems-sales-manager-beijer-ref-india-private-limited-1687104"
)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestParseCardSchema:
    """Every valid card must produce the required 8-field aggregator schema."""

    def test_all_required_keys_present(self):
        result = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert result is not None
        for key in ("company", "role", "source", "url", "stack", "product",
                    "location", "posted_at"):
            assert key in result, f"Missing key: {key}"

    def test_source_is_unstop(self):
        result = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert result["source"] == "unstop"

    def test_url_is_absolute(self):
        result = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert result["url"].startswith("https://unstop.com")

    def test_stack_is_list(self):
        result = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert isinstance(result["stack"], list)


class TestRoleCompanySplit:
    """Role and company are correctly split using the tag-repetition strategy."""

    def test_job_role(self):
        r = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert "Accounts Executive" in r["role"]

    def test_job_company(self):
        r = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert "Star Samarth International" in r["company"]

    def test_internship_role(self):
        r = _parse_card(_INTERNSHIP_WFH_HREF, _INTERNSHIP_WFH)
        assert "React.js Developer Internship" in r["role"]

    def test_internship_company(self):
        r = _parse_card(_INTERNSHIP_WFH_HREF, _INTERNSHIP_WFH)
        assert "Pragma Consulting" in r["company"]


class TestLocation:
    """Location is extracted for in-office roles, None for WFH."""

    def test_in_office_has_location(self):
        r = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert r["location"] == "Gurgaon"

    def test_wfh_has_no_location(self):
        r = _parse_card(_INTERNSHIP_WFH_HREF, _INTERNSHIP_WFH)
        assert r["location"] is None

    def test_multi_city_location(self):
        r = _parse_card(_JOB_MULTI_CITY_HREF, _JOB_MULTI_CITY)
        assert r["location"] is not None
        assert "Mumbai" in r["location"]


class TestSalary:
    """Salary/stipend goes into the product field."""

    def test_salary_extracted(self):
        r = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert r["product"] is not None
        assert "20 K" in r["product"]

    def test_internship_stipend(self):
        r = _parse_card(_INTERNSHIP_WFH_HREF, _INTERNSHIP_WFH)
        assert r["product"] is not None
        assert "8 K" in r["product"]

    def test_no_salary_is_none(self):
        r = _parse_card(_INTERNSHIP_NO_SALARY_HREF, _INTERNSHIP_NO_SALARY)
        assert r["product"] is None


class TestStack:
    """Stack tags include job_type, work_mode, and opportunity type."""

    def test_job_type_in_stack(self):
        r = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert any("Time" in t for t in r["stack"])

    def test_internship_tag_in_stack(self):
        r = _parse_card(_INTERNSHIP_WFH_HREF, _INTERNSHIP_WFH)
        assert "internship" in r["stack"]

    def test_job_tag_in_stack(self):
        r = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert "job" in r["stack"]

    def test_work_from_home_in_stack(self):
        r = _parse_card(_INTERNSHIP_WFH_HREF, _INTERNSHIP_WFH)
        assert "Work from Home" in r["stack"]


class TestPostedAt:
    def test_posted_at_extracted(self):
        r = _parse_card(_JOB_IN_OFFICE_HREF, _JOB_IN_OFFICE)
        assert r["posted_at"] == "May 16, 2026"


class TestEdgeCases:
    def test_empty_text_returns_none(self):
        assert _parse_card("/jobs/something-123", "") is None

    def test_no_exp_marker_returns_none(self):
        assert _parse_card("/jobs/something-123", "Just a title Posted May 2026") is None

    def test_relative_href_becomes_absolute(self):
        r = _parse_card("/jobs/some-role-company-99999", _JOB_IN_OFFICE)
        assert r["url"] == "https://unstop.com/jobs/some-role-company-99999"