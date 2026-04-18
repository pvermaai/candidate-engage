"""
Confidence gate — lightweight pre-screening layer that catches known
out-of-scope topics before they reach the LLM. This saves tokens on
obvious cases and provides a safety net on top of the prompt-level
confidence protocol.
"""

import re

# Patterns that indicate out-of-scope topics
OUT_OF_SCOPE_PATTERNS = [
    (re.compile(r"\b(salary|salaries|compensation|ctc|package|pay\s?band|stipend|wage)\b", re.I),
     "compensation",
     "I appreciate your interest! Compensation details are discussed directly with our recruitment team during the interview process. I can tell you more about the role itself, the skills involved, or what it's like working at Wissen — what would you like to know?"),

    (re.compile(r"\b(visa|h1b|h-1b|work\s*permit|sponsorship|green\s*card|immigration)\b", re.I),
     "visa",
     "Great question — visa and work authorization details are best discussed with our HR team, as policies can vary by location and role. I can help with questions about the role, required skills, or Wissen's work culture. What else can I help with?"),

    (re.compile(r"\b(stock|equity|esop|rsu|options|vesting|shares)\b", re.I),
     "equity",
     "Equity and stock-related details are part of the offer discussion with our recruitment team. I'm happy to answer questions about the role, tech stack, or Wissen's engineering culture!"),

    (re.compile(r"\b(layoff|laid\s*off|fire|fired|terminat|retrench|downsiz)\b", re.I),
     "sensitive_hr",
     "That's a sensitive topic best addressed by our HR team directly. I can help with information about the role, the tech stack, or what working at Wissen is like. What would you like to explore?"),

    (re.compile(r"\b(compare|comparison|vs\.?|versus|better\s+than|worse\s+than).{0,30}(infosys|tcs|wipro|cognizant|accenture|hcl|tech\s*mahindra|capgemini|deloitte|competitor)\b", re.I),
     "competitor_comparison",
     "I'd prefer to focus on what makes Wissen unique rather than comparisons. Wissen is a product engineering company with a focus on complex, mission-critical systems and an engineering-first culture. Want me to tell you more about what sets us apart?"),
]

# Patterns that need extra context injection but are still sent to LLM
SENSITIVE_PATTERNS = [
    (re.compile(r"\b(interview|rounds|process|stages|hiring\s*process)\b", re.I),
     "interview_process"),
    (re.compile(r"\b(notice\s*period|joining\s*date|start\s*date|when\s*can\s*i\s*join)\b", re.I),
     "joining"),
    (re.compile(r"\b(wfh|work\s*from\s*home|remote|onsite|office\s*days)\b", re.I),
     "work_mode"),
]


def pre_screen(message: str) -> dict:
    """
    Pre-screen a candidate message. Returns:
    {
        "allowed": bool — whether to send to LLM,
        "redirect_response": str | None — if not allowed, the canned response,
        "category": str | None — the matched category,
        "hints": list[str] — extra context hints to inject into the prompt
    }
    """
    result = {
        "allowed": True,
        "redirect_response": None,
        "category": None,
        "hints": []
    }

    # Check hard out-of-scope patterns
    for pattern, category, response in OUT_OF_SCOPE_PATTERNS:
        if pattern.search(message):
            result["allowed"] = False
            result["redirect_response"] = response
            result["category"] = category
            return result

    # Check soft sensitive patterns — still send to LLM but with hints
    for pattern, category in SENSITIVE_PATTERNS:
        if pattern.search(message):
            result["hints"].append(category)

    return result
