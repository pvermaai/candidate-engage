import os
import json
import uuid
from flask import (Flask, render_template, request, jsonify, Response,
                   stream_with_context, redirect, url_for)
from dotenv import load_dotenv
import anthropic

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

from lib.database import (init_db, save_candidate, update_candidate_resume_analysis,
                           save_message, log_api_usage, get_all_candidates,
                           get_candidate, get_conversations, get_api_usage_summary)
from lib.jds import get_jd, get_all_jds, COMPANY_CONTEXT
from lib.prompts import build_chat_system_prompt
from lib.confidence_gate import pre_screen
from lib.resume_parser import parse_resume
from lib.match_scorer import compute_match

init_db()


# ── Page Routes ───────────────────────────────────────────────────

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


@app.route("/admin")
def admin_page():
    candidates = get_all_candidates()
    usage = get_api_usage_summary()
    # Parse JSON fields for display
    for c in candidates:
        if c.get("extracted_profile"):
            try:
                c["extracted_profile"] = json.loads(c["extracted_profile"])
            except (json.JSONDecodeError, TypeError):
                pass
        if c.get("match_breakdown"):
            try:
                c["match_breakdown"] = json.loads(c["match_breakdown"])
            except (json.JSONDecodeError, TypeError):
                pass
        if c.get("match_suggestions"):
            try:
                c["match_suggestions"] = json.loads(c["match_suggestions"])
            except (json.JSONDecodeError, TypeError):
                pass
    return render_template("admin.html", candidates=candidates, usage=usage)


# ── API Routes ────────────────────────────────────────────────────

@app.route("/api/jds")
def api_list_jds():
    return jsonify(get_all_jds())


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    jd_id = data.get("jd_id")
    messages = data.get("messages", [])
    user_msg = data.get("message", "")

    jd = get_jd(jd_id)
    if not jd:
        return jsonify({"error": "JD not found"}), 404

    if not user_msg.strip():
        return jsonify({"error": "Empty message"}), 400

    # Pre-screen with confidence gate
    screen = pre_screen(user_msg)
    if not screen["allowed"]:
        # Return canned response without calling LLM — saves tokens
        save_message(jd_id, "user", user_msg)
        save_message(jd_id, "assistant", screen["redirect_response"])
        return jsonify({
            "response": screen["redirect_response"],
            "confidence": "redirected",
            "category": screen["category"]
        })

    # Build conversation for Claude
    system_prompt = build_chat_system_prompt(jd)
    claude_messages = []
    for m in messages[-10:]:  # Keep last 10 turns to save tokens
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

                # After stream completes, log usage
                final = stream.get_final_message()
                log_api_usage(
                    "chat",
                    final.usage.input_tokens,
                    final.usage.output_tokens,
                    "claude-sonnet-4-20250514"
                )
                save_message(jd_id, "user", user_msg)
                save_message(jd_id, "assistant", full_response)
                yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/api/interest", methods=["POST"])
def api_interest():
    data = request.form
    jd_id = data.get("jd_id")
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()

    if not name or not email or not jd_id:
        return jsonify({"error": "Name, email, and JD are required"}), 400

    jd = get_jd(jd_id)
    if not jd:
        return jsonify({"error": "Invalid JD"}), 400

    # Handle resume upload
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
        "experience_years": int(data["experience_years"]) if data.get("experience_years") else None,
        "current_location": data.get("current_location", "").strip() or None,
        "jd_id": jd_id,
        "consent": 1 if data.get("consent") else 0,
        "resume_path": resume_path
    })

    result = {"candidate_id": candidate_id, "status": "captured"}

    # Process resume if uploaded
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
            result["resume_error"] = str(e)

    return jsonify(result)


@app.route("/api/admin/candidates")
def api_candidates():
    return jsonify(get_all_candidates())


@app.route("/api/admin/candidate/<int:cid>")
def api_candidate_detail(cid):
    c = get_candidate(cid)
    if not c:
        return jsonify({"error": "Not found"}), 404
    # Parse JSON fields
    for field in ["extracted_profile", "match_breakdown", "match_suggestions"]:
        if c.get(field):
            try:
                c[field] = json.loads(c[field])
            except (json.JSONDecodeError, TypeError):
                pass
    # Get conversations
    if c.get("email"):
        c["conversations"] = get_conversations(candidate_email=c["email"])
    return jsonify(c)


@app.route("/api/usage")
def api_usage():
    usage = get_api_usage_summary()
    # Estimate cost (Claude Sonnet pricing: ~$3/M input, $15/M output)
    est_cost = (usage["total_input"] * 3 + usage["total_output"] * 15) / 1_000_000
    usage["estimated_cost_usd"] = round(est_cost, 4)
    return jsonify(usage)


# ── Run ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
