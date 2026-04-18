"""
Tests for key logic: match scoring, confidence gate, skill matching, database, API.
Run: python -m pytest tests/ -v
"""

import sys
import os
import json
import tempfile
import sqlite3
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lib.match_scorer import skill_matches, score_experience, score_skills, get_all_resume_skills
from lib.confidence_gate import pre_screen
from lib.jds import get_jd, get_all_jds
from lib.prompts import build_chat_system_prompt


# ── Skill Matching Tests ──────────────────────────────────────

def test_exact_match():
    assert skill_matches(["Java", "Python"], "Java") is True

def test_case_insensitive():
    assert skill_matches(["spring boot"], "Spring Boot") is True

def test_alias_k8s():
    assert skill_matches(["k8s"], "Kubernetes") is True

def test_alias_java8():
    assert skill_matches(["Java 17"], "Java 8+") is True

def test_no_match():
    assert skill_matches(["Python", "Django"], "Java") is False

def test_contains_match():
    assert skill_matches(["REST APIs"], "REST APIs") is True

def test_nosql_variants():
    assert skill_matches(["MongoDB", "Redis"], "NoSQL databases") is True

def test_cloud_match():
    assert skill_matches(["AWS"], "AWS / Azure / GCP (any one)") is True


# ── Experience Scoring Tests ──────────────────────────────────

def test_experience_exact_match():
    jd = get_jd("java-architect")
    score = score_experience(14, jd)
    assert score >= 70

def test_experience_under():
    jd = get_jd("java-architect")
    score = score_experience(5, jd)
    assert score <= 30

def test_experience_way_under():
    jd = get_jd("java-architect")
    score = score_experience(2, jd)
    assert score <= 15

def test_experience_none():
    jd = get_jd("java-architect")
    score = score_experience(None, jd)
    assert score == 30

def test_experience_developer_range():
    jd = get_jd("java-developer")
    score = score_experience(6, jd)
    assert score == 100

def test_experience_overqualified():
    jd = get_jd("java-developer")
    score = score_experience(15, jd)
    assert score >= 60

def test_experience_max_defined():
    """Java Architect should have experience_max set (gap fix)."""
    jd = get_jd("java-architect")
    assert "experience_max" in jd
    assert jd["experience_max"] > jd["experience_min"]


# ── Skill Scoring Tests ──────────────────────────────────────

def test_full_skill_match():
    resume_skills = ["Java", "Spring Boot", "Docker", "Kubernetes", "AWS",
                     "Hibernate", "REST APIs", "MongoDB", "PostgreSQL",
                     "Microservices", "Java 17"]
    jd = get_jd("java-architect")
    score, matched, missing = score_skills(resume_skills, jd["must_have"])
    assert score >= 70
    assert len(matched) >= 8

def test_no_skill_match():
    resume_skills = ["Python", "Django", "Flask"]
    jd = get_jd("java-architect")
    score, matched, missing = score_skills(resume_skills, jd["must_have"])
    assert score <= 20
    assert len(missing) >= 8

def test_empty_jd_skills():
    score, matched, missing = score_skills(["Java"], [])
    assert score == 50


# ── Confidence Gate Tests ─────────────────────────────────────

def test_salary_blocked():
    result = pre_screen("What is the salary for this role?")
    assert result["allowed"] is False
    assert result["category"] == "compensation"

def test_ctc_blocked():
    result = pre_screen("What CTC can I expect?")
    assert result["allowed"] is False

def test_visa_blocked():
    result = pre_screen("Do you sponsor H1B visas?")
    assert result["allowed"] is False
    assert result["category"] == "visa"

def test_competitor_blocked():
    result = pre_screen("How does Wissen compare to TCS?")
    assert result["allowed"] is False
    assert result["category"] == "competitor_comparison"

def test_normal_question_allowed():
    result = pre_screen("What skills are needed for this role?")
    assert result["allowed"] is True
    assert result["redirect_response"] is None

def test_culture_question_allowed():
    result = pre_screen("Tell me about the company culture")
    assert result["allowed"] is True

def test_interview_hint():
    result = pre_screen("How many interview rounds are there?")
    assert result["allowed"] is True
    assert "interview_process" in result["hints"]

def test_work_mode_hint():
    result = pre_screen("Can I work from home?")
    assert result["allowed"] is True
    assert "work_mode" in result["hints"]

def test_joining_hint():
    result = pre_screen("What is the expected notice period?")
    assert result["allowed"] is True
    assert "joining" in result["hints"]

def test_equity_blocked():
    result = pre_screen("How many RSU shares will I get?")
    assert result["allowed"] is False
    assert result["category"] == "equity"


# ── Profile Extraction Helper ────────────────────────────────

def test_get_all_resume_skills():
    profile = {
        "skills": {
            "languages": ["Java", "Python"],
            "frameworks": ["Spring Boot"],
            "databases": ["MongoDB"],
        },
        "architecture_signals": ["designed microservices"],
        "soft_skills_signals": ["mentoring"],
        "ownership_signals": []
    }
    all_skills = get_all_resume_skills(profile)
    assert "Java" in all_skills
    assert "Spring Boot" in all_skills
    assert "designed microservices" in all_skills
    assert len(all_skills) == 6

def test_get_all_resume_skills_empty():
    profile = {"skills": {}}
    all_skills = get_all_resume_skills(profile)
    assert all_skills == []


# ── Prompt Building Tests ─────────────────────────────────────

def test_build_prompt_without_hints():
    jd = get_jd("java-architect")
    prompt = build_chat_system_prompt(jd)
    assert "Java Architect" in prompt
    assert "CONTEXTUAL GUIDANCE" not in prompt

def test_build_prompt_with_hints():
    jd = get_jd("java-architect")
    prompt = build_chat_system_prompt(jd, hints=["interview_process"])
    assert "CONTEXTUAL GUIDANCE" in prompt
    assert "interview" in prompt.lower()

def test_build_prompt_with_work_mode_hint():
    jd = get_jd("java-developer")
    prompt = build_chat_system_prompt(jd, hints=["work_mode"])
    assert "CONTEXTUAL GUIDANCE" in prompt
    assert "work mode" in prompt.lower()

def test_build_prompt_with_empty_hints():
    jd = get_jd("java-architect")
    prompt = build_chat_system_prompt(jd, hints=[])
    assert "CONTEXTUAL GUIDANCE" not in prompt


# ── JD Registry Tests ─────────────────────────────────────────

def test_get_all_jds():
    jds = get_all_jds()
    assert len(jds) >= 2
    for jd in jds:
        assert "id" in jd
        assert "title" in jd

def test_get_jd_invalid():
    assert get_jd("nonexistent") is None

def test_jd_has_required_fields():
    for jd_id in ("java-architect", "java-developer"):
        jd = get_jd(jd_id)
        for field in ("must_have", "good_to_have", "soft_skills",
                       "responsibilities", "experience_min"):
            assert field in jd, f"{jd_id} missing field: {field}"


# ── Database Tests ────────────────────────────────────────────

class TestDatabase:
    """Tests for database operations using a temp database."""

    def setup_method(self):
        """Set up a temporary database for each test."""
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.orig_path = None

    def teardown_method(self):
        if self.orig_path:
            import lib.database as db_mod
            db_mod.DB_PATH = self.orig_path
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _use_temp_db(self):
        import lib.database as db_mod
        self.orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.tmp.name
        db_mod.init_db()
        return db_mod

    def test_save_and_get_candidate(self):
        db = self._use_temp_db()
        cid = db.save_candidate({
            "name": "John Doe",
            "email": "john@example.com",
            "jd_id": "java-developer",
            "consent": 1,
        })
        assert cid > 0
        c = db.get_candidate(cid)
        assert c["name"] == "John Doe"
        assert c["email"] == "john@example.com"

    def test_candidate_exists(self):
        db = self._use_temp_db()
        assert db.candidate_exists("nobody@example.com", "java-developer") is False
        db.save_candidate({
            "name": "Jane", "email": "jane@example.com",
            "jd_id": "java-developer"
        })
        assert db.candidate_exists("jane@example.com", "java-developer") is True
        assert db.candidate_exists("jane@example.com", "java-architect") is False

    def test_save_message_with_session(self):
        db = self._use_temp_db()
        db.save_message("java-dev", "user", "Hello", session_id="sess-123")
        db.save_message("java-dev", "assistant", "Hi!", session_id="sess-123")
        convos = db.get_conversations(session_id="sess-123")
        assert len(convos) == 2
        assert convos[0]["role"] == "user"
        assert convos[1]["role"] == "assistant"

    def test_link_conversations_to_candidate(self):
        db = self._use_temp_db()
        db.save_message("java-dev", "user", "Hello", session_id="sess-456")
        db.save_message("java-dev", "assistant", "Hi!", session_id="sess-456")
        db.link_conversations_to_candidate("sess-456", "test@example.com")
        convos = db.get_conversations(candidate_email="test@example.com")
        assert len(convos) == 2

    def test_api_usage_logging(self):
        db = self._use_temp_db()
        db.log_api_usage("chat", 100, 50, "claude-sonnet")
        db.log_api_usage("chat", 200, 100, "claude-sonnet")
        summary = db.get_api_usage_summary()
        assert summary["total_calls"] == 2
        assert summary["total_input"] == 300
        assert summary["total_output"] == 150

    def test_get_all_candidates_empty(self):
        db = self._use_temp_db()
        assert db.get_all_candidates() == []


# ── Flask App Tests ───────────────────────────────────────────

class TestFlaskApp:
    """Integration tests for Flask routes."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()

        import lib.database as db_mod
        self.orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.tmp.name
        db_mod.init_db()

        from app import app
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.app = app

    def teardown_method(self):
        import lib.database as db_mod
        db_mod.DB_PATH = self.orig_path
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_index_page(self):
        res = self.client.get("/")
        assert res.status_code == 200
        assert b"Wissen" in res.data

    def test_chat_page_valid_jd(self):
        res = self.client.get("/chat/java-developer")
        assert res.status_code == 200
        assert b"Java Developer" in res.data

    def test_chat_page_invalid_jd(self):
        res = self.client.get("/chat/nonexistent")
        assert res.status_code == 302

    def test_api_jds(self):
        res = self.client.get("/api/jds")
        data = res.get_json()
        assert len(data) >= 2

    def test_api_chat_missing_jd(self):
        res = self.client.post("/api/chat",
                               json={"jd_id": "nope", "message": "hi"})
        assert res.status_code == 404

    def test_api_chat_empty_message(self):
        res = self.client.post("/api/chat",
                               json={"jd_id": "java-developer", "message": "  "})
        assert res.status_code == 400

    def test_api_chat_confidence_gate_redirect(self):
        res = self.client.post("/api/chat",
                               json={"jd_id": "java-developer",
                                     "message": "What is the salary?",
                                     "session_id": "test-sess"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["confidence"] == "redirected"
        assert data["category"] == "compensation"

    def test_api_interest_missing_fields(self):
        res = self.client.post("/api/interest", data={"jd_id": "java-developer"})
        assert res.status_code == 400

    def test_api_interest_invalid_jd(self):
        res = self.client.post("/api/interest",
                               data={"jd_id": "nope", "name": "John", "email": "j@e.com"})
        assert res.status_code == 400

    def test_api_interest_success(self):
        res = self.client.post("/api/interest",
                               data={"jd_id": "java-developer",
                                     "name": "Test User",
                                     "email": "test@example.com",
                                     "consent": "on",
                                     "session_id": "test-sess"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "captured"
        assert "candidate_id" in data

    def test_api_interest_duplicate(self):
        self.client.post("/api/interest",
                         data={"jd_id": "java-developer",
                               "name": "Test", "email": "dup@example.com"})
        res = self.client.post("/api/interest",
                               data={"jd_id": "java-developer",
                                     "name": "Test", "email": "dup@example.com"})
        assert res.status_code == 409

    def test_api_interest_bad_experience(self):
        """Non-numeric experience_years should not crash (gap fix)."""
        res = self.client.post("/api/interest",
                               data={"jd_id": "java-developer",
                                     "name": "Test",
                                     "email": "exp@example.com",
                                     "experience_years": "five"})
        assert res.status_code == 200

    def test_api_usage(self):
        res = self.client.get("/api/usage")
        data = res.get_json()
        assert "estimated_cost_usd" in data
        assert "total_calls" in data

    def test_admin_requires_auth(self):
        res = self.client.get("/admin")
        assert res.status_code == 302
        assert "/admin/login" in res.headers["Location"]

    def test_admin_api_requires_auth(self):
        res = self.client.get("/api/admin/candidates")
        assert res.status_code == 401

    def test_admin_login_wrong_password(self):
        res = self.client.post("/admin/login",
                               data={"user_id": "admin", "password": "wrong"})
        assert res.status_code == 200
        assert b"Invalid user ID or password" in res.data

    def test_admin_login_wrong_user(self):
        res = self.client.post("/admin/login",
                               data={"user_id": "nobody", "password": "abc@123"})
        assert res.status_code == 200
        assert b"Invalid user ID or password" in res.data

    def test_admin_login_correct_credentials(self):
        res = self.client.post("/admin/login",
                               data={"user_id": "admin", "password": "abc@123"},
                               follow_redirects=True)
        assert res.status_code == 200
        assert b"Admin Dashboard" in res.data

    def test_admin_login_success(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.get("/admin")
        assert res.status_code == 200

    def test_analyze_page_requires_auth(self):
        res = self.client.get("/admin/analyze")
        assert res.status_code == 302

    def test_analyze_page_accessible_when_authed(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.get("/admin/analyze")
        assert res.status_code == 200
        assert b"Resume Analyzer" in res.data

    def test_analyze_api_requires_auth(self):
        res = self.client.post("/api/admin/analyze",
                               data={"jd_id": "java-developer"})
        assert res.status_code == 401

    def test_analyze_api_missing_jd(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.post("/api/admin/analyze", data={})
        assert res.status_code == 400

    def test_analyze_api_missing_resume(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.post("/api/admin/analyze",
                               data={"jd_id": "java-developer"})
        assert res.status_code == 400


# ── Resume Parser Tests (mocked LLM) ─────────────────────────

class TestResumeParser:
    """Test resume parsing with mocked LLM calls."""

    @patch("lib.resume_parser.anthropic.Anthropic")
    @patch("lib.resume_parser.log_api_usage")
    def test_extract_profile_success(self, mock_log, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "years_of_experience": 8,
            "current_role": "Senior Developer",
            "skills": {"languages": ["Java", "Python"]},
            "soft_skills_signals": [],
            "architecture_signals": [],
            "ownership_signals": [],
        })
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 200

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        from lib.resume_parser import extract_profile
        profile = extract_profile("John Doe - 8 years experience, Java, Python")
        assert profile["years_of_experience"] == 8
        assert "Java" in profile["skills"]["languages"]
        mock_log.assert_called_once()

    @patch("lib.resume_parser.anthropic.Anthropic")
    @patch("lib.resume_parser.log_api_usage")
    def test_extract_profile_bad_json(self, mock_log, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = "This is not JSON"
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        from lib.resume_parser import extract_profile
        profile = extract_profile("some resume text")
        assert "parse_error" in profile

    @patch("lib.resume_parser.anthropic.Anthropic")
    @patch("lib.resume_parser.log_api_usage")
    def test_extract_profile_strips_markdown_fences(self, mock_log, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '```json\n{"years_of_experience": 5, "current_role": null, "skills": {}}\n```'
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        from lib.resume_parser import extract_profile
        profile = extract_profile("resume text here")
        assert profile["years_of_experience"] == 5


# ── Match Scorer Tests (mocked LLM) ──────────────────────────

class TestMatchScorer:
    """Test compute_match with mocked LLM alignment call."""

    @patch("lib.match_scorer.get_role_alignment")
    def test_compute_match_strong(self, mock_alignment):
        mock_alignment.return_value = {
            "role_alignment_score": 85,
            "role_alignment_reason": "Great fit",
            "seniority_fit": "good_fit",
            "key_strengths": ["Java", "Microservices"],
            "key_gaps": [],
            "overall_recommendation": "strong_match"
        }

        profile = {
            "years_of_experience": 14,
            "skills": {
                "languages": ["Java"],
                "frameworks": ["Spring Boot", "Spring"],
                "databases": ["PostgreSQL", "MongoDB"],
                "cloud": ["AWS"],
                "devops": ["Docker", "Kubernetes"],
                "other": ["REST APIs", "Microservices"],
            },
            "soft_skills_signals": ["mentoring", "leadership"],
            "architecture_signals": ["designed microservices", "system design"],
            "ownership_signals": ["led team of 8"],
        }

        jd = get_jd("java-architect")
        from lib.match_scorer import compute_match
        result = compute_match(profile, jd)
        assert result["overall_score"] >= 60
        assert "breakdown" in result
        assert "suggestions" in result

    @patch("lib.match_scorer.get_role_alignment")
    def test_compute_match_weak(self, mock_alignment):
        mock_alignment.return_value = {
            "role_alignment_score": 20,
            "role_alignment_reason": "Not a fit",
            "seniority_fit": "underqualified",
            "key_strengths": [],
            "key_gaps": ["Java", "Spring"],
            "overall_recommendation": "weak_match"
        }

        profile = {
            "years_of_experience": 1,
            "skills": {"languages": ["Python"]},
            "soft_skills_signals": [],
            "architecture_signals": [],
            "ownership_signals": [],
        }

        jd = get_jd("java-architect")
        from lib.match_scorer import compute_match
        result = compute_match(profile, jd)
        assert result["overall_score"] <= 40


# ── Safe Int Helper Test ──────────────────────────────────────

def test_safe_int():
    from app import safe_int
    assert safe_int("5") == 5
    assert safe_int("five") is None
    assert safe_int("") is None
    assert safe_int(None) is None
    assert safe_int("3.5") is None
    assert safe_int("0") == 0


# ── JD CRUD Tests ────────────────────────────────────────────

class TestJdCrud:
    """Tests for JD creation and management."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        import lib.database as db_mod
        self.orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.tmp.name
        db_mod.init_db()

    def teardown_method(self):
        import lib.database as db_mod
        db_mod.DB_PATH = self.orig_path
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_save_and_get_jd(self):
        import lib.database as db
        jd_id = db.save_jd({
            "id": "python-dev",
            "title": "Python Developer",
            "location": "Bangalore",
            "mode": "Remote",
            "experience": "3 to 5 years",
            "experience_min": 3,
            "experience_max": 5,
            "must_have": ["Python", "Django"],
            "good_to_have": ["Docker"],
            "soft_skills": ["Communication"],
            "responsibilities": ["Write code"],
        })
        assert jd_id == "python-dev"
        jd = db.get_db_jd("python-dev")
        assert jd is not None
        assert jd["title"] == "Python Developer"
        assert jd["must_have"] == ["Python", "Django"]

    def test_get_all_db_jds(self):
        import lib.database as db
        db.save_jd({
            "id": "test-role", "title": "Test", "location": "X",
            "mode": "Remote", "experience": "1 year", "experience_min": 1,
            "must_have": ["A"],
        })
        all_jds = db.get_all_db_jds()
        assert any(j["id"] == "test-role" for j in all_jds)

    def test_delete_jd(self):
        import lib.database as db
        db.save_jd({
            "id": "to-delete", "title": "Delete Me", "location": "X",
            "mode": "Onsite", "experience": "2 years", "experience_min": 2,
            "must_have": ["B"],
        })
        assert db.jd_id_exists_in_db("to-delete") is True
        assert db.delete_jd("to-delete") is True
        assert db.jd_id_exists_in_db("to-delete") is False

    def test_jd_id_not_found(self):
        import lib.database as db
        assert db.get_db_jd("nonexistent") is None


class TestJdApi:
    """Integration tests for JD creation API."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        import lib.database as db_mod
        self.orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.tmp.name
        db_mod.init_db()
        from app import app
        app.config["TESTING"] = True
        self.client = app.test_client()

    def teardown_method(self):
        import lib.database as db_mod
        db_mod.DB_PATH = self.orig_path
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_create_jd_requires_auth(self):
        res = self.client.post("/api/admin/jds",
                               json={"title": "Test"},
                               content_type="application/json")
        assert res.status_code == 401

    def test_create_jd_missing_fields(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.post("/api/admin/jds",
                               json={"title": "Test Role"},
                               content_type="application/json")
        assert res.status_code == 400

    def test_create_jd_success(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.post("/api/admin/jds", json={
            "title": "React Developer",
            "location": "Mumbai",
            "mode": "Hybrid",
            "experience": "3 to 5 years",
            "experience_min": 3,
            "experience_max": 5,
            "must_have": ["React", "JavaScript", "TypeScript"],
            "good_to_have": ["Next.js"],
            "soft_skills": ["Communication"],
            "responsibilities": ["Build UIs"],
        }, content_type="application/json")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "created"
        assert data["id"] == "react-developer"

    def test_created_jd_appears_on_homepage(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        self.client.post("/api/admin/jds", json={
            "title": "Go Engineer",
            "location": "Remote",
            "mode": "Remote",
            "experience": "2+ years",
            "experience_min": 2,
            "must_have": ["Go", "gRPC"],
        }, content_type="application/json")
        res = self.client.get("/")
        assert b"Go Engineer" in res.data

    def test_created_jd_chat_page_works(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        self.client.post("/api/admin/jds", json={
            "title": "Data Analyst",
            "location": "Delhi",
            "mode": "Onsite",
            "experience": "1 to 3 years",
            "experience_min": 1,
            "must_have": ["SQL", "Python"],
        }, content_type="application/json")
        res = self.client.get("/chat/data-analyst")
        assert res.status_code == 200
        assert b"Data Analyst" in res.data

    def test_delete_builtin_jd_blocked(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.delete("/api/admin/jds/java-architect")
        assert res.status_code == 403

    def test_jd_list_page(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
        res = self.client.get("/admin/jds")
        assert res.status_code == 200
        assert b"Manage Job Roles" in res.data


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
