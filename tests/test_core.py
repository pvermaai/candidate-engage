"""
Tests for key logic: match scoring, confidence gate, skill matching.
Run: python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lib.match_scorer import skill_matches, score_experience, score_skills, get_all_resume_skills
from lib.confidence_gate import pre_screen
from lib.jds import get_jd


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


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
