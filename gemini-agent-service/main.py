"""
main.py — FastAPI application for the Gemini Agent Service (Service 8).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import agent
import storage
from tools import enhance_resume_for_job, write_cold_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gemini Agent Service...")
    await storage.create_pool()
    yield
    await storage.close_pool()
    logger.info("Gemini Agent Service shut down.")


app = FastAPI(
    title="Gemini Agent Service",
    description="AI-powered job search, resume tuning, and cold email drafting using Google Gemini API.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "An internal error occurred",
            "path": str(request.url.path),
            "hint": "Check service logs for details"
        }
    )


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class EnhanceResumeRequest(BaseModel):
    resume_text: str
    job_description: str
    level: str = "moderate"  # light | moderate | aggressive


class DraftEmailRequest(BaseModel):
    job_id: Optional[str] = None
    company: str
    role: str
    candidate_name: str = "Applicant"
    candidate_stack: List[str] = Field(default_factory=list)
    contact_name: Optional[str] = None


@app.get("/health", tags=["ops"])
async def health():
    key_set = bool(agent.GEMINI_API_KEY)
    return {
        "status": "ok",
        "gemini_configured": key_set,
        "model": "gemini-2.0-flash" if key_set else None,
        "message": (
            "Ready" if key_set else
            "GEMINI_API_KEY not set — agent features disabled"
        ),
    }


@app.post("/agent/chat", tags=["gemini"])
async def agent_chat(body: ChatRequest):
    if not agent.GEMINI_API_KEY:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Gemini agent not configured",
                "message": "Set GEMINI_API_KEY in your .env file to enable AI features",
                "docs": "https://aistudio.google.com/apikey",
            },
        )
    try:
        res = await agent.process_chat(
            message=body.message,
            session_id=body.session_id,
            context=body.context,
        )
        return res
    except Exception as exc:
        logger.exception("Chat handling error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/agent/enhance-resume", tags=["gemini"])
async def agent_enhance_resume(body: EnhanceResumeRequest):
    return enhance_resume_for_job(
        resume_text=body.resume_text,
        job_description=body.job_description,
        enhancement_level=body.level,
    )


@app.post("/agent/draft-email", tags=["gemini"])
async def agent_draft_email(body: DraftEmailRequest):
    return await write_cold_email(
        company=body.company,
        role=body.role,
        candidate_name=body.candidate_name,
        candidate_stack=body.candidate_stack,
        contact_name=body.contact_name,
        job_id=body.job_id,
    )


@app.get("/agent/sessions/{session_id}", tags=["gemini"])
async def get_agent_session(session_id: str):
    session = await storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
