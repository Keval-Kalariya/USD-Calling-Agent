# Ultimate Smile Design (USD) Calling Agent - Project Handoff

## Project Overview
You are building an AI voice calling agent named **Kiara** for Ultimate Smile Design (ultimatesmiledesign.com), a nationwide dental network in India.
The agent acts as an **Elite Concierge** targeting high-net-worth individuals. Her goal is to build luxury value, check city coverage, and capture lead details (Name, Phone, City) for a human patient care team callback. She speaks three languages seamlessly: English, Hindi, and Gujarati.

## Architecture & Tech Stack
- **Model:** Google Gemini (exclusively via the official `google-genai` SDK). No OpenAI or Anthropic fallbacks.
- **Speech:** Deepgram (STT) and ElevenLabs (TTS).
- **Telephony:** Twilio (Media Streams WebSockets).
- **Backend:** FastAPI (managed by Honcho/Uvicorn).
- **Current Data Store:** JSON files (`data/covered_cities.json`, `data/leads.json`).

## What Has Been Completed (Phases 0-6)
1. **Phase 0 (Base Setup):** FastAPI backend, virtual environment, Makefile, Honcho Procfile, `.env` management, and API key verification script (`scripts/check_keys.py`).
2. **Phase 1 (Telephony):** Twilio webhook and WebSocket endpoint boilerplate created in `backend/app/routes/twilio_voice.py`.
3. **Phase 2 (Speech Pipeline):** Deepgram STT and ElevenLabs TTS tested individually for trilingual support (English, Hindi, Gujarati).
4. **Phase 3 (Conversational Core):** `agent/cli_harness.py` fully implemented using the native Gemini agentic tool-calling loop.
5. **Phase 4 (Elite Persona & Business Logic):** 
    - Injected the new Elite Concierge prompt into `agent/prompts/system_prompt.md`.
    - Implemented `agent/tools/check_city_coverage.py` checking against `data/covered_cities.json`.
    - Implemented `agent/tools/capture_lead.py` saving to `data/leads.json` (requires name, phone, city).
    - Removed old "Dentist Lookup" logic to maintain exclusivity.
6. **Phase 5 (Connecting the Pipeline):**
    - Built a Pipecat Voice Pipeline in `agent/pipeline.py`.
    - Integrated Twilio WebSocket streaming with Deepgram STT, ElevenLabs TTS, and Silero VAD (barge-in).
    - Created `CustomGeminiLLMService` directly wrapping `google-genai` SDK (`gemini-2.5-flash`).
    - Added `agent/tools/handoff.py` for human escalation.
    - Updated data logging schemas: separated lead capture (`leads.json`) from per-call telemetry and transcripts (`calls.json`), and added usage metrics (`usage.json`).
    - Tested end-to-end with live Twilio outbound calls via `scripts/test_outbound_call.py`.
7. **Phase 6 (Outbound Follow-up):**
    - Created `backend/app/routes/internal_callback.py` providing the `POST /internal/trigger-callback` endpoint.
    - Added internal header security (`X-Internal-Key` verification against `INTERNAL_KEY`).
    - Implemented strict safety controls: `ALLOWED_NUMBERS` allow-list check and an in-memory 5-minute per-phone rate limit.
    - Integrated Twilio `client.calls.create` to originate outbound follow-up calls dynamically with custom `opening_intent=follow-up` parameters passing to `/twilio/voice`.
    - Extended `build_pipeline` in `agent/pipeline.py` to accept `opening_intent="follow-up"`, `lead_name`, and `lead_city`, custom-framing the opening call greeting (*"Hi {lead_name}, this is Kiara from Ultimate Smile Design, following up on your {lead_city} smile consultation enquiry..."*).
    - Maintained full call telemetry tracking for outbound calls (`direction = "outbound"`) in `data/calls.json`.

## Where We Left Off
We have completed Phase 6. Kiara can now seamlessly handle inbound calls and initiate secure, rate-limited outbound follow-up calls to leads using Twilio Media Streams and the real-time voice pipeline.

## Immediate Next Steps (Phase 7)
The next major objective is **Phase 7: Lead capture & staff handoff**.
We need to automatically notify staff when a lead is captured or handoff is triggered (via Email/SMTP, Telegram, or Webhook) and provide a read-only admin route/export script for captured leads. See `Phases/PHASE_07_lead_capture_handoff.md` for details.
