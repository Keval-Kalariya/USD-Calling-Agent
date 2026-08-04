# Voice Pipeline Architecture & TTS Operations Guide

This document describes the real-time, bi-directional voice orchestration architecture for the Ultimate Smile Design AI Calling Agent. It details TTS provider switching, feature-flag configuration, audio transcoding mechanics, fallback capabilities, and operational troubleshooting.

---

## 1. Architectural Overview

The telephony pipeline operates through a framework-agnostic orchestrator (`VoicePipelineOrchestrator`) that bridges Twilio WebSocket Media Streams with real-time Speech-to-Text (STT), Large Language Model (LLM) reasoning, and Text-to-Speech (TTS) vocal synthesis.

```
       +-------------------------+
       |   Twilio Media Stream   |
       |  (8kHz u-law WebSocket) |
       +------------+------------+
                    |
      [Audio Frames]| [Inbound Speech]
                    v
       +-------------------------+
       | Deepgram Real-Time STT  |
       +------------+------------+
                    |
  [Final Transcript]| [Sentence Boundaries]
                    v
       +-------------------------+
       |  Gemini 3.6 Flash LLM   |
       |  (Tool Calling & RAG)   |
       +------------+------------+
                    |
     [Text Fragments]| [Sentence Queue]
                    v
       +-------------------------+
       | TTS Provider Selection  |
       |  (ElevenLabs / Gemini)  |
       +------------+------------+
                    |
 [8kHz u-law Audio]| [Base64 Packets]
                    v
       +-------------------------+
       |  Twilio Audio Playback  |
       +-------------------------+
```

### Component Breakdown
1. **Inbound Telephony (Twilio):** Audio arrives over WebSockets as base64-encoded 8,000 Hz u-law packets (`event: "media"`).
2. **Real-Time STT (Deepgram):** `DeepgramStreamClient` consumes audio frames and streams interim/final text transcripts back to the orchestrator.
3. **Conversational Engine (Google Gemini LLM):** `GeminiStreamClient` maintains call conversational context using `gemini-3.6-flash`, integrating Retrieval-Augmented Generation (RAG) and Tool Calling (e.g., appointment lookups).
4. **Sentence Boundary Chunker:** Streaming LLM output token fragments are segmented into natural syntactic sentence boundaries before being fed to the TTS generation queue.
5. **Acoustic Synthesis (TTS Provider):** Selected dynamically via feature flags, converting conversational text segments into audio.
6. **Outbound Playback:** TTS audio is segmented into uniform packets ($\le 2,048$ bytes), base64-encoded, and transmitted directly to Twilio for speaker playback.

---

## 2. TTS Provider Selection & Feature Flag

The orchestrator utilizes dynamic dependency injection controlled by the `TTS_PROVIDER` feature flag in your runtime configuration.

* **`TTS_PROVIDER=elevenlabs` (Default Production Setting):** Instantiates `ElevenLabsStreamClient`. Uses ElevenLabs WebSocket/REST streaming APIs.
* **`TTS_PROVIDER=gemini` (Validated Alternative):** Instantiates `GeminiTTSStreamClient`. Uses Google Cloud GenAI Models API (`generate_content_stream` with audio response modality) to produce synthesized speech.

> [!IMPORTANT]
> **Startup Fail-Fast Protection:** If an unsupported provider string (e.g., `edge`, `azure`) is supplied to `TTS_PROVIDER`, the orchestrator immediately raises a descriptive `ValueError` during application startup, preventing broken telephony connections in production.

---

## 3. Required Environment Variables

Ensure your `.env` and runtime environment variables reflect the following single-source parameters:

| Variable Name | Required Value / Default | Description |
| :--- | :--- | :--- |
| `TTS_PROVIDER` | `elevenlabs` *(or `gemini`)* | Master switch controlling active TTS dependency injection. |
| `GEMINI_API_KEY` | `AIzaSy...` | Paid Google Cloud GenAI authentication key for LLM and TTS. |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Model identifier used by the conversational messaging engine. |
| `GEMINI_TTS_MODEL`| `models/gemini-3.1-flash-tts-preview` | Model identifier specifically targeting audio speech synthesis. |
| `GEMINI_TTS_VOICE`| `Puck` | Prebuilt Google voice persona assigned to Kiara. |
| `GEMINI_TTS_TIMEOUT`| `10.0` | Maximum network waiting duration (seconds) before clean stream termination. |

### Example `.env` Configuration Block
```ini
# --- Core Telephony & STT ---
TWILIO_ACCOUNT_SID=AC_your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
DEEPGRAM_API_KEY=your_deepgram_key

# --- TTS Provider Feature Flag ---
TTS_PROVIDER=elevenlabs

# --- Google Gemini Configuration (LLM & TTS) ---
GEMINI_API_KEY=your_paid_gemini_api_key
GEMINI_MODEL=gemini-3.6-flash
GEMINI_TTS_MODEL=models/gemini-3.1-flash-tts-preview
GEMINI_TTS_VOICE=Puck
GEMINI_TTS_TIMEOUT=10.0

# --- ElevenLabs Rollback Configuration ---
ELEVENLABS_API_KEY=your_elevenlabs_api_key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```

---

## 4. Supported Gemini TTS Voices

When utilizing `TTS_PROVIDER=gemini`, the `GEMINI_TTS_VOICE` parameter supports any prebuilt Google cloud voice persona:
* **`Puck`** *(Default)*: Smooth, natural conversational timbre optimized for professional customer assistance.
* **`Charon`**: Deep, assertive vocal presence.
* **`Kore`**: Bright, dynamic, energetic pacing.
* **`Fenrir`**: Robust, warm vocal tone.
* **`Aoede`**: Elegant, articulate delivery suitable for formal messaging.

---

## 5. Twilio Audio Format & Transcoding Pipeline

Twilio Media Streams universally require **8,000 Hz $\mu$-law (u-law) mono audio**. Because generative AI native audio endpoints emit higher-resolution studio formats, `GeminiTTSStreamClient` implements real-time transcoding using `agent/audio/codecs.py`:

1. **Raw SDK Output:** Gemini returns continuous audio blobs encoded as **24,000 Hz 16-bit linear PCM**.
2. **On-the-Fly Downsampling:** As audio packets stream over gRPC, `resample_pcm16` downsamples the 24kHz linear audio to 8kHz linear PCM using `audioop-lts`, preserving acoustic filter state across chunk boundaries to prevent static or clicking artifacts.
3. **$\mu$-Law Companding:** Downsampled samples are converted into standard 8kHz $\mu$-law (`pcm16_to_mulaw`).
4. **Packetization:** Audio bytes are sliced into manageable streaming blocks ($\le 2,048$ bytes) to match Twilio’s internal jitter buffers and maintain seamless conversational cadence without buffer starvation.

---

## 6. Fallback Behaviour & Safe Rollback

The pipeline has been engineered with a zero-risk rollback guarantee:
* **Undeleted Fallback Path:** ElevenLabs integration code (`agent/streaming/elevenlabs_stream.py`) remains completely intact and fully verified.
* **Instant Rollback:** If Gemini TTS encounters quota depletion or degraded latency in live production, simply switch `TTS_PROVIDER=elevenlabs` in your environment variables. No repository recompiles or code deployments are necessary to revert to ElevenLabs.
* **Barge-In Safety:** If a caller speaks while Kiara is replying (barge-in interruption), the orchestrator triggers an immediate `asyncio.CancelledError`. Both `ElevenLabsStreamClient` and `GeminiTTSStreamClient` intercept this signal, halt generative loops instantly, close underlying gRPC/HTTP generators, and release network resources without leaking background tasks.

---

## 7. Troubleshooting Guide

| Problem / Symptom | Root Cause | Recommended Solution |
| :--- | :--- | :--- |
| **`ValueError: Unsupported TTS_PROVIDER value...` on startup** | A typo or unsupported parameter was entered into `.env` for `TTS_PROVIDER`. | Ensure `TTS_PROVIDER` is set strictly to lowercase `elevenlabs` or `gemini`. |
| **HTTP 429 / `ResourceExhausted` logs during high call concurrency** | Google GenAI account tier rate limits hit on preview models during burst traffic. | The client automatically retries up to 3 times with exponential backoff. If volume persists, temporarily set `TTS_PROVIDER=elevenlabs` for peak overflow. |
| **Caller experiences ~2 second pause before reply on first turn** | Cold streaming initiation and preview API TTFB characteristics (~1.8–2.2s TTFB). | Normal behavior for current Google GenAI preview audio models. Subsequent conversational turns drop to ~1.3s TTFB. |
| **Windows Console `UnicodeEncodeError: 'charmap' codec can't encode character...`** | Attempting to print Greek mu ($\mu$-law) symbols on Windows terminal codepages. | Standardized logging uses ASCII `u-law` across all print outputs. Avoid inserting raw Unicode characters into operational logs. |
| **Audio generation stops or cuts off on multi-paragraph text** | Attempting to pass >500 characters in a single un-segmented API call. | `GeminiTTSStreamClient` automatically applies grammatical sentence chunking (`_segment_text`) to preserve streaming TTFB and prevent model timeout. |
