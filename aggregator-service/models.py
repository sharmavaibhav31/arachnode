"""
models.py — Pydantic v2 response schemas for the Job Aggregator Service.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class JobBase(BaseModel):
    """Fields shared between read and write representations."""

    company: str
    role: str
    source: Optional[str] = None
    url: Optional[str] = None
    stack: Optional[List[str]] = None
    product: Optional[str] = None
    location: Optional[str] = None
    posted_at: Optional[datetime] = None


class JobOut(JobBase):
    """Full job record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    created_at: datetime
    match_score: Optional[float] = None
    match_tier: Optional[str] = None


class StatusUpdate(BaseModel):
    """Payload for PATCH /jobs/{id}/status."""

    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"new", "applied", "ignored"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class StatsOut(BaseModel):
    """Response schema for GET /stats."""

    by_source: dict[str, int]
    by_status: dict[str, int]
