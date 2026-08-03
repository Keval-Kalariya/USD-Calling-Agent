# Phase 1 — Telephony integration (inbound calls) (2 days)

## 1. Objective
Get a real inbound phone call routed to your backend and hear a scripted response — no AI yet. This proves the phone ↔ webhook ↔ audio path end to end before anything smart is layered on.

## 2. Prerequisites
- Phase 0 complete: Twilio trial number claimed, ngrok running, `.env` populated.

## 3. Scope — In
- **Architecture decision (make this now, it shapes everything later):** use Twilio's `<Connect><Stream>` TwiML verb to open a bidirectional **Media Stream** WebSocket, rather than `<Record>` or `<Gather>`. This is required for the real-time, low-latency conversation built in Phase 5 — a turn-based `<Gather>` approach would mean rebuilding the whole call-handling layer later.
- `POST /twilio/voice` webhook: Twilio hits this when a call comes in; it returns TwiML pointing at your Media Stream WebSocket.
- `WS /twilio/media-stream`: receives base64-encoded 8kHz mulaw audio chunks from Twilio, and can send audio back on the same connection.
- A trivial script for this phase: answer the call, play a static pre-recorded "Thanks for calling Ultimate Smile Design" clip (no TTS yet), then hang up.
- Call logging: persist `call_sid`, direction, `from_number`, `to_number`, `started_at`, `ended_at`, `status` — a log file is fine for this phase; promoted to a real table in Phase 5.
- One outbound test: a script that tells Twilio to originate a call to your own verified number, confirming the account can also place calls (needed for Phase 6).

## 4. Scope — Out (deferred)
- STT, LLM, TTS → Phases 2, 3, 5.
- Real two-way conversation → Phase 5.

## 5. Files to create / modify
```
backend/app/
├── routes/
│   └── twilio_voice.py   # POST /twilio/voice, WS /twilio/media-stream
├── models/
│   └── call.py            # Call log dataclass/model (promoted to DB table in Phase 5)
└── static/
    └── welcome.wav         # scripted greeting for this phase's smoke test
scripts/
└── test_outbound_call.py
```

## 6. Data model slice
`Call` (id, twilio_call_sid, direction, from_number, to_number, started_at, ended_at, status) — file-backed or a stub table for now.

## 7. API surface
```
POST /twilio/voice          — Twilio webhook, returns TwiML
WS   /twilio/media-stream   — bidirectional audio stream
```

## 8. Frontend routes / components
N/A this phase.

## 9. External integrations (this phase)
Twilio Voice + Media Streams (inbound and one outbound test call).

## 10. Acceptance — "Done when"
- Calling your Twilio trial number rings and plays the welcome clip, then hangs up cleanly.
- A `Call` log entry appears for that call.
- The outbound test script successfully rings your own verified phone.

## 11. Risks & open questions
- **Trial account restriction:** Twilio trial numbers can only call or receive calls from *verified* numbers until the account is upgraded — fine for solo dev testing, but blocks testing with arbitrary third-party numbers. Note this before planning any wider test with colleagues.
- **Audio format lock-in:** Media Streams audio is 8kHz mulaw — every downstream component (Deepgram in Phase 2, ElevenLabs output in Phase 2/5) must either natively match this or be resampled; verify this explicitly rather than assuming.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
- Twilio Media Streams docs: https://www.twilio.com/docs/voice/media-streams
