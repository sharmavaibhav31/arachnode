"""
Layer 1 — Unit tests: Email generator (Jinja2 templates + helpers)

Tests _split_rendered(), _select_fallback(), and full Jinja2 template
rendering with known inputs.  No Ollama, no DB, no network.
"""

import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "email-generator-service"))

from generator import _split_rendered, _select_fallback, VALID_TEMPLATES, _jinja_env


# ---------------------------------------------------------------------------
# _split_rendered — subject/body parser
# ---------------------------------------------------------------------------

class TestSplitRendered:
    def test_extracts_subject(self):
        raw = "Subject: Hello World\n\nThis is the body."
        subject, body = _split_rendered(raw)
        assert subject == "Hello World"

    def test_extracts_body(self):
        raw = "Subject: Hello World\n\nLine 1\nLine 2"
        subject, body = _split_rendered(raw)
        assert "Line 1" in body
        assert "Line 2" in body

    def test_subject_prefix_stripped(self):
        raw = "Subject: Backend Engineer interest — Aditya\n\nDear Alice,"
        subject, _ = _split_rendered(raw)
        assert not subject.startswith("Subject:")

    def test_no_leading_blank_in_body(self):
        raw = "Subject: Test\n\nHello"
        _, body = _split_rendered(raw)
        assert not body.startswith("\n")

    def test_multiline_body(self):
        raw = "Subject: X\n\nPara 1\n\nPara 2"
        _, body = _split_rendered(raw)
        assert "Para 1" in body
        assert "Para 2" in body


# ---------------------------------------------------------------------------
# _select_fallback — category matching
# ---------------------------------------------------------------------------

class TestSelectFallback:
    def test_returns_string(self):
        obs = _select_fallback(product="payment gateway", stack=["Python"])
        assert isinstance(obs, str)
        assert len(obs) > 10

    def test_fintech_keywords_match(self):
        # Should not raise; pick a fintech observation
        obs = _select_fallback(product="digital payments UPI transactions", stack=["Go"])
        assert len(obs) > 5

    def test_devtools_keywords(self):
        obs = _select_fallback(product="developer platform API tooling", stack=["TypeScript"])
        assert obs  # non-empty

    def test_no_context_uses_default(self):
        obs = _select_fallback(product=None, stack=None)
        assert isinstance(obs, str)

    def test_empty_strings_use_default(self):
        obs = _select_fallback(product="", stack=[])
        assert isinstance(obs, str)


# ---------------------------------------------------------------------------
# Cold outreach template — Jinja2 rendering
# ---------------------------------------------------------------------------

def _render(template_name: str, **ctx) -> tuple[str, str]:
    """Render a template and split into (subject, body)."""
    tmpl = _jinja_env.get_template(f"{template_name}.j2")
    rendered = tmpl.render(**ctx)
    return _split_rendered(rendered)


_DEFAULT_CTX = dict(
    company="Razorpay",
    role="Backend Engineer",
    your_name="Aditya Kumar",
    your_stack=["Go", "Kubernetes"],
    github_url="https://github.com/aditya",
    product_observation="Their payment infra handles 5M txns/day",
    contact_name=None,
    contact_email=None,
    graduation_year="2025",
    availability=None,
    referred_by="Priya Menon",
)


class TestColdOutreachTemplate:
    def test_subject_contains_role(self):
        subject, _ = _render("cold_outreach", **_DEFAULT_CTX)
        assert "Backend Engineer" in subject

    def test_subject_contains_name(self):
        subject, _ = _render("cold_outreach", **_DEFAULT_CTX)
        assert "Aditya Kumar" in subject

    def test_body_mentions_company(self):
        _, body = _render("cold_outreach", **_DEFAULT_CTX)
        assert "Razorpay" in body

    def test_body_contains_product_observation(self):
        _, body = _render("cold_outreach", **_DEFAULT_CTX)
        assert "5M txns/day" in body

    def test_body_contains_github_url(self):
        _, body = _render("cold_outreach", **_DEFAULT_CTX)
        assert "https://github.com/aditya" in body

    def test_body_word_count_under_160(self):
        _, body = _render("cold_outreach", **_DEFAULT_CTX)
        assert len(body.split()) < 160, "Email body exceeds 160 words — keep it tight"

    def test_stack_tags_in_body(self):
        _, body = _render("cold_outreach", **_DEFAULT_CTX)
        assert "Go" in body or "Kubernetes" in body

    def test_no_unfilled_jinja_tags_in_output(self):
        subject, body = _render("cold_outreach", **_DEFAULT_CTX)
        full = subject + body
        assert "{{" not in full and "}}" not in full

    def test_contact_name_used_when_provided(self):
        ctx = {**_DEFAULT_CTX, "contact_name": "Alice Smith"}
        _, body = _render("cold_outreach", **ctx)
        assert "Alice" in body

    def test_falls_back_to_there_when_no_contact(self):
        _, body = _render("cold_outreach", **{**_DEFAULT_CTX, "contact_name": None})
        assert "there" in body.lower()


class TestRecruiterOutreachTemplate:
    def test_subject_contains_role(self):
        subject, _ = _render("recruiter_outreach", **_DEFAULT_CTX)
        assert "Backend Engineer" in subject or "Razorpay" in subject

    def test_body_non_empty(self):
        _, body = _render("recruiter_outreach", **_DEFAULT_CTX)
        assert len(body) > 20

    def test_no_jinja_artifacts(self):
        subject, body = _render("recruiter_outreach", **_DEFAULT_CTX)
        assert "{{" not in subject + body


class TestReferralOutreachTemplate:
    def test_subject_contains_role_and_company(self):
        subject, _ = _render("referral_outreach", **_DEFAULT_CTX)
        assert "Backend Engineer" in subject
        assert "Razorpay" in subject

    def test_opening_mentions_referrer(self):
        _, body = _render("referral_outreach", **_DEFAULT_CTX)
        assert "Priya Menon" in body

    def test_body_contains_product_observation(self):
        _, body = _render("referral_outreach", **_DEFAULT_CTX)
        assert "5M txns/day" in body

    def test_no_jinja_artifacts(self):
        subject, body = _render("referral_outreach", **_DEFAULT_CTX)
        assert "{{" not in subject + body

    def test_falls_back_to_mutual_connection_when_no_referrer(self):
        _, body = _render("referral_outreach", **{**_DEFAULT_CTX, "referred_by": None})
        assert "mutual connection" in body.lower()


class TestFollowupTemplate:
    def test_body_non_empty(self):
        ctx = {**_DEFAULT_CTX, "product_observation": ""}
        _, body = _render("followup", **ctx)
        assert len(body) > 20

    def test_no_jinja_artifacts(self):
        subject, body = _render("followup", **_DEFAULT_CTX)
        assert "{{" not in subject + body


# ---------------------------------------------------------------------------
# VALID_TEMPLATES set
# ---------------------------------------------------------------------------

def test_valid_templates_set_unchanged():
    """Guard against accidental removals from the template registry."""
    assert "cold_outreach" in VALID_TEMPLATES
    assert "recruiter_outreach" in VALID_TEMPLATES
    assert "referral_outreach" in VALID_TEMPLATES
    assert "followup" in VALID_TEMPLATES
