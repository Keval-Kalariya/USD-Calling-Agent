# Phase 2 — Speech pipeline: STT + TTS, standalone (2–3 days)

## 1. Objective
Wire speech-to-text and text-to-speech in isolation — not yet joined to a live call — so you can judge quality and latency before combining everything in Phase 5. Cheaper to debug two simple scripts now than a live call pipeline later.

## 2. Prerequisites
- Phase 0's Deepgram and ElevenLabs keys validated.
- A short sample audio clip (mulaw or WAV) to test STT against, ideally including an English-with-Indian-accent sample if you have one handy.

## 3. Scope — In
- **STT:** a script using Deepgram's streaming API that feeds a sample audio file and prints live partial + final transcripts.
- **TTS:** a script that sends sample text to ElevenLabs (or Deepgram Aura, if you'd rather use one vendor for both directions) and saves/plays the resulting audio.
- **Latency benchmark:** log time-to-first-partial-transcript and time-to-first-audio-byte for both directions; write the numbers down.
- **Target budget to design against:** partial STT transcript within ~300ms of speech; first TTS audio byte within ~500ms of text being sent. These aren't hard requirements yet — they're the numbers Phase 5 will be tuned against.
- **Language check:** run the same STT test against a Hindi/Gujarati-accented English sample if available, and note the result in `CONVERSATION_DESIGN.md` (created properly in Phase 3) — this directly informs whether Deepgram's Nova-2 (which has Hindi support) is worth switching to before Phase 5.

## 4. Scope — Out (deferred)
- Hooking either component into the live phone call → Phase 5.
- The LLM in between → Phase 3.

## 5. Files to create / modify
```
scripts/
├── test_stt.py        # feed sample audio, print transcripts + timing
└── test_tts.py         # send sample text, save audio + timing
data/
└── samples/
    └── sample_call.wav
```

## 6. Data model slice
None new.

## 7. API surface
None new — throwaway scripts only, not endpoints.

## 8. Frontend routes / components
N/A this phase.

## 9. External integrations (this phase)
Deepgram (streaming STT) and ElevenLabs or Deepgram Aura (TTS), used directly from scripts, not through the live call path.

## 10. Acceptance — "Done when"
- `test_stt.py` correctly transcribes the sample clip and prints latency numbers.
- `test_tts.py` produces intelligible audio for a short sentence in under ~1 second, saved as a playable file.
- Latency numbers and the language-accuracy note are written down for Phase 3/5 to reference.

## 11. Risks & open questions
- **Free-tier ceilings:** both Deepgram and ElevenLabs free tiers have limited minutes/characters — track usage from this phase onward so you know your remaining runway before Phase 8's test-call round.
- **Vendor consolidation:** using Deepgram for both STT and TTS (via Aura) simplifies billing/monitoring to one vendor; using ElevenLabs for TTS may sound better but adds a second free-tier ceiling to track. Decide based on the quality you hear in this phase's test, not in the abstract.

## 12. Cross-references
- See [INDEX.md](INDEX.md) for the phase table and cross-cutting risk list.
- Deepgram streaming docs: https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio
- ElevenLabs TTS docs: https://elevenlabs.io/docs/api-reference/text-to-speech
