# Phase 10 — Migration off third-party services (once validated) (variable — plan, not a sprint)

## 1. Objective
This is the phase you asked for explicitly: once the free MVP proves the concept, replace paid/third-party pieces with self-hosted or owned equivalents — one layer at a time, without breaking the working agent.

## 2. Prerequisites
- Phase 9 deployed and stable; the business has agreed the v1 concept "worked" and is worth investing further in.

## 3. Scope — In (a menu, tackled in this order — cheapest and highest-value first)
1. **LLM:** swap the API-based model for a self-hosted Ollama model (7–8B parameters is workable on CPU; larger if GPU is available) once the conversation design from Phase 3 is stable and well-tested. This mirrors the same provider-swap approach used in your VAPT Central plan's AI layer.
2. **TTS:** move from ElevenLabs to an open-source engine (Coqui TTS or Piper). This is the biggest quality trade-off of the five — validate with real callers before fully committing, not just internally.
3. **STT:** move from Deepgram to self-hosted Whisper (via `faster-whisper`) — generally the most achievable swap with the smallest quality gap, given reasonable CPU/GPU.
4. **Telephony:** the hardest of the five to fully self-host — it requires SIP trunking and carrier relationships, not just software. Realistically, most teams keep a telephony provider (Twilio, Exotel, or a cheaper SIP trunk) even after "going paid," and optimize cost here rather than eliminating the vendor entirely. Document this honestly rather than promising full removal of this layer.
5. **Hosting:** move from the Phase 9 free-tier host to owned or company infrastructure once call volume justifies the cost.

## 4. Scope — Out
- Doing all five swaps at once. Swap and validate one layer at a time so any regression in quality or latency is traceable to a specific change.

## 5. Files to create / modify
```
docs/
└── migration_log.md    # one entry per swapped component: date, before/after cost, latency, quality notes
```

## 6. Data model slice
No schema changes — this phase is an infrastructure swap, not a feature change.

## 7. API surface
Unchanged from the caller's perspective — the goal is that nobody calling in notices anything changed.

## 8. Frontend routes / components
N/A.

## 9. External integrations (this phase)
Being removed, one at a time: Deepgram, ElevenLabs, the chosen LLM API, and (partially, per the note above) the telephony provider.

## 10. Acceptance — "Done when"
For each component swapped: a side-by-side comparison (cost, latency, call-quality) is documented in `migration_log.md` before that vendor's API key is deleted — not after.

## 11. Risks & open questions
- **Compute cost isn't zero, it's just different.** Self-hosted STT/TTS/LLM need real compute, ideally a GPU — the "free" version of this phase is CPU-only and noticeably slower. Budget for either patience or a small GPU box once past validation; this phase trades a per-minute vendor bill for a hardware/hosting bill, it doesn't eliminate cost entirely.
- **Telephony realistically doesn't fully go away** — see item 4 above. Set that expectation with the business now, rather than after they've been told "we'll remove all third-party services."

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
- Ollama: https://ollama.com · faster-whisper: https://github.com/SYSTRAN/faster-whisper · Coqui TTS: https://github.com/coqui-ai/TTS · Piper: https://github.com/rhasspy/piper
