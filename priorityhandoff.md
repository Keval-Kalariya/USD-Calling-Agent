# USD Calling Agent — Production Priority Handoff Document
*Use this document in a new conversation to seamlessly resume work right where we left off.*

---

## 1. Project Architecture & Operating Context
* **Project Purpose**: Real-time bi-directional voice conversational AI concierge ("Kiara") for Ultimate Smile Design (USD).
* **Core Pipeline Stack**: 
  `Twilio WebSocket Media Streams (8kHz μ-law)` → `Silero VAD (64ms audio chunking)` → `Deepgram Streaming STT (nova-2, multi-language, asyncwebsocket)` → `CallSession (state machine & transcript merging)` → `Google Gemini 2.5 Flash (async google-genai SDK with inline tool calling)` → `Sentence Boundary Chunker` → `ElevenLabs Stream (ulaw_8000 output)` → `Twilio Audio Downlink`.
* **Current Operational Status**: Local Fast-API server running via Uvicorn and Ngrok tunnel. All core conversation loop upgrades are active and syntax-verified.

---

## 2. Strict Architectural Rules & Constraints
When implementing architectural or pipeline repairs, adhering to these rules is **mandatory**:
1. **Step-by-Step Approval Protocol**: Implement **only one item at a time**. After each change, you must:
   - Explain what changed.
   - Explain why.
   - Show the modified files.
   - **Stop and wait for explicit user approval before beginning the next item.**
2. **Do NOT Optimize ElevenLabs**: The user explicitly intends to remove ElevenLabs and migrate to **Microsoft Edge-TTS** after completing these provider-independent architectural repairs. Do not waste time optimizing ElevenLabs networking or sessions.
3. **Do NOT Modify Unrelated Behavior**:
   - Do NOT change TTS pronunciation or voice behavior.
   - Do NOT modify business logic, tool schemas, or prompt text during architectural cleanups.
   - Do NOT change Twilio Media Stream payload handling.
   - Do NOT modify conversation turn flow or state transitions.
   - **Preserve all existing method signatures, defaults, and public interfaces.**
4. **No Interim Transcript Leakage**: The LLM must NEVER be fed an unfinalized interim STT transcript solely because a timeout or connection blip occurred. Only confirmed complete utterances (`is_final=True` or confirmed trailing buffers) may trigger LLM inference.

---

## 3. Work Completed & Verified In Past Sessions

### 1. Priority 1 — Turn Synchronization & Truncation Fix (COMPLETED)
* Eliminated early cut-off of user utterances (e.g., *"How long"* instead of *"How long does a smile makeover take?"*).
* Built a hybrid synchronization mechanism in `VoicePipelineOrchestrator`: Silero VAD speech offset (`speech_ended`) triggers an `asyncio.Event` wait loop up to 800ms for Deepgram to confirm sentence completion via `is_final=True`.
* If speech resumes during the window, the turn timer cancels immediately.

### 2. Priority 2 — Transcript Buffering & Word Deduping (COMPLETED)
* Implemented `_merge_and_deduplicate()` in `CallSession` to merge streaming STT fragments without losing words or stutter-repeating tokens across Deepgram acoustic packet boundaries.
* Separated buffer reading (`get_merged_transcript(include_interim=False)`) from buffer wiping (`clear_transcripts()`), ensuring buffers are cleared only after the LLM begins consuming them.

### 3. Priority 3 — System Prompt Verification & Integrity (COMPLETED)
* Confirmed the full 52KB `system_prompt.md` loads without truncation or placeholder replacement.
* Added mandatory diagnostic logging before every LLM interaction displaying prompt line count, byte size, and first/last 300 characters.

### 4. Priority 4 — Multilingual STT & Dynamic Mirroring (COMPLETED)
* Upgraded `DeepgramStreamClient` default initialization to `language="multi"`, supporting automatic conversational code-switching across English, Hindi, Gujarati, Hinglish, and Gujlish.
* Updated Gemini runtime session context with explicit behavioral guidance: *"Respond in the same language or natural code-mixed form used in the caller's most recent message. Mirror the caller's language naturally. If the caller switches language, switch with them."*

### 5. Prompt 5 — Filler & Vocal Hesitation Removal (COMPLETED)
* Added explicit instructions in `system_prompt.md` and `USD_Calling_Agent_Prompt.md` banning phonetic fillers (`uh`, `umm`, `ah`, `eh`).
* Built defensive TTS sentence chunk filtering (`_filter_tts_chunk`) in `CallSession` that strips initial hesitation phonemes and drops isolated filler chunks with lightweight informational logging (`[TTS Filter] Removed hesitation token...`).

### 6. Comprehensive Audit & Item 1 Fix — Deepgram Reconnect Watchdog (COMPLETED & APPROVED)
* Conducted a comprehensive 20-category architectural audit of the entire pipeline. The user instructed us to fix **only provider-independent production-critical fixes (Items 1, 2, and 3)** before migrating to Edge-TTS.
* **Item 1 Implemented & Verified in `agent/streaming/deepgram_stream.py` & `agent/pipeline.py` & `agent/session/call_session.py`**:
  * Added an async exponential-backoff watchdog (`_auto_reconnect`) to recover dropped Deepgram WebSockets mid-call.
  * Made audio transmission resilient (`send_audio` peacefully drops media gap frames during reconnection without throwing exceptions).
  * Implemented **Reconnection Sanitization Hook (`purge_interim_state`)**: If an unexpected outage occurs mid-speech, pending turn timers cancel and unconfirmed interim transcripts are purged so stale words cannot corrupt speech after recovery.
  * Gated sanitization directly behind `self._should_reconnect`, guaranteeing that normal call hang-ups via `stop()` or `finish()` close instantly without unnecessary state resets.

---

## 4. IMMEDIATE NEXT STEPS FOR NEW CONVERSATION

Start the new conversation by confirming receipt of this handoff and offering to implement **Item 2** under the agreed rules:

* **Item 2 (CURRENT TASK): Streaming Client Lifecycle Cleanup (#14)**
  * **Goal**: In `VoicePipelineOrchestrator.stop()` ([agent/pipeline.py:L249](file:///e:/USD-Calling-Agent/agent/pipeline.py#L249)), call cleanup/finish hooks uniformly across all client connections upon call hang-up or disconnection.
  * **Requirements**: Implement safe `.close()` / `.finish()` lifecycle teardown methods on `gemini_client` and `tts_client` (to match `dg_client.finish()`) and call them in `orchestrator.stop()`. Preserve all existing interfaces and behaviors.
  * **Action**: Implement Item 2, show modified code, explain the changes, and **wait for explicit user approval before proceeding to Item 3.**

* **Item 3 (UP NEXT AFTER ITEM 2 APPROVAL): Async Task Cancellation and Cleanup (#13 and #17)**
  * **Goal**: Prevent orphaned background task leaks during turn interruption or call shutdown.
  * **Requirements**: In `_run_turn_lifecycle` ([agent/pipeline.py:L195](file:///e:/USD-Calling-Agent/agent/pipeline.py#L195)), when a conversational turn terminates or is cancelled, explicitly cancel the sentence boundary producer task (`chunker_task = asyncio.create_task(...)`) in the `finally:` block so orphaned loops do not continue consuming billing tokens or pushing to dead queues.

* **Future Major Milestone (AFTER ITEM 3 APPROVED)**:
  * Replace ElevenLabs dependency with **Microsoft Edge-TTS** across the pipeline.
  * Upgrade Gemini SDK credentials to a production-grade paid API key.

---
*End of Handoff Document. Ready to resume at Item 2.*
