# Kiara Voice Pipeline: Terminal Log Audit & UX Improvement Report

An extensive diagnostic audit of the live terminal logs (`uvicorn`, PID 17532) alongside architectural recommendations for your conversational UX goals (barge-in, active listening, multilingual onboarding, and latency minimization).

---

## 1. Root Cause Analysis: Why Kiara Went Silent & High Latency

> [!CAUTION]
> **Primary Cause of Dead Air: Google Gemini HTTP 429 Rate Limit Exceeded**
> Your logs reveal that Kiara attempted to generate a response to *"Tell me about implants"* and *"Hello? Are you there?"*, but both calls crashed with an HTTP `429 Too Many Requests` quota violation from Gemini Free Tier. Because the exception handler caught the 429, Kiara returned an empty response (`''`), leaving the caller in total silence (dead air).

### Why did we hit the Rate Limit & High Latency?
1. **Massive System Prompt Overhead (`52,221 bytes` / `~13,000 tokens`):**
   Every single speech turn re-transmits a 716-line system prompt containing over 51,789 characters. On Gemini 3.6 Flash Free Tier, passing 13,000+ tokens per request rapidly burns through daily per-minute request/token limits and introduces substantial compute lag before the first audio token can be synthesized.
2. **STT vs. VAD Synchronization Mismatch & Timeout:**
   When you finished speaking, Silero VAD immediately detected `speech_ended`. However, the orchestrator waited for Deepgram to emit an `is_final=True` event. Because Deepgram's internal endpointing took longer than your orchestrator's timeout, the turn aborted with `[Orchestrator] No finalized transcript available` and discarded your speech buffer! A split-second later, Deepgram delivered the final transcript, forcing another delayed state transition.

---

## 2. Line-by-Line Terminal Audit & Diagnosis

| Log Snippet | Diagnosis & What is Happening |
| :--- | :--- |
| `[Orchestrator] VAD speech_ended detected... Waiting for Deepgram final transcript...` | Silero VAD detects speech stopped and sets a short timer waiting for Deepgram to confirm the sentence ended. |
| `[Partial Transcript] Tell me about in` | Deepgram continues streaming partial words while the timer is ticking down. |
| `[Orchestrator] Timeout waiting for Deepgram is_final. Proceeding with buffered transcript.`<br>`No finalized transcript available. Staying in listening state...` | **Pipeline Defect:** The wait timer expired before Deepgram sent `is_final`. The orchestrator abandoned the conversational turn, causing severe perceived latency and dropped syllables. |
| `[Final Transcript] Tell me about implants.`<br>`State: listening → thinking` | Deepgram finally delivered the sentence after the timeout. The pipeline recovered and triggered the LLM. |
| `System Prompt Loaded. Length: 716 lines (52221 bytes)... Characters: 51789` | **Performance Bottleneck:** Loading 52KB (~13,000 tokens) of instructions and static data into the LLM on every single interaction. |
| `[Sentence Chunker Error] 429 Too Many Requests... Quota exceeded... Free-Tier... limit: 20...` | **Fatal Call Defect:** Google rejected the request due to free tier limits. The pipeline crashed mid-turn. |
| `[Orchestrator] Turn finished. Assistant replied: ''`<br>`State: speaking → listening` | Because of the 429 crash, the synthesized speech text was empty (`''`). Kiara went completely silent without playing a fallback error message to the caller. |
| `[Final Transcript] Hello? Are you there?` ... `RetryDelay: 42s` | The caller attempted to check if the call was connected, but the API remained locked out for 42 seconds. |

---

## 3. Conversational UX & Performance Improvement Plan

Here is the exact technical blueprint to resolve each of the 5 user-experience enhancements you requested for our upcoming migration steps:

### A. Barge-In: "When I speak, she does not stop speaking"
* **Why this happens right now:** In Step 5, we strictly followed the rule to *only log* VAD events without acting on them. Furthermore, even in full implementations, simply stopping ElevenLabs in Python is not enough—Twilio's network buffer holds ~300–500ms of audio that continues playing in your ear.
* **How we will solve it in Step 7:** 
  1. **Instant Twilio Cache Flush:** The exact millisecond `SileroVAD` triggers `speech_started` while Kiara is speaking, our websocket handler will transmit a raw Twilio payload: `{"event": "clear", "streamSid": streamSid}`. This wipes Twilio's audio buffer instantly.
  2. **Turn Counter Tokenization:** Assign an incrementing `turn_id` to every LLM turn. On interruption, bump the ID and silently discard any lagging incoming TTS bytes from old turns.

### B. Active Listening Acknowledgments: "Yes, yes!", Filler responses in 3 Languages
* **Why this happens right now:** Complete silence exists between the moment you stop speaking and the moment ElevenLabs starts delivering synthesized audio (~1.5s gap).
* **How we will solve it (Backchanneling Architecture):** 
  1. **Pre-caching Audio:** Save instant, pre-compiled 8kHz μ-law audio clips in `data/audio/backchannels/` for English, Hindi, and Gujarati (e.g., *"Ji, tell me"*, *"Yes, listening"*, *"Ha bolo"*, *"Hmm, let me check that"*).
  2. **Zero-Latency Injection:** As soon as VAD flags `speech_ended`, immediately blast one of these 300ms pre-cached audio frames down the Twilio socket. Kiara sounds actively engaged *while* Gemini is calculating the full answer in the background!

### C. Language Switching Latency & Reliability: "Takes 2 or 3 times to change language"
* **Why this happens right now:** 
  1. Deepgram's socket is initialized with `language="en-US"`, making it deaf to Hindi/Gujarati until enough phonetic context overrides it, causing mangled STT transcripts.
  2. A 13,000-token system prompt weakens Gemini's attention span, making it ignore mild conversational language switches.
* **How we will solve it:** 
  1. **Multilingual STT Setup:** Configure Deepgram's streaming client to use multilingual models (`model="nova-2"`, `language="multi"` or dedicated Indian regional profiles).
  2. **Explicit Language State Guard:** Maintain a `current_language` property inside `CallSession`. When language switching is detected, prepend a high-priority system directive directly into the immediate turn message: `[SYSTEM OVERRIDE: RESPOND EXPLICITLY IN GUJARATI]`.

### D. Onboarding Language Routing: "First ask their language, then speak in that language"
* **How we will implement this seamlessly:**
  1. **Multi-lingual Welcome Turn:** Upon call connection (`start` event), play a friendly trilingual greeting: *"Hello! Welcome to Ultimate Smile Design. Would you like to speak in English, Hindi, or Gujarati? Ji, Hindi ya English?"*.
  2. **Deterministic Classification:** Route the caller's first response to a high-speed classifier setting `session.current_language = 'hi' | 'gu' | 'en'`.
  3. **Locked Mode:** From that point forward, lock Kiara into that language profile so she responds instantly in the preferred native dialect without hesitation.

---

## 4. Immediate Action Item Checklist for Latency & Reliability

> [!IMPORTANT]
> To eliminate the latency and 429 crashes before we begin wiring Step 6, we must optimize three core components:

1. [ ] **Prompt Compression:** Shrink `system_prompt.md` from **52 KB to under 4 KB (~1,000 tokens)**. All exhaustive FAQ tables and city directory listings must be removed from the main text and fetched *only when requested* via our existing Python tool-calling functions (`get_faq`, `check_city_coverage`).
2. [ ] **Tune VAD / STT Sync:** Increase the orchestrator's Deepgram finalization grace period from ~500ms to **1200ms**, OR set Deepgram's live streaming `endpointing=200` (down from 300ms) so `is_final=True` fires faster than the VAD timer.
3. [ ] **Graceful 429 Fallback Audio:** Modify the exception handler in `CallSession` so that if Gemini throws a rate-limit or network error, Kiara immediately speaks an audio fallback: *"I apologize, our systems are experiencing high traffic. Allow me to transfer you to a specialist."* instead of dropping to dead air.
