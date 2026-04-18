import sqlite3
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "candidates.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            experience_years INTEGER,
            current_location TEXT,
            jd_id TEXT NOT NULL,
            consent INTEGER DEFAULT 0,
            resume_path TEXT,
            resume_text TEXT,
            extracted_profile TEXT,
            match_score INTEGER,
            match_breakdown TEXT,
            match_suggestions TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            candidate_email TEXT,
            jd_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            model TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS job_descriptions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            location TEXT NOT NULL,
            mode TEXT NOT NULL,
            experience TEXT NOT NULL,
            experience_min INTEGER NOT NULL DEFAULT 0,
            experience_max INTEGER,
            department TEXT DEFAULT 'Product Engineering',
            must_have TEXT NOT NULL DEFAULT '[]',
            good_to_have TEXT NOT NULL DEFAULT '[]',
            soft_skills TEXT NOT NULL DEFAULT '[]',
            responsibilities TEXT NOT NULL DEFAULT '[]',
            full_text TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_email
            ON conversations(candidate_email);
        CREATE INDEX IF NOT EXISTS idx_candidates_email_jd
            ON candidates(email, jd_id);
    """)

    _migrate(conn)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_session
            ON conversations(session_id)
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", DB_PATH)


def _migrate(conn):
    """Add columns that may not exist in older schema versions."""
    migrations = [
        "ALTER TABLE conversations ADD COLUMN session_id TEXT",
        "ALTER TABLE conversations ADD COLUMN candidate_email TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except Exception:
            pass


def save_candidate(data: dict) -> int:
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO candidates (name, email, phone, experience_years, current_location,
                                jd_id, consent, resume_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["name"], data["email"], data.get("phone"),
        data.get("experience_years"), data.get("current_location"),
        data["jd_id"], data.get("consent", 0), data.get("resume_path")
    ))
    conn.commit()
    candidate_id = cur.lastrowid
    conn.close()
    logger.info("Saved candidate %d (%s) for JD %s", candidate_id, data["email"], data["jd_id"])
    return candidate_id


def candidate_exists(email: str, jd_id: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM candidates WHERE email = ? AND jd_id = ?",
        (email, jd_id)
    ).fetchone()
    conn.close()
    return row is not None


def update_candidate_resume_analysis(candidate_id: int, resume_text: str,
                                      extracted_profile: dict,
                                      match_score: int,
                                      match_breakdown: dict,
                                      match_suggestions: list):
    conn = get_db()
    conn.execute("""
        UPDATE candidates
        SET resume_text = ?, extracted_profile = ?, match_score = ?,
            match_breakdown = ?, match_suggestions = ?
        WHERE id = ?
    """, (
        resume_text,
        json.dumps(extracted_profile),
        match_score,
        json.dumps(match_breakdown),
        json.dumps(match_suggestions),
        candidate_id
    ))
    conn.commit()
    conn.close()


def save_message(jd_id: str, role: str, content: str,
                 candidate_email: str = None, session_id: str = None):
    conn = get_db()
    conn.execute("""
        INSERT INTO conversations (session_id, candidate_email, jd_id, role, content)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, candidate_email, jd_id, role, content))
    conn.commit()
    conn.close()


def link_conversations_to_candidate(session_id: str, candidate_email: str):
    """Link all chat messages from a session to a candidate after they express interest."""
    if not session_id:
        return
    conn = get_db()
    conn.execute("""
        UPDATE conversations SET candidate_email = ?
        WHERE session_id = ? AND candidate_email IS NULL
    """, (candidate_email, session_id))
    conn.commit()
    conn.close()
    logger.info("Linked session %s conversations to %s", session_id, candidate_email)


def log_api_usage(endpoint: str, input_tokens: int, output_tokens: int, model: str):
    conn = get_db()
    conn.execute("""
        INSERT INTO api_usage (endpoint, input_tokens, output_tokens, model)
        VALUES (?, ?, ?, ?)
    """, (endpoint, input_tokens, output_tokens, model))
    conn.commit()
    conn.close()


def get_all_candidates():
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM candidates ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_candidate(candidate_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_conversations(jd_id: str = None, candidate_email: str = None,
                      session_id: str = None):
    conn = get_db()
    if candidate_email:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE candidate_email = ? ORDER BY created_at",
            (candidate_email,)
        ).fetchall()
    elif session_id:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE session_id = ? ORDER BY created_at",
            (session_id,)
        ).fetchall()
    elif jd_id:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE jd_id = ? ORDER BY created_at",
            (jd_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Job Description CRUD ──────────────────────────────────────

def save_jd(data: dict) -> str:
    conn = get_db()
    conn.execute("""
        INSERT INTO job_descriptions
            (id, title, location, mode, experience, experience_min, experience_max,
             department, must_have, good_to_have, soft_skills, responsibilities, full_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["id"], data["title"], data["location"], data["mode"],
        data["experience"], data["experience_min"], data.get("experience_max"),
        data.get("department", "Product Engineering"),
        json.dumps(data.get("must_have", [])),
        json.dumps(data.get("good_to_have", [])),
        json.dumps(data.get("soft_skills", [])),
        json.dumps(data.get("responsibilities", [])),
        data.get("full_text", ""),
    ))
    conn.commit()
    conn.close()
    logger.info("Saved JD: %s (%s)", data["id"], data["title"])
    return data["id"]


def get_db_jd(jd_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_jd(dict(row))


def get_all_db_jds() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM job_descriptions ORDER BY created_at DESC").fetchall()
    conn.close()
    return [_row_to_jd(dict(r)) for r in rows]


def delete_jd(jd_id: str) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM job_descriptions WHERE id = ?", (jd_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if deleted:
        logger.info("Deleted JD: %s", jd_id)
    return deleted


def jd_id_exists_in_db(jd_id: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()
    conn.close()
    return row is not None


def _row_to_jd(row: dict) -> dict:
    """Convert a DB row into the same dict shape as the hardcoded JDs."""
    for field in ("must_have", "good_to_have", "soft_skills", "responsibilities"):
        val = row.get(field)
        if val and isinstance(val, str):
            try:
                row[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                row[field] = []
    return row


def get_api_usage_summary():
    conn = get_db()
    row = conn.execute("""
        SELECT COUNT(*) as total_calls,
               COALESCE(SUM(input_tokens), 0) as total_input,
               COALESCE(SUM(output_tokens), 0) as total_output
        FROM api_usage
    """).fetchone()
    conn.close()
    return dict(row)
