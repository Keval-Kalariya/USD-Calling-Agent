# Phase 0 — Project bootstrap & free-tier accounts (1 day)

## 1. Objective
Stand up the empty repo, a minimal FastAPI health endpoint, and every free-tier account this project needs — with keys wired into `.env` — so Phase 1 can place a real (if trivial) phone call on day one.

## 2. Prerequisites
- Python 3.12+ installed locally.
- Free-tier accounts to create now (all $0 to start):
  - **Twilio** — trial account, verify your own phone number, claim a free trial Voice-capable number.
  - **Deepgram** — free credits, generate an API key.
  - **ElevenLabs** — free tier, generate an API key (Deepgram Aura is a fallback if you'd rather consolidate vendors).
  - **Claude / Gemini / OpenAI** — API key for whichever provider you already have credits on; pick ONE as the v1 "brain" (see Risks below).
  - **ngrok** — free tier, for exposing your local dev server to Twilio's webhooks.
- A Git host (GitHub or similar) for the repo.

## 3. Scope — In
- `git init`; repo layout:
  ```
  backend/        # FastAPI app
  agent/          # Pipecat pipeline code (Phase 5+)
  data/           # dentist directory, seeded in Phase 4
  scripts/        # one-off test/utility scripts
  ```
- Python venv at `backend/.venv`; dependencies in `backend/pyproject.toml`: `fastapi`, `uvicorn`, `pipecat-ai`, `twilio`, `deepgram-sdk`, `elevenlabs`, plus whichever of `anthropic` / `google-generativeai` / `openai` you chose, and `pydantic-settings` for config.
- `.env.example` (committed) + `.env` (gitignored): `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `LLM_PROVIDER`, `LLM_API_KEY`.
- `Makefile` targets: `make install` (venv + deps), `make dev` (uvicorn --reload, plus ngrok in a second terminal or via `honcho`).
- `GET /health` endpoint returning `{"status": "ok"}`.
- A tiny `scripts/check_keys.py` that pings each vendor's cheapest read-only endpoint (e.g. list models / account info) to confirm every key actually works before you build on top of it.

## 4. Scope — Out (deferred)
- Any real call handling → Phase 1.
- STT/TTS wiring → Phase 2.
- LLM prompt/brain → Phase 3.

## 5. Files to create / modify
```
calling-agent/
├── README.md                 # install + dev quickstart
├── Makefile
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── .venv/                # gitignored
│   └── app/
│       ├── main.py           # FastAPI app, GET /health
│       └── settings.py       # pydantic-settings config
├── agent/                     # empty stub, fleshed out from Phase 5
├── data/                       # empty stub, seeded in Phase 4
└── scripts/
    └── check_keys.py
```

## 6. Data model slice
None yet — no database in this phase.

## 7. API surface
```
GET /health   →  200 {"status": "ok"}
```

## 8. Frontend routes / components
N/A — this project has no end-user frontend in v1; any later admin view is a lightweight read-only page added in Phase 7/8.

## 9. External integrations (this phase)
Account creation and key validation only — no real Twilio call, no real STT/TTS/LLM call beyond `check_keys.py`'s smoke test.

## 10. Acceptance — "Done when"
- `curl http://127.0.0.1:8000/health` → 200 `{"status":"ok"}`.
- `python scripts/check_keys.py` reports all five vendor keys as valid.
- ngrok tunnel forwards a public URL to the local server.
- README documents install steps and the two dev commands.

## 11. Risks & open questions
- **Pick ONE LLM provider for the live pipeline now**, even though you may hold multiple keys — switching providers mid-call adds format/latency inconsistency. Document the choice and why (cost, free-tier ceiling, latency you've observed elsewhere).
- **Twilio trial limitations** apply from the moment you claim a number — note this now so Phase 1 isn't a surprise (see INDEX.md risk #2).

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
