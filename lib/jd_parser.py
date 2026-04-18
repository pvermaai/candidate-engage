"""
JD document parser — extracts structured job description data from uploaded files.
Supports PDF, Word (.docx), and plain text (.txt) formats.
Pipeline: file → raw text → Claude structured extraction.
"""

import json
import logging
import pdfplumber
import anthropic
from docx import Document as DocxDocument
from lib.prompts import JD_EXTRACTION_PROMPT
from lib.database import log_api_usage

logger = logging.getLogger(__name__)

MAX_JD_CHARS = 8000

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


def allowed_jd_file(filename: str) -> bool:
    if not filename:
        return False
    ext = _get_extension(filename)
    return ext in ALLOWED_EXTENSIONS


def _get_extension(filename: str) -> str:
    from os.path import splitext
    return splitext(filename.lower())[1]


def extract_text_from_file(file_path: str, filename: str) -> str:
    ext = _get_extension(filename)
    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return _extract_docx(file_path)
    elif ext == ".txt":
        return _extract_txt(file_path)
    raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(path: str) -> str:
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def _extract_docx(path: str) -> str:
    doc = DocxDocument(path)
    parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_jd_fields(raw_text: str) -> dict:
    """Use Claude to extract structured JD fields from raw text."""
    client = anthropic.Anthropic()

    truncated = raw_text
    if len(raw_text) > MAX_JD_CHARS:
        truncated = raw_text[:MAX_JD_CHARS]
        logger.warning(
            "JD text truncated from %d to %d chars", len(raw_text), MAX_JD_CHARS
        )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        temperature=0,
        messages=[{"role": "user", "content": JD_EXTRACTION_PROMPT + truncated}],
    )

    log_api_usage(
        "jd_extraction",
        response.usage.input_tokens,
        response.usage.output_tokens,
        "claude-sonnet-4-20250514",
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
        logger.error("Failed to parse JD extraction response: %s", raw[:300])
        raise ValueError("Could not parse the document into structured fields. Please try manual entry.")

    for arr_field in ("must_have", "good_to_have", "soft_skills", "responsibilities"):
        if not isinstance(parsed.get(arr_field), list):
            parsed[arr_field] = []

    return parsed


def parse_jd_document(file_path: str, filename: str) -> tuple[str, dict]:
    """Full pipeline: file → text → structured JD fields."""
    logger.info("Parsing JD document: %s", filename)
    raw_text = extract_text_from_file(file_path, filename)
    if not raw_text.strip():
        raise ValueError("Could not extract any text from the uploaded file")
    fields = extract_jd_fields(raw_text)
    return raw_text, fields
