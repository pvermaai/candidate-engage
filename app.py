import os
import json
import uuid
import logging
from functools import wraps
from flask import (Flask, render_template, request, jsonify, Response,
                   stream_with_context, redirect, url_for, session)
from dotenv import load_dotenv
from werkzeug.exceptions import RequestEntityTooLarge
import anthropic

load_dotenv()

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── App Setup ─────────────────────────────────────────────────
app = Flask(__name__)

secret_key = os.getenv("FLASK_SECRET_KEY")
if not secret_key or secret_key == "dev-secret-key":
    logger.warning("FLASK_SECRET_KEY is missing or using the insecure default")
app.secret_key = secret_key or "dev-secret-key"

app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ── Rate Limiting ─────────────────────────────────────────────
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per hour"],
    storage_uri="memory://",
)

# ── Imports from lib ──────────────────────────────────────────
from lib.database import (init_db, save_candidate, update_candidate_resume_analysis,
                           save_message, log_api_usage, get_all_candidates,
                           get_candidate, get_conversations, get_api_usage_summary,
                           link_conversations_to_candidate, candidate_exists,
                           save_jd, get_all_db_jds, delete_jd, jd_id_exists_in_db)
import re as _re
from lib.jds import get_jd, get_all_jds, get_all_jds_full, COMPANY_CONTEXT, BUILTIN_JD_IDS
from lib.prompts import build_chat_system_prompt
from lib.confidence_gate import pre_screen
from lib.resume_parser import parse_resume
from lib.match_scorer import compute_match

init_db()

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "abc@123")


# ── Helpers ───────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def parse_candidate_json_fields(c: dict) -> dict:
    """Parse JSON string fields in a candidate dict (shared helper)."""
    for field in ("extracted_profile", "match_breakdown", "match_suggestions"):
        val = c.get(field)
        if val and isinstance(val, str):
            try:
                c[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return c


def safe_int(value, default=None):
    """Safely convert a value to int, returning default on failure."""
    if not value:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    return _re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_tag_list(raw: str) -> list[str]:
    """Split comma-separated string into a clean list of non-empty items."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Error Handlers ────────────────────────────────────────────

@app.errorhandler(RequestEntityTooLarge)
def file_too_large(e):
    return jsonify({"error": "File too large. Maximum size is 10 MB."}), 413


@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({"error": "Too many requests. Please slow down."}), 429


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error"}), 500


# ── Page Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    jds = get_all_jds()
    return render_template("index.html", jds=jds)


@app.route("/chat/<jd_id>")
def chat_page(jd_id):
    jd = get_jd(jd_id)
    if not jd:
        return redirect(url_for("index"))
    return render_template("chat.html", jd=jd)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        uid = request.form.get("user_id", "").strip()
        pwd = request.form.get("password", "")
        if uid == ADMIN_USER and pwd == ADMIN_PASSWORD:
            session["admin_authenticated"] = True
            logger.info("Admin login from %s (user: %s)", request.remote_addr, uid)
            return redirect(url_for("admin_page"))
        error = "Invalid user ID or password"
        logger.warning("Failed admin login attempt from %s (user: %s)",
                       request.remote_addr, uid)
    return render_template("login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_authenticated", None)
    return redirect(url_for("index"))


@app.route("/admin/analyze")
@admin_required
def admin_analyze():
    jds = get_all_jds_full()
    return render_template("analyze.html", jds=jds)


@app.route("/admin/jds/new")
@admin_required
def admin_jd_new():
    return render_template("jd_form.html")


@app.route("/admin/jds")
@admin_required
def admin_jds_list():
    builtin = [get_jd(jid) for jid in BUILTIN_JD_IDS]
    custom = get_all_db_jds()
    return render_template("jd_list.html", builtin=builtin, custom=custom)


@app.route("/admin")
@admin_required
def admin_page():
    candidates = get_all_candidates()
    usage = get_api_usage_summary()
    for c in candidates:
        parse_candidate_json_fields(c)
    return render_template("admin.html", candidates=candidates, usage=usage)


# ── API Routes ────────────────────────────────────────────────

@app.route("/api/jds")
def api_list_jds():
    return jsonify(get_all_jds())


@app.route("/api/chat", methods=["POST"])
@limiter.limit("30 per minute")
def api_chat():
    data = request.get_json()
    jd_id = data.get("jd_id")
    messages = data.get("messages", [])
    user_msg = data.get("message", "")
    session_id = data.get("session_id")

    jd = get_jd(jd_id)
    if not jd:
        return jsonify({"error": "JD not found"}), 404

    if not user_msg.strip():
        return jsonify({"error": "Empty message"}), 400

    screen = pre_screen(user_msg)
    if not screen["allowed"]:
        save_message(jd_id, "user", user_msg, session_id=session_id)
        save_message(jd_id, "assistant", screen["redirect_response"],
                     session_id=session_id)
        return jsonify({
            "response": screen["redirect_response"],
            "confidence": "redirected",
            "category": screen["category"]
        })

    system_prompt = build_chat_system_prompt(jd, hints=screen.get("hints"))

    claude_messages = []
    for m in messages[-10:]:
        claude_messages.append({"role": m["role"], "content": m["content"]})
    claude_messages.append({"role": "user", "content": user_msg})

    def generate():
        client = anthropic.Anthropic()
        full_response = ""
        try:
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                system=system_prompt,
                messages=claude_messages
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield f"data: {json.dumps({'text': text})}\n\n"

                final = stream.get_final_message()
                log_api_usage(
                    "chat",
                    final.usage.input_tokens,
                    final.usage.output_tokens,
                    "claude-sonnet-4-20250514"
                )
                save_message(jd_id, "user", user_msg, session_id=session_id)
                save_message(jd_id, "assistant", full_response,
                             session_id=session_id)
                yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            logger.exception("Chat streaming error for JD %s", jd_id)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/api/interest", methods=["POST"])
@limiter.limit("10 per minute")
def api_interest():
    try:
        data = request.form
        jd_id = data.get("jd_id")
        name = data.get("name", "").strip()
        email = data.get("email", "").strip()
        session_id = data.get("session_id")

        if not name or not email or not jd_id:
            return jsonify({"error": "Name, email, and JD are required"}), 400

        jd = get_jd(jd_id)
        if not jd:
            return jsonify({"error": "Invalid JD"}), 400

        if candidate_exists(email, jd_id):
            return jsonify({"error": "You have already applied for this role"}), 409

        resume_path = None
        if "resume" in request.files:
            file = request.files["resume"]
            if file.filename and file.filename.lower().endswith(".pdf"):
                filename = f"{uuid.uuid4().hex}_{file.filename}"
                resume_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(resume_path)

        candidate_id = save_candidate({
            "name": name,
            "email": email,
            "phone": data.get("phone", "").strip() or None,
            "experience_years": safe_int(data.get("experience_years")),
            "current_location": data.get("current_location", "").strip() or None,
            "jd_id": jd_id,
            "consent": 1 if data.get("consent") else 0,
            "resume_path": resume_path
        })

        if session_id:
            try:
                link_conversations_to_candidate(session_id, email)
            except Exception:
                logger.warning("Could not link session %s to %s", session_id, email)

        result = {"candidate_id": candidate_id, "status": "captured"}

        if resume_path:
            try:
                resume_text, profile = parse_resume(resume_path)
                match_result = compute_match(profile, jd)

                update_candidate_resume_analysis(
                    candidate_id,
                    resume_text,
                    profile,
                    match_result["overall_score"],
                    match_result["breakdown"],
                    match_result["suggestions"]
                )

                result["match_score"] = match_result["overall_score"]
                result["match_result"] = match_result
            except Exception as e:
                logger.exception("Resume processing failed for candidate %d", candidate_id)
                result["resume_error"] = str(e)

        return jsonify(result)
    except Exception as e:
        logger.exception("Interest submission failed")
        return jsonify({"error": f"Submission failed: {str(e)}"}), 500


@app.route("/api/admin/candidates")
@admin_required
def api_candidates():
    return jsonify(get_all_candidates())


@app.route("/api/admin/candidate/<int:cid>")
@admin_required
def api_candidate_detail(cid):
    c = get_candidate(cid)
    if not c:
        return jsonify({"error": "Not found"}), 404
    parse_candidate_json_fields(c)
    if c.get("email"):
        c["conversations"] = get_conversations(candidate_email=c["email"])
    return jsonify(c)


@app.route("/api/admin/jds", methods=["POST"])
@admin_required
def api_create_jd():
    data = request.get_json()
    title = (data.get("title") or "").strip()
    location = (data.get("location") or "").strip()
    mode = (data.get("mode") or "").strip()
    experience = (data.get("experience") or "").strip()
    experience_min = safe_int(data.get("experience_min"), 0)
    experience_max = safe_int(data.get("experience_max"))

    if not title or not location or not mode or not experience:
        return jsonify({"error": "Title, location, work mode, and experience are required"}), 400
    if experience_min is None or experience_min < 0:
        return jsonify({"error": "Minimum experience must be a non-negative number"}), 400

    must_have = data.get("must_have", [])
    good_to_have = data.get("good_to_have", [])
    soft_skills = data.get("soft_skills", [])
    responsibilities = data.get("responsibilities", [])

    if not must_have:
        return jsonify({"error": "At least one must-have skill is required"}), 400

    jd_id = slugify(title)
    if not jd_id:
        return jsonify({"error": "Title must contain at least one alphanumeric character"}), 400

    if jd_id in BUILTIN_JD_IDS or jd_id_exists_in_db(jd_id):
        counter = 2
        while f"{jd_id}-{counter}" in BUILTIN_JD_IDS or jd_id_exists_in_db(f"{jd_id}-{counter}"):
            counter += 1
        jd_id = f"{jd_id}-{counter}"

    department = (data.get("department") or "Product Engineering").strip()

    full_text = f"""{title} — Wissen Technology

Location: {location} | Mode: {mode} | Experience: {experience}

Must-Have Skills:
{chr(10).join('• ' + s for s in must_have)}

Good-to-Have:
{chr(10).join('• ' + s for s in good_to_have)}

Key Responsibilities:
{chr(10).join('• ' + r for r in responsibilities)}

Soft Skills:
{chr(10).join('• ' + s for s in soft_skills)}"""

    jd_data = {
        "id": jd_id,
        "title": title,
        "location": location,
        "mode": mode,
        "experience": experience,
        "experience_min": experience_min,
        "experience_max": experience_max,
        "department": department,
        "must_have": must_have,
        "good_to_have": good_to_have,
        "soft_skills": soft_skills,
        "responsibilities": responsibilities,
        "full_text": full_text,
    }

    try:
        save_jd(jd_data)
        return jsonify({"id": jd_id, "status": "created"})
    except Exception as e:
        logger.exception("Failed to create JD")
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/jds/<jd_id>", methods=["DELETE"])
@admin_required
def api_delete_jd(jd_id):
    if jd_id in BUILTIN_JD_IDS:
        return jsonify({"error": "Built-in JDs cannot be deleted"}), 403
    if delete_jd(jd_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "JD not found"}), 404


@app.route("/api/admin/analyze", methods=["POST"])
@admin_required
@limiter.limit("10 per minute")
def api_admin_analyze():
    jd_id = request.form.get("jd_id")
    if not jd_id:
        return jsonify({"error": "Please select a job role"}), 400

    jd = get_jd(jd_id)
    if not jd:
        return jsonify({"error": "Invalid job role"}), 400

    if "resume" not in request.files:
        return jsonify({"error": "Please upload a resume PDF"}), 400

    file = request.files["resume"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    filename = f"{uuid.uuid4().hex}_{file.filename}"
    resume_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(resume_path)

    try:
        resume_text, profile = parse_resume(resume_path)
        if not resume_text.strip():
            return jsonify({"error": "Could not extract text from the PDF"}), 422

        match_result = compute_match(profile, jd)

        return jsonify({
            "profile": profile,
            "match_result": match_result,
            "jd_title": jd["title"],
        })
    except Exception as e:
        logger.exception("Resume analysis failed for JD %s", jd_id)
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500
    finally:
        try:
            os.unlink(resume_path)
        except OSError:
            pass


@app.route("/api/usage")
def api_usage():
    usage = get_api_usage_summary()
    est_cost = (usage["total_input"] * 3 + usage["total_output"] * 15) / 1_000_000
    usage["estimated_cost_usd"] = round(est_cost, 4)
    return jsonify(usage)


# ── Run ───────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=8080)
