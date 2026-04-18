# Wissen Recruit AI — Candidate Engagement Chatbot

> AI-powered candidate engagement platform anchored to Job Descriptions.
> Built for Wissen Technology Hackathon 2026 — Problem Statement #2.

---

## Quick Start

```bash
git clone <repo-url>
cd candidate-engage
pip install -r requirements.txt
cp .env.example .env       # Add your ANTHROPIC_API_KEY
python app.py               # → http://localhost:5000
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Candidate Browser                    │
│  JD Viewer  │  Chat (SSE streaming)  │  Apply Form  │
└──────┬──────────────┬────────────────────┬──────────┘
       │              │                    │
       ▼              ▼                    ▼
┌─────────────────────────────────────────────────────┐
│              Flask API Routes                        │
│                                                      │
│  /api/chat ──► Confidence Gate ──► Claude Sonnet 4   │
│                • JD in system prompt (no RAG)        │
│                • Streaming SSE                       │
│                                                      │
│  /api/interest ──► SQLite (candidate data)           │
│                                                      │
│  /api/resume ──► pdfplumber ──► Claude (extraction)  │
│              ──► Match Scorer (weighted rubric)       │
└──────────────────────┬──────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   Claude API      SQLite DB     File System
   (Sonnet 4)    (candidates)    (resumes)
```

---

## Key Design Decisions

### 1. No Vector DB / No RAG
JDs are under 2K tokens — they fit entirely in the system prompt. This gives us:
- 100% context recall (no retrieval misses)
- Zero embedding cost
- Zero retrieval latency
- Simpler architecture with fewer failure modes

### 2. Hybrid Match Scoring
LLM extracts structured data from resumes; deterministic code scores against a weighted rubric:

| Category | Weight |
|---|---|
| Must-have skills | 35% |
| Experience | 20% |
| Good-to-have skills | 15% |
| Role alignment (LLM) | 10% |
| Soft skills | 10% |
| Architecture depth | 10% |

This is **explainable** — every score shows matched skills, missing skills, and suggestions.

### 3. Confidence Gating (Two Layers)
- **Layer 1 (Server):** Regex pre-screening catches salary, visa, competitor questions → canned responses without calling the LLM (saves tokens)
- **Layer 2 (Prompt):** Three-tier confidence protocol (confident / partial / decline) in the system prompt prevents hallucination

### 4. Streaming Chat
Server-Sent Events (SSE) stream Claude's response token-by-token for a real-time typing effect.

### 5. API Cost Tracking
Every API call logs input/output tokens. Running cost is shown in the header. Demo-friendly: judges can see spend in real-time.

---

## Prompt Strategy

The system prompt (see `lib/prompts.py`) is structured with explicit sections:

1. **Identity** — Who the bot is, what company it represents
2. **Company Context** — Wissen facts the bot can reference
3. **Role Context** — Full JD with skills, responsibilities, requirements
4. **Behavioral Rules** — Grounding, scope boundaries, confidence protocol
5. **Tone Guidelines** — Professional but warm, concise, on-brand

The prompt uses **zero-shot grounding** — no few-shot examples needed because the JD context is explicit and exhaustive for the scope of questions.

---

## Project Structure

```
candidate-engage/
├── app.py                    # Flask app — all routes
├── lib/
│   ├── database.py           # SQLite setup + queries
│   ├── jds.py                # JD data registry
│   ├── prompts.py            # System prompt + extraction prompts
│   ├── confidence_gate.py    # Pre-screening layer
│   ├── resume_parser.py      # PDF → text → structured profile
│   └── match_scorer.py       # Weighted rubric scoring engine
├── templates/
│   ├── base.html             # Layout + Tailwind
│   ├── index.html            # JD selection page
│   ├── chat.html             # Chat + interest + resume
│   └── admin.html            # Admin dashboard
├── tests/
│   └── test_core.py          # Unit tests for scoring + gate
├── uploads/                  # Resume PDFs (gitignored)
├── candidates.db             # SQLite (auto-created)
├── requirements.txt
├── Dockerfile
├── Procfile
├── .env.example
└── README.md
```

---

## API Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | JD selection landing page |
| `/chat/<jd_id>` | GET | Chat page for a specific JD |
| `/admin` | GET | Admin dashboard |
| `/api/jds` | GET | List available JDs |
| `/api/chat` | POST | Send message → streaming response |
| `/api/interest` | POST | Submit candidate interest + resume |
| `/api/usage` | GET | API token usage + cost estimate |
| `/api/admin/candidates` | GET | List all candidates (JSON) |
| `/api/admin/candidate/<id>` | GET | Candidate detail (JSON) |

---

## Cost Analysis

| Action | Est. Tokens | Est. Cost |
|---|---|---|
| Chat message (single turn) | ~2500 in + ~300 out | ~$0.012 |
| Chat message (cached system prompt) | ~500 in + ~300 out | ~$0.006 |
| Resume extraction | ~2000 in + ~500 out | ~$0.014 |
| Match alignment | ~1000 in + ~200 out | ~$0.006 |
| **Full demo (10 chat + 1 resume)** | — | **~$0.08** |

---

## Deployment

### Option A: Render (Recommended)
1. Push to GitHub
2. Create a new **Web Service** on [render.com](https://render.com)
3. Connect your repo
4. Set environment: `ANTHROPIC_API_KEY`, `FLASK_SECRET_KEY`
5. Build command: `pip install -r requirements.txt`
6. Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app`
7. Deploy → live URL in ~2 minutes

### Option B: Docker
```bash
docker build -t wissen-recruit .
docker run -p 5000:5000 -e ANTHROPIC_API_KEY=sk-ant-... wissen-recruit
```

### Option C: Railway
1. Push to GitHub
2. New project → Deploy from GitHub
3. Add env variables
4. Auto-deploys on push

---

## Testing

```bash
python -m pytest tests/ -v
```

Tests cover: skill matching (aliases, fuzzy), experience scoring, confidence gate (blocked/allowed), profile extraction helpers.

---

## Demo Script (5 minutes)

**Minute 0–1:** Show architecture diagram + explain "no vector DB" decision

**Minute 1–3:** Live demo happy path
1. Open app → select Java Architect
2. Ask: "What skills are needed?" → grounded answer
3. Ask: "Tell me about Wissen's culture" → company context
4. Ask: "Is remote work an option?" → JD-grounded answer
5. Click "I'm Interested!" → fill form → upload resume
6. Show match score breakdown

**Minute 3–4:** Edge cases
1. Ask: "What's the salary?" → graceful decline
2. Ask: "How does Wissen compare to TCS?" → redirect
3. Switch to Java Developer JD → different context

**Minute 4–5:** Technical highlights
- Show system prompt structure
- Show API cost in header
- Show admin dashboard with candidates
- Show match breakdown explainability

---

## Team

Built for Wissen Technology Hackathon 2026 — Problem Statement #2
