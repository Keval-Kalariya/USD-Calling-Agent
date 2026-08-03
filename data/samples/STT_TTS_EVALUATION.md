# Phase 2 — STT & TTS Language Evaluation

**Objective:** Validate that Deepgram (STT) and ElevenLabs (TTS) handle English, Hindi, and Gujarati with acceptable quality and latency before moving to Phase 5.

## 1. Deepgram STT Results

| Scenario | Language Param | Model | Latency (ms) | Accuracy & Code-Switching Notes |
|----------|----------------|-------|--------------|---------------------------------|
| Pure English | `en-IN` | `nova-2` | | |
| Hinglish | `hi` / `en-IN` | `nova-2` | | |
| Pure Hindi | `hi` | `nova-2` | | |
| Pure Gujarati | `gu` | `nova-2` | | |

*Notes on Code-Switching (Hinglish/Gujlish):*
- (Fill in observations: Did the Hindi model capture English brand names correctly?)

**Recommended Deepgram Settings for Phase 5:**
- (e.g., Use `nova-2` with `hi` language for all inbound calls, or detect dynamically)

---

## 2. ElevenLabs TTS Results

**Voice ID Used:** `pNInz6obbfDQGcgMyIGb` (Adam) / _______________  
**Model:** `eleven_multilingual_v2`

| Scenario | Latency (ms) | Pronunciation & Naturalness Notes |
|----------|--------------|-----------------------------------|
| English | | |
| Hindi | | |
| Gujarati | | |

*Notes on Brand Names:*
- (Did the TTS pronounce "Ultimate Smile Design" correctly in the middle of Hindi/Gujarati sentences?)

**Recommended ElevenLabs Settings for Phase 5:**
- Voice ID: 
- Model: `eleven_multilingual_v2`

---

## 3. Conclusion & Go/No-Go Decision

- [ ] **GO**: Quality and latency for all three languages are acceptable. We proceed with a trilingual agent.
- [ ] **FALLBACK**: Hindi/Gujarati STT is too slow or inaccurate. We will fall back to English-only for v1.
- [ ] **ADJUST**: We need to find a different ElevenLabs voice ID, as the current one sounds unnatural in Gujarati.
