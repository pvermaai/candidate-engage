"""
Match scoring engine — hybrid deterministic + LLM approach.
- Deterministic: skill matching, experience scoring, location scoring
- LLM-assisted: role alignment / seniority fit (one cheap call)

Produces an explainable, auditable score with per-category breakdown.
"""

import json
import anthropic
from lib.prompts import build_match_scoring_prompt
from lib.database import log_api_usage

# ── Skill aliases for fuzzy matching ──────────────────────────────
ALIASES = {
    "java8": ["java 8", "java8", "java 11", "java11", "java 17", "java17", "java 21", "java21", "java8+", "java 8+"],
    "core java": ["core java", "java", "java se"],
    "spring boot": ["spring boot", "springboot", "spring-boot"],
    "spring": ["spring", "spring framework", "spring mvc"],
    "microservices": ["microservices", "micro services", "micro-services", "microservice"],
    "rest apis": ["rest", "rest api", "rest apis", "restful", "restful api", "restful apis"],
    "hibernate / jpa": ["hibernate", "jpa", "hibernate/jpa", "hibernate / jpa", "jakarta persistence"],
    "sql databases": ["sql", "mysql", "postgresql", "postgres", "oracle", "sql server", "mssql", "rdbms"],
    "nosql databases": ["nosql", "mongodb", "mongo", "cassandra", "dynamodb", "redis", "couchbase", "nosql databases"],
    "docker": ["docker", "containers", "containerization", "docker compose"],
    "kubernetes": ["kubernetes", "k8s", "kube", "aks", "eks", "gke"],
    "aws / azure / gcp (any one)": ["aws", "azure", "gcp", "amazon web services", "google cloud", "cloud"],
    "kafka / rabbitmq": ["kafka", "rabbitmq", "rabbit mq", "apache kafka", "event-driven"],
    "ci/cd pipelines": ["ci/cd", "cicd", "ci cd", "continuous integration", "continuous deployment", "continuous delivery"],
    "jenkins": ["jenkins"],
    "git": ["git", "github", "gitlab", "bitbucket"],
    "design patterns": ["design patterns", "design pattern", "gang of four", "gof", "solid principles", "solid"],
    "domain-driven design (ddd)": ["ddd", "domain driven design", "domain-driven design"],
    "oauth2 / jwt": ["oauth", "oauth2", "jwt", "json web token", "authentication", "authorization"],
    "terraform / iac": ["terraform", "iac", "infrastructure as code", "cloudformation", "pulumi"],
    "object-oriented programming (oop)": ["oop", "object oriented", "object-oriented", "oops"],
    "data structures & algorithms (dsa)": ["dsa", "data structures", "algorithms", "data structures and algorithms"],
    "debugging & troubleshooting": ["debugging", "troubleshooting", "problem solving", "root cause analysis"],
    "unit testing (junit, mockito)": ["junit", "mockito", "unit testing", "unit tests", "testing"],
    "agile / scrum": ["agile", "scrum", "sprint", "kanban", "jira"],
}


def normalize(text: str) -> str:
    return text.lower().strip().replace("–", "-").replace("—", "-")


import re as _re

def _compact(text: str) -> str:
    """Strip all non-alphanumeric for alias lookups."""
    return _re.sub(r"[^a-z0-9]", "", text.lower())


def skill_matches(resume_skills: list[str], jd_skill: str) -> bool:
    """Check if any resume skill matches a JD skill using aliases."""
    jd_norm = normalize(jd_skill)
    resume_norms = [normalize(s) for s in resume_skills]

    # Direct containment check
    for rs in resume_norms:
        if jd_norm in rs or rs in jd_norm:
            return True

    # Compact alias-based matching (strips spaces/symbols for things like "Java 8+" vs "java17")
    jd_compact = _compact(jd_skill)
    resume_compacts = [_compact(s) for s in resume_skills]

    # Look up aliases using the compact key
    alias_list = ALIASES.get(jd_norm, None) or ALIASES.get(jd_compact, [jd_norm])
    for alias in alias_list:
        alias_c = _compact(alias)
        for rc in resume_compacts:
            if alias_c in rc or rc in alias_c:
                return True

    return False


def get_all_resume_skills(profile: dict) -> list[str]:
    """Flatten all skill categories from extracted profile into one list."""
    skills = profile.get("skills") or {}
    all_skills = []
    for category_skills in skills.values():
        if isinstance(category_skills, list):
            all_skills.extend(category_skills)
    all_skills.extend(profile.get("architecture_signals") or [])
    all_skills.extend(profile.get("soft_skills_signals") or [])
    all_skills.extend(profile.get("ownership_signals") or [])
    return all_skills


def score_experience(candidate_years, jd: dict) -> int:
    """Score experience match (0-100)."""
    try:
        candidate_years = int(candidate_years) if candidate_years is not None else None
    except (ValueError, TypeError):
        candidate_years = None

    if candidate_years is None:
        return 30  # Unknown, give partial credit

    min_req = int(jd.get("experience_min") or 0)
    max_req = int(jd.get("experience_max") or (min_req + 5))

    if min_req <= candidate_years <= max_req:
        return 100
    elif candidate_years > max_req:
        # Overqualified but not a dealbreaker
        overshoot = candidate_years - max_req
        return max(70, 100 - overshoot * 5)
    else:
        # Underqualified
        gap = min_req - candidate_years
        if gap <= 1:
            return 75
        elif gap <= 3:
            return 50
        elif gap <= 5:
            return 30
        else:
            return 10


def score_skills(resume_skills: list[str], jd_skills: list[str]) -> tuple[int, list[str], list[str]]:
    """Score skill match, return (score, matched, missing)."""
    matched = []
    missing = []
    for skill in jd_skills:
        if skill_matches(resume_skills, skill):
            matched.append(skill)
        else:
            missing.append(skill)

    if not jd_skills:
        return 50, matched, missing

    score = int((len(matched) / len(jd_skills)) * 100)
    return score, matched, missing


def score_soft_skills(profile: dict, jd: dict) -> int:
    """Score soft skills match."""
    signals = profile.get("soft_skills_signals") or []
    ownership = profile.get("ownership_signals") or []
    all_signals = signals + ownership

    if not all_signals:
        return 30  # No signals found

    jd_soft = jd.get("soft_skills") or []
    if not jd_soft:
        return 50

    matches = 0
    for jd_skill in jd_soft:
        jd_norm = normalize(jd_skill)
        for signal in all_signals:
            if any(word in normalize(signal) for word in jd_norm.split()):
                matches += 1
                break

    return min(100, int((matches / len(jd_soft)) * 100) + 20)  # +20 baseline for having any signals


def get_role_alignment(profile: dict, jd: dict) -> dict:
    """Use LLM to assess role alignment — one cheap API call."""
    try:
        client = anthropic.Anthropic()
        prompt = build_match_scoring_prompt(profile, jd)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        log_api_usage(
            "match_alignment",
            response.usage.input_tokens,
            response.usage.output_tokens,
            "claude-sonnet-4-20250514"
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]

        return json.loads(raw.strip())
    except Exception as e:
        return {
            "role_alignment_score": 50,
            "role_alignment_reason": "Could not assess role alignment",
            "seniority_fit": "unknown",
            "key_strengths": [],
            "key_gaps": [],
            "overall_recommendation": "partial_match"
        }


def compute_match(profile: dict, jd: dict) -> dict:
    """
    Full match scoring pipeline.
    Weights:
      - Must-have skills:  35%
      - Experience:         20%
      - Good-to-have:       15%
      - Role alignment:     10%
      - Soft skills:        10%
      - Architecture/depth: 10%
    """
    resume_skills = get_all_resume_skills(profile)

    must_score, must_matched, must_missing = score_skills(
        resume_skills, jd.get("must_have") or [])

    gth_score, gth_matched, gth_missing = score_skills(
        resume_skills, jd.get("good_to_have") or [])

    exp_score = score_experience(profile.get("years_of_experience"), jd)

    soft_score = score_soft_skills(profile, jd)

    arch_signals = profile.get("architecture_signals") or []
    arch_score = min(100, len(arch_signals) * 25) if arch_signals else 20

    alignment = get_role_alignment(profile, jd)
    role_score = alignment.get("role_alignment_score") or 50
    if not isinstance(role_score, (int, float)):
        try:
            role_score = int(role_score)
        except (ValueError, TypeError):
            role_score = 50

    total = (
        must_score * 0.35 +
        exp_score * 0.20 +
        gth_score * 0.15 +
        role_score * 0.10 +
        soft_score * 0.10 +
        arch_score * 0.10
    )

    suggestions = []
    if must_missing:
        suggestions.append(f"Consider highlighting experience with: {', '.join(must_missing[:4])}")
    if exp_score < 50:
        suggestions.append(f"The role requires {jd.get('experience', 'relevant')} of experience")
    if gth_missing:
        suggestions.append(f"Nice-to-have skills to develop: {', '.join(gth_missing[:3])}")
    if not arch_signals and "architect" in (jd.get("title") or "").lower():
        suggestions.append("Highlight any architecture or system design experience")

    return {
        "overall_score": round(total),
        "breakdown": {
            "must_have_skills": {
                "score": must_score,
                "weight": "35%",
                "matched": must_matched,
                "missing": must_missing
            },
            "experience": {
                "score": exp_score,
                "weight": "20%",
                "candidate_years": profile.get("years_of_experience"),
                "required": jd.get("experience", "Not specified")
            },
            "good_to_have": {
                "score": gth_score,
                "weight": "15%",
                "matched": gth_matched,
                "missing": gth_missing
            },
            "role_alignment": {
                "score": role_score,
                "weight": "10%",
                "seniority_fit": alignment.get("seniority_fit") or "unknown",
                "reason": alignment.get("role_alignment_reason") or ""
            },
            "soft_skills": {
                "score": soft_score,
                "weight": "10%",
                "signals_found": profile.get("soft_skills_signals") or []
            },
            "architecture_depth": {
                "score": arch_score,
                "weight": "10%",
                "signals_found": arch_signals
            }
        },
        "key_strengths": alignment.get("key_strengths") or must_matched[:3],
        "key_gaps": alignment.get("key_gaps") or must_missing[:3],
        "recommendation": alignment.get("overall_recommendation") or "partial_match",
        "suggestions": suggestions
    }
