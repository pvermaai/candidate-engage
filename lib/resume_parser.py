"""
Resume parser — two-stage pipeline:
1. Extract raw text from PDF using pdfplumber
2. Extract structured profile using Claude (one API call)
"""

import json
import logging
import pdfplumber
import anthropic
from lib.prompts import RESUME_EXTRACTION_PROMPT
from lib.database import log_api_usage

logger = logging.getLogger(__name__)

MAX_RESUME_CHARS = 6000


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)


def extract_profile(resume_text: str) -> dict:
    """Use Claude to extract a structured profile from resume text."""
    client = anthropic.Anthropic()

    truncated = resume_text
    if len(resume_text) > MAX_RESUME_CHARS:
        truncated = resume_text[:MAX_RESUME_CHARS]
        logger.warning(
            "Resume text truncated from %d to %d chars — some content may be lost",
            len(resume_text), MAX_RESUME_CHARS
        )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        temperature=0,
        messages=[{
            "role": "user",
            "content": RESUME_EXTRACTION_PROMPT + truncated
        }]
    )

    log_api_usage(
        "resume_extraction",
        response.usage.input_tokens,
        response.usage.output_tokens,
        "claude-sonnet-4-20250514"
    )

    raw = response.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM resume extraction response: %s", raw[:200])
        return {
            "years_of_experience": None,
            "current_role": None,
            "skills": {},
            "soft_skills_signals": [],
            "architecture_signals": [],
            "ownership_signals": [],
            "parse_error": "Failed to parse LLM response",
            "raw_response": raw[:500]
        }

    if not isinstance(parsed.get("skills"), dict):
        parsed["skills"] = {}
    for arr_field in ("soft_skills_signals", "architecture_signals",
                      "ownership_signals", "domain_hints", "certifications"):
        if not isinstance(parsed.get(arr_field), list):
            parsed[arr_field] = []

    return parsed


def parse_resume(pdf_path: str) -> tuple[str, dict]:
    """Full pipeline: PDF → text → structured profile."""
    logger.info("Parsing resume: %s", pdf_path)
    resume_text = extract_text_from_pdf(pdf_path)
    if not resume_text.strip():
        logger.warning("No text extracted from PDF: %s", pdf_path)
        return "", {"parse_error": "No text could be extracted from the PDF"}
    profile = extract_profile(resume_text)
    return resume_text, profile
