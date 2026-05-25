"""
test_resume_parser.py

Unit tests for the resume parser module.
Testing skill extraction, experience detection,
role detection, and the prompt snippet output.
"""

import pytest
from resume_parser import parse_resume, CandidateContext


# --- Sample resume texts for testing ---

STRONG_RESUME = b"""
Jane Doe
Senior Software Engineer
5 years of experience

Skills: Python, FastAPI, Docker, PostgreSQL, React, AWS

Experience:
- Senior Backend Engineer at TechCorp (2021-2024)
- Built REST APIs using FastAPI and Python
- Deployed microservices using Docker and Kubernetes
- Managed PostgreSQL databases
"""

MINIMAL_RESUME = b"""
John Smith
Developer
I have worked with javascript and nodejs for 2 years.
"""

EMPTY_RESUME = b""

NO_EXPERIENCE_RESUME = b"""
Alice Johnson
Software Engineer

Skills: Python, Django, Redis
Projects: Built a web scraper using Python
"""


# --- Tests ---

def test_skills_extracted_correctly():
    result = parse_resume(STRONG_RESUME, file_type="txt")
    assert "python" in result.skills
    assert "fastapi" in result.skills
    assert "docker" in result.skills
    assert "postgresql" in result.skills


def test_experience_extracted_correctly():
    result = parse_resume(STRONG_RESUME, file_type="txt")
    assert result.years_experience == 5


def test_role_extracted_correctly():
    result = parse_resume(STRONG_RESUME, file_type="txt")
    assert result.recent_role is not None
    assert "engineer" in result.recent_role.lower()


def test_minimal_resume_still_works():
    result = parse_resume(MINIMAL_RESUME, file_type="txt")
    assert "javascript" in result.skills or "nodejs" in result.skills
    assert result.years_experience == 2


def test_empty_resume_returns_empty_context():
    result = parse_resume(EMPTY_RESUME, file_type="txt")
    assert result.is_empty() is True


def test_no_experience_returns_none():
    result = parse_resume(NO_EXPERIENCE_RESUME, file_type="txt")
    assert result.years_experience is None


def test_prompt_snippet_not_empty_for_strong_resume():
    result = parse_resume(STRONG_RESUME, file_type="txt")
    snippet = result.to_prompt_snippet()
    assert len(snippet) > 0
    assert "Skills" in snippet


def test_prompt_snippet_empty_for_empty_resume():
    result = parse_resume(EMPTY_RESUME, file_type="txt")
    snippet = result.to_prompt_snippet()
    assert snippet == ""


def test_candidate_context_is_empty_check():
    empty = CandidateContext()
    assert empty.is_empty() is True

    filled = CandidateContext(skills=["python"], recent_role="engineer")
    assert filled.is_empty() is False