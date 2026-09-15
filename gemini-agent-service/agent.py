"""
agent.py — Gemini Agent configuration and invocation logic.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from tools import (
    enhance_resume_for_job,
    get_tools,
    search_jobs_pipeline,
    search_jobs_web,
    write_cold_email,
)
import storage

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def get_model() -> Optional[genai.GenerativeModel]:
    if not GEMINI_API_KEY:
        return None
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        tools=get_tools(),
        system_instruction="""
        You are Arachnode's job search and career assistant.
        You help users find relevant jobs, improve their resumes,
        and write cold emails that get responses.
        
        When searching for jobs, always prefer freshly posted ones
        (last 14 days). When writing emails, keep them under
        150 words and make them specific to the company.
        When enhancing resumes, never fabricate experience —
        only reframe what already exists using the JD's language.
        """,
    )


async def process_chat(
    message: str,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured")

    sid = session_id or str(uuid.uuid4())
    existing_session = await storage.get_session(sid)
    messages = existing_session["messages"] if existing_session else []

    model = get_model()
    if not model:
        raise ValueError("Model initialization failed")

    # Append user message
    user_msg_entry = {"role": "user", "content": message}
    messages.append(user_msg_entry)

    tool_calls_executed = []
    jobs_found = []
    email_draft = None
    resume_enhanced = None

    try:
        # Generate model response
        chat = model.start_chat(enable_automatic_function_calling=True)
        response = await asyncio.to_thread(chat.send_message, message)
        response_text = response.text if response and hasattr(response, "text") else "I've processed your request."

        # Check for tool call execution signals or direct keyword triggers
        lower_msg = message.lower()
        if "job" in lower_msg or "search" in lower_msg or "find" in lower_msg:
            # Execute web & pipeline search for rich response
            web_jobs = await search_jobs_web(message)
            if web_jobs:
                jobs_found.extend(web_jobs)
                tool_calls_executed.append({"tool": "search_jobs_web", "result_count": len(web_jobs)})

        if "email" in lower_msg or "draft" in lower_msg or "write" in lower_msg:
            email_draft = await write_cold_email(
                company=context.get("company", "Target Company") if context else "Target Company",
                role=context.get("role", "Software Engineer") if context else "Software Engineer",
                candidate_name=context.get("candidate_name", "Applicant") if context else "Applicant",
            )
            tool_calls_executed.append({"tool": "write_cold_email", "result_count": 1})

        if "resume" in lower_msg or "tune" in lower_msg or "optimize" in lower_msg:
            resume_text = (context.get("resume_text") if context else "") or message
            job_desc = (context.get("job_description") if context else "") or "Backend Software Engineer"
            resume_enhanced = enhance_resume_for_job(resume_text, job_desc)
            tool_calls_executed.append({"tool": "enhance_resume_for_job", "result_count": 1})

        model_msg_entry = {"role": "model", "content": response_text}
        messages.append(model_msg_entry)

        await storage.save_session(sid, messages, context)

        result: Dict[str, Any] = {
            "session_id": sid,
            "response": response_text,
            "tool_calls": tool_calls_executed,
        }
        if jobs_found:
            result["jobs"] = jobs_found
        if email_draft:
            result["email_draft"] = email_draft
        if resume_enhanced:
            result["resume_enhanced"] = resume_enhanced

        return result

    except Exception as exc:
        logger.error("Error in Gemini chat process: %s", exc)
        # Fallback response if API issue occurs
        response_text = f"I understood your request: '{message}'. Currently processing via Gemini Agent."
        model_msg_entry = {"role": "model", "content": response_text}
        messages.append(model_msg_entry)
        await storage.save_session(sid, messages, context)

        return {
            "session_id": sid,
            "response": response_text,
            "tool_calls": tool_calls_executed,
            "jobs": jobs_found,
            "email_draft": email_draft,
            "resume_enhanced": resume_enhanced,
        }
