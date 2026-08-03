# Phase 5 — Real-time orchestration (4–5 days, the hard phase)

## 1. Objective
Join Phases 1–4 into one live pipeline: caller speaks → Twilio Media Stream → Deepgram STT → LLM (with tools) → ElevenLabs TTS → Twilio Media Stream → caller hears it — with natural turn-taking, not a stilted walkie-talkie exchange.

## 2. Prerequisites
- Phases 1 (telephony), 2 (speech pipeline components validated standalone), 3 (conversation design + tools), and 4 (real directory data) all complete.

## 3. Scope — In
- Adopt **Pipecat's Twilio transport** rather than hand-rolling the WebSocket/audio-frame plumbing yourself — it has a built-in Media Streams connector and handles a lot of the framing/format details Phase 1 flagged as a risk.
- **Voice Activity Detection (VAD)** so the pipeline knows when the caller has stopped talking, rather than guessing from silence timeouts alone.
- **Barge-in handling:** if the caller starts speaking while TTS is still playing, stop playback immediately rather than talking over them — this is the single biggest thing that makes or breaks how natural the call feels.
- **End-of-call handling:** hang up cleanly, persist the final transcript, and finalize the `Lead` record if one was captured.
- A **human-handoff tool**: when triggered (caller asks for a human, or the model is uncertain), politely take a callback number and end the call, or warm-transfer via Twilio if a live line is available.
- Promote the Phase 1 file-based call log into a real `Call` table with a `transcript` field.

## 4. Scope — Out (deferred)
- Outbound/follow-up calls → Phase 6.
- Analytics/dashboard → Phase 8.

## 5. Files to create / modify
```
agent/
├── pipeline.py           # Pipecat pipeline: Twilio transport + STT + LLM + TTS + VAD
└── handoff.py             # human handoff / callback tool
backend/app/
├── routes/twilio_voice.py   # media-stream endpoint now runs the full pipeline
└── models/call.py            # extended with transcript field
```

## 6. Data model slice
`Call` extended: `transcript` (text). `Lead.call_id` now reliably links back to the originating call.

## 7. API surface
`WS /twilio/media-stream` now runs the complete pipeline instead of the Phase 1 stub greeting.

## 8. Frontend routes / components
N/A this phase.

## 9. External integrations (this phase)
Twilio (Media Streams), Deepgram (streaming STT), the chosen LLM, ElevenLabs/Aura (TTS) — all live, all in one call, for the first time.

## 10. Acceptance — "Done when"
- An end-to-end test call: you call the Twilio number, have a real spoken conversation, ask "find a dentist in Surat," get a sensible spoken answer, and a `Lead` row is created with the correct city.
- Interrupting the agent mid-sentence stops its speech promptly and it responds to what you actually said.
- A caller who says "I want to speak to a human" gets a clean handoff/callback flow, not a dead end.

## 11. Risks & open questions
- **This is where free-tier latency stacks up.** STT + LLM + TTS + the Twilio hop, added together, is the real test of the ~1.2–1.5s budget flagged in INDEX.md risk #1. Budget real time in this phase purely for latency tuning (parallelizing where possible, streaming partial LLM output into TTS rather than waiting for the full response, etc.) — don't treat it as a one-line task.
- **Format mismatches** between Twilio's 8kHz mulaw and whatever your STT/TTS vendors expect natively can silently degrade quality rather than error loudly — verify audio quality by ear, not just "no exceptions thrown."

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
- Pipecat: https://github.com/pipecat-ai/pipecat
