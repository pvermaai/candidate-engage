import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "candidates.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
    """)
    conn.commit()
    conn.close()


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
    return candidate_id


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


def save_message(jd_id: str, role: str, content: str, candidate_email: str = None):
    conn = get_db()
    conn.execute("""
        INSERT INTO conversations (candidate_email, jd_id, role, content)
        VALUES (?, ?, ?, ?)
    """, (candidate_email, jd_id, role, content))
    conn.commit()
    conn.close()


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


def get_conversations(jd_id: str = None, candidate_email: str = None):
    conn = get_db()
    if candidate_email:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE candidate_email = ? ORDER BY created_at",
            (candidate_email,)
        ).fetchall()
    elif jd_id:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE jd_id = ? ORDER BY created_at",
            (jd_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM conversations ORDER BY created_at DESC LIMIT 200").fetchall()
    conn.close()
    return [dict(r) for r in rows]


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
