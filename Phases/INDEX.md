# Calling Agent — Phase Plan Index

**Project:** Ultimate Smile Design — free-tier AI voice calling agent (inbound lead intake, dentist-network routing, FAQ handling), built to validate the concept before any paid infrastructure is adopted.
(Python 3.12 + FastAPI, Pipecat voice-agent orchestration, Twilio Voice (trial) for telephony, Deepgram for STT, ElevenLabs for TTS, Claude/Gemini/OpenAI free-tier for the LLM, PostgreSQL or SQLite, Redis optional.)

**Company context:** Ultimate Smile Design (ultimatesmiledesign.com) is a nationwide directory/network connecting patients to certified "Smile Designer" dentists across 25+ Indian cities (Ahmedabad, Surat, Rajkot, Mumbai, Jamnagar, Indore, and more). It is a sister brand of Advance Dental Export Pvt Ltd (advancedentalexport.com), the parent dental-lab company. This matters for scope: v1 of the agent is a **lead-intake and routing** tool, not a single-clinic scheduler — there is no existing public appointment API to book directly into.

**Deployment:** native — Python venv, host-installed PostgreSQL/Redis (SQLite is fine for v1), uvicorn/gunicorn behind nginx, systemd units. No Docker in v1, mirroring the approach in your VAPT Central plan — called out as swappable later if the team prefers containers.

**Source of truth:** this INDEX.md and the phase files below. There is no pre-existing plan PDF for this project; the phases are original to this planning session, adapted from the VAPT Central phase-plan format you provided as the template.

**Total estimated duration:** ~22–27 working days for Phases 0–9 (the MVP). Phase 10 (migrating off third-party services) is a post-validation initiative, not part of the MVP timeline.

---

## Phase table

| #  | Phase | Duration | Depends on | File |
|----|-------|----------|------------|------|
| 0  | Project bootstrap & free-tier accounts | 1 day | — | [PHASE_00_project_bootstrap.md](PHASE_00_project_bootstrap.md) |
| 1  | Telephony integration (inbound calls) | 2 days | 0 | [PHASE_01_telephony_integration.md](PHASE_01_telephony_integration.md) |
| 2  | Speech pipeline (STT + TTS, standalone) | 2–3 days | 0 | [PHASE_02_speech_pipeline.md](PHASE_02_speech_pipeline.md) |
| 3  | Conversational core (LLM brain, text-only) | 3 days | 0 | [PHASE_03_conversational_core.md](PHASE_03_conversational_core.md) |
| 4  | Dentist directory & lead data model | 2 days | 3 | [PHASE_04_directory_lead_data.md](PHASE_04_directory_lead_data.md) |
| 5  | Real-time orchestration (join 1+2+3+4) | 4–5 days | 1, 2, 3, 4 | [PHASE_05_realtime_orchestration.md](PHASE_05_realtime_orchestration.md) |
| 6  | Outbound follow-up calls | 2 days | 5 | [PHASE_06_outbound_followup.md](PHASE_06_outbound_followup.md) |
| 7  | Lead capture & staff handoff | 2 days | 5 | [PHASE_07_lead_capture_handoff.md](PHASE_07_lead_capture_handoff.md) |
| 8  | Testing, QA & call analytics | 2–3 days | 6, 7 | [PHASE_08_testing_qa_analytics.md](PHASE_08_testing_qa_analytics.md) |
| 9  | Hardening & free-tier deployment | 2–3 days | 8 | [PHASE_09_hardening_deploy.md](PHASE_09_hardening_deploy.md) |
| 10 | Migration off third-party services | variable | 9, and business sign-off that v1 "succeeded" | [PHASE_10_thirdparty_migration.md](PHASE_10_thirdparty_migration.md) |

---

## Cross-cutting references

- **Pipecat** (voice-agent orchestration framework, has a built-in Twilio Media Streams transport): https://github.com/pipecat-ai/pipecat
- **Twilio Voice + Media Streams:** https://www.twilio.com/docs/voice/media-streams
- **Twilio trial account limitations** (calls/SMS restricted to verified numbers until upgraded): https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account
- **Deepgram streaming STT:** https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio
- **ElevenLabs TTS API:** https://elevenlabs.io/docs/api-reference/text-to-speech
- **Exotel** (India-specific telephony alternative to Twilio, worth a cost/latency comparison before committing): https://exotel.com
- **Ollama** (self-hosted LLM option for Phase 10): https://ollama.com
- **faster-whisper** (self-hosted STT option for Phase 10): https://github.com/SYSTRAN/faster-whisper
- **Coqui TTS / Piper** (self-hosted TTS options for Phase 10): https://github.com/coqui-ai/TTS · https://github.com/rhasspy/piper

---

## Risks & open questions (apply across multiple phases)

1. **Real-time latency budget.** Total round-trip (STT → LLM → TTS → back through Twilio) needs to stay under roughly 1.2–1.5s or the conversation feels unnatural and callers talk over the agent. Budget real tuning time for this in Phase 5.
2. **Free-tier ceilings.** Twilio trial numbers can only call/receive verified numbers until the account is upgraded; Deepgram and ElevenLabs free tiers have limited minutes/characters. Track usage from day one so you know when you'll hit the cap during testing, well before deciding to go paid.
3. **No live booking API.** Ultimate Smile Design's public site doesn't expose an appointment-booking API. v1 assumes the agent captures a lead (name, phone, city, intent) and a human team follows up — it does not book a live slot. If an internal scheduling system exists, that changes Phase 4/5 significantly — worth confirming with the business early.
4. **Barge-in / interruption handling.** A caller talking over the agent's TTS playback needs to interrupt cleanly; naive pipelines produce awkward overlap or the agent talking over the caller. Addressed explicitly in Phase 5.
5. **Call recording consent.** Add a brief recording/AI-disclosure line at the start of every call — good practice generally, and expected in most jurisdictions.
6. **Directory data drift.** The dentist-by-city list used by the agent (Phase 4) will drift from the live website over time. v1 solves this with a manually-updatable file/table and flags it as needing an owner, not with live scraping.
7. **Language coverage.** Given the target cities (Ahmedabad, Surat, Rajkot, Bharuch, Bhavnagar, Jamnagar — largely Gujarat) and the typical caller mix, English-only STT/TTS may frustrate some callers who mix in Hindi/Gujarati. Deepgram's Nova-2 model has Hindi support; evaluate this in Phase 2 rather than discovering it live.
8. **Outbound-calling compliance.** India's DND/TRAI rules apply to outbound calls. Phase 6 restricts outbound calls to numbers that explicitly requested a callback — never a cold list.
9. **Migration path.** Captured in full in Phase 10 — this is the "once it succeeds, drop the third-party pieces" plan you asked for, and it's treated as a real phase with its own risks, not an afterthought.
