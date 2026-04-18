"""
Resume parser — two-stage pipeline:
1. Extract raw text from PDF using pdfplumber
2. Extract structured profile using Claude (one API call)
"""

import json
import pdfplumber
import anthropic
from lib.prompts import RESUME_EXTRACTION_PROMPT
from lib.database import log_api_usage


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

    # Truncate very long resumes to save tokens
    truncated = resume_text[:6000] if len(resume_text) > 6000 else resume_text

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

    # Clean potential markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "years_of_experience": None,
            "current_role": None,
            "skills": {},
            "parse_error": "Failed to parse LLM response",
            "raw_response": raw[:500]
        }


def parse_resume(pdf_path: str) -> tuple[str, dict]:
    """Full pipeline: PDF → text → structured profile."""
    resume_text = extract_text_from_pdf(pdf_path)
    if not resume_text.strip():
        return "", {"parse_error": "No text could be extracted from the PDF"}
    profile = extract_profile(resume_text)
    return resume_text, profile
