# Migration Plan: Pipecat → Raw FastAPI/WebSocket Voice Pipeline
**Project:** Ultimate Smile Design Calling Agent ("Kiara")
**Scope:** Replace the real-time voice orchestration layer only. No business-logic redesign, no new project.

---

## 0. Why this migration is tractable

Looking at your tree, Pipecat's footprint is small and load-bearing in exactly one place: `agent/pipeline.py`, and by extension whatever `backend/app/routes/twilio_voice.py` imports from it. Everything else — prompts, tools, lead capture, city coverage, handoff, call logging, the Gemini wrapper you already hand-rolled (`CustomGeminiLLMService`) — is framework-agnostic Python that doesn't know Pipecat exists. That's the leverage point: you're not migrating a project, you're replacing one module's internals and rewriting the thin integration seam around it.

The fact that you already built `CustomGeminiLLMService` directly against the `google-genai` SDK (per your handoff notes) rather than using Pipecat's Gemini service class is actually a big head start — that code is likely reusable close to as-is, just called directly instead of invoked as a Pipecat `FrameProcessor`.

---

## 1. Analysis of Current Pipecat Integration

### 1.1 How Pipecat is currently integrated
Based on your project tree and handoff notes, Pipecat involvement centers on:
- `agent/pipeline.py` — builds a Pipecat `Pipeline` object: Twilio transport → Silero VAD → STT service → your custom Gemini LLM service → TTS service → back out. This is the file most tightly coupled to Pipecat's `FrameProcessor`/`Frame` abstractions and its `Pipeline`/`PipelineTask`/`PipelineRunner` runtime.
- `backend/app/routes/twilio_voice.py` — the `WS /twilio/media-stream` endpoint. In a Pipecat setup this route's job is usually reduced to accepting the WebSocket and handing it to Pipecat's `FastAPIWebsocketTransport`, which then owns the read/write loop, audio framing, and lifecycle.
- Silero VAD — currently used as a Pipecat-bundled VAD analyzer plugged into the transport params, not a standalone component you call yourself.
- Barge-in handling — currently implicit, riding on Pipecat's frame-based interruption strategy (`interruption_strategies` / `allow_interruptions` on the pipeline task) rather than logic you wrote.

### 1.2 Files that depend on Pipecat directly
- `agent/pipeline.py` — full rewrite. Every import and the entire control flow is Pipecat-shaped.
- `backend/app/routes/twilio_voice.py` — the WebSocket handler needs a full rewrite of its transport/lifecycle handling, even though the *route path and TwiML-returning half* (`POST /twilio/voice`) likely stays close to untouched.
- Anywhere `agent/pipeline.py` is imported to be started/stopped (likely inside `twilio_voice.py`, possibly touched in `backend/app/main.py` for startup/shutdown hooks or session registries) — needs updating to call the new orchestrator's start/stop instead of `PipelineRunner.run()`.
- `requirements.txt` — remove `pipecat-ai` and its Twilio/Deepgram/ElevenLabs/Silero extras; add the raw SDK/client libraries you'll call directly instead (see §4 and §7).

### 1.3 Folders/files that can remain unchanged
These have zero Pipecat awareness and should not be touched beyond normal review:
- `agent/prompts/system_prompt.md` — pure prompt text.
- `agent/tools/capture_lead.py`, `check_city_coverage.py`, `get_faq.py`, `handoff.py` — these are your Gemini function-calling tool implementations; they operate on plain Python function signatures the LLM tool-calling loop invokes, not Pipecat frames.
- `agent/cli_harness.py` — your text-only conversation harness never touched audio or Pipecat.
- `agent/utils/call_logger.py` — assuming it writes to `data/calls.json`, this is I/O logic, not transport logic.
- `backend/app/models/call.py`, `lead.py` — data models, untouched.
- `backend/app/routes/internal_callback.py` — the outbound-trigger endpoint's job is to originate a Twilio call and pass an `opening_intent`; it doesn't own the media stream itself. It may need one small change (see §3, Phase 6 note) if it currently reaches into Pipecat internals to pre-seed pipeline state, but likely just calls `client.calls.create(...)` and lets `/twilio/voice` handle the rest.
- `backend/app/settings.py`, `.env` — config is transport-agnostic.
- `data/` directory — all data files, untouched.
- `scripts/` — `check_keys.py`, `test_stt.py`, `test_tts.py`, `test_outbound_call.py` remain valid smoke tests, though `test_stt.py`/`test_tts.py` may be worth re-pointing at the new raw-SDK client code once it exists, so they test the actual code path you'll run in production rather than a standalone vendor SDK call that no longer resembles the pipeline.
- `CONVERSATION_DESIGN.md`, `USD_Calling_Agent_Prompt.md`, `README.md`, `handoff.md` — documentation, update only for narrative accuracy once migration lands.

### 1.4 Files to modify
- `agent/pipeline.py` — rewritten as a plain asyncio orchestrator class (see §4).
- `backend/app/routes/twilio_voice.py` — WebSocket handler rewritten to own the receive loop and call the new orchestrator.
- `requirements.txt` — dependency swap.
- `backend/app/main.py` — only if it currently references Pipecat's runner/lifecycle for startup/shutdown; otherwise untouched.

### 1.5 Files to remove
- Nothing needs deleting outright except Pipecat-specific config if it lives in its own file (e.g. a `pipeline_config.py` if one exists that isn't in your listed tree). The `pipecat-ai` dependency itself is removed from `requirements.txt`.

### 1.6 New files to create
```
agent/
├── pipeline.py                    # REWRITTEN: plain asyncio orchestrator (was Pipecat Pipeline)
├── audio/
│   ├── __init__.py
│   ├── codecs.py                  # mulaw <-> PCM16, resampling 8kHz <-> 16kHz
│   └── vad.py                     # thin wrapper around Silero VAD (torch/onnx), called directly
├── streaming/
│   ├── __init__.py
│   ├── deepgram_stream.py         # Deepgram streaming STT client (raw websocket/SDK)
│   ├── gemini_stream.py           # wraps your existing CustomGeminiLLMService for streaming token output
│   └── elevenlabs_stream.py       # ElevenLabs streaming TTS client (raw websocket/SDK)
└── session/
    ├── __init__.py
    └── call_session.py            # per-call state machine: turn state, transcript buffer, interruption flags
```
This structure keeps the new orchestration code isolated from your untouched business logic, and mirrors the pipeline stages explicitly instead of hiding them inside a framework's frame graph — which will make debugging the "agent doesn't speak" class of bug far more tractable, since every hop is a function you can log around.

---

## 2. Migration Roadmap — Phase by Phase

| Phase | Original scope | Status under migration |
|---|---|---|
| **0 — Bootstrap** | Accounts, keys, health check | **Unchanged.** No Pipecat dependency here. |
| **1 — Telephony** | `POST /twilio/voice` webhook, `WS /twilio/media-stream` boilerplate | **Partially changes.** The TwiML-returning webhook stays the same. The WebSocket endpoint's *ownership model* changes: instead of handing the socket to a Pipecat transport, your route code becomes the permanent owner of the receive/send loop for the life of the call. |
| **2 — Speech pipeline (standalone)** | Deepgram STT + ElevenLabs TTS scripts | **Re-scoped, not discarded.** These become the basis for `agent/streaming/deepgram_stream.py` and `elevenlabs_stream.py` — promoted from throwaway scripts into the actual runtime clients, since you're no longer relying on Pipecat's bundled service wrappers for these vendors. |
| **3 — Conversational core** | System prompt, tools, CLI harness | **Unchanged.** This was already framework-agnostic. |
| **4 — Directory/lead data → City coverage & lead capture** | Real data wired into tools | **Unchanged.** |
| **5 — Real-time orchestration** | *This is the phase being fully redone.* | **Full rewrite**, this is the core of the migration — see §4 below for the new architecture replacing Pipecat's pipeline/frame model. |
| **6 — Outbound follow-up** | Trigger endpoint originates calls into the same pipeline | **Small adjustment.** `internal_callback.py`'s job (call Twilio, pass `opening_intent`) is unchanged in shape; it just needs to confirm it's not reaching into Pipecat-specific pipeline internals to pre-seed state — if it currently does, that hook moves to the new `call_session.py`. |
| **7 — Lead capture & staff handoff** | Notifications, admin view | **Unchanged** — reads from `data/leads.json`/`calls.json`, no transport dependency. (Per your last message, this was in progress — safe to resume once Phase 5's rewrite is stable, or in parallel since it's fully decoupled.) |
| **8 — Testing/QA/analytics** | Scripted test-call checklist | **Unchanged in scope, but re-run in full.** Every scenario needs re-validation against the new pipeline since the failure mode you're fixing (agent doesn't speak) lived exactly in this layer. |
| **9 — Hardening & deploy** | Free-tier host, systemd, WS support | **Unchanged**, though note your tree now shows Docker in the deployment target (your task doc says "Deployment (Later): Linux, Docker" vs. the original plan's "no Docker in v1"). Worth reconciling that explicitly — Docker doesn't materially change this migration, but it does change Phase 9's deliverable (a `Dockerfile`/`docker-compose.yml` instead of/alongside systemd units). Flagging as a decision to confirm, not assuming either way. |
| **10 — Third-party migration** | Later, self-hosted swaps | **Unchanged**, and arguably easier post-migration — since you'll now own the streaming client code for each vendor directly (§1.6), swapping Deepgram for `faster-whisper` or ElevenLabs for Piper later means replacing one client module behind a stable internal interface, rather than replacing a Pipecat service class and hoping the frame contract still holds. |

### New phase to insert
**Phase 5a — Orchestrator smoke test (before full Phase 5 re-validation).** Insert a narrow, isolated test between "new orchestrator code exists" and "re-run the full Phase 8 checklist": a single scripted call that does nothing but prove the raw audio round-trip works — caller speaks, a canned/echoed response plays back — with zero LLM tool-calling in the loop. This isolates "is the transport/audio path fixed" from "does the conversation logic still work," which matters a lot here because your stated bug (agent never speaks) is almost certainly a transport/framing bug, not a conversation-logic bug, and you want to confirm that in isolation before re-running the full multi-turn checklist.

### Dependencies between phases
Same dependency shape as your original plan — Phase 5 (now the rewrite) still depends on 1–4 being intact, and 6/7/8/9 still depend on 5. The one new dependency: Phase 5a (the smoke test) gates Phase 8's full re-run — don't spend time re-running the irritated-caller/Hindi-Gujarati/dead-air checklist until the bare audio round-trip is proven first.

### Migration risks
1. **You are now responsible for everything Pipecat used to hide.** Frame-level backpressure, WebSocket keepalive, format negotiation, and interruption timing were Pipecat's job. All of that becomes your orchestrator's job. This is the main cost of the migration — budget real time for it, not just a mechanical file rewrite.
2. **Audio format bugs are the most likely root cause of "doesn't speak."** Before assuming the rewrite is needed to fix the underlying issue, it's worth confirming *why* Pipecat wasn't producing audio — if it's a genuine Pipecat/Twilio transport bug, the raw rewrite fixes it by construction. If it was actually a misconfigured TTS voice ID, a silent exception being swallowed, or a WebSocket closing early, the same root cause can resurface in the new code if it's not diagnosed first. Recommend a short root-cause pass (even just verbose logging on the existing Pipecat pipeline for one test call) before or in parallel with starting the rewrite, so you're not migrating away from a framework to escape a bug that wasn't the framework's fault.
3. **Streaming Gemini + streaming TTS coordination is the hardest part to get right by hand.** Pipecat's frame graph handles partial-LLM-token → TTS streaming reasonably transparently. Doing this manually means you own: buffering LLM tokens into TTS-appropriate chunks (usually sentence/clause boundaries, not raw tokens), starting TTS synthesis before the full LLM response is generated, and being able to cancel both mid-flight on barge-in. This is where most of the new complexity lives — see §4.2.
4. **Silero VAD outside Pipecat needs its own runtime loop.** You'll be running the VAD model directly against incoming audio frames instead of it being wired in as a pipeline stage — straightforward, but it's one more explicit async task to manage per call.
5. **Regression surface.** Because Phase 5 touches the one file everything downstream depends on, a regression here silently breaks Phases 6 and 8's assumptions (that a working live pipeline exists). The Phase 5a smoke test above exists specifically to catch this early rather than discovering it during a full Phase 8 re-run.

---

## 3. Updated Project Structure

```
USD Calling Agent/
├── .env
├── requirements.txt                          # MODIFIED — remove pipecat-ai, add raw SDK deps
├── agent/
│   ├── cli_harness.py                        # UNCHANGED
│   ├── pipeline.py                           # REWRITTEN — orchestrator, no Pipecat
│   ├── prompts/system_prompt.md               # UNCHANGED
│   ├── tools/                                  # UNCHANGED (all 4 files)
│   ├── utils/call_logger.py                    # UNCHANGED
│   ├── audio/                                  # NEW
│   │   ├── codecs.py                           # NEW — mulaw/PCM16, resampling
│   │   └── vad.py                              # NEW — Silero VAD direct wrapper
│   ├── streaming/                              # NEW
│   │   ├── deepgram_stream.py                  # NEW — promoted from scripts/test_stt.py
│   │   ├── gemini_stream.py                    # NEW — thin streaming wrapper around existing CustomGeminiLLMService
│   │   └── elevenlabs_stream.py                # NEW — promoted from scripts/test_tts.py
│   └── session/                                 # NEW
│       └── call_session.py                      # NEW — per-call state machine
├── backend/app/
│   ├── main.py                                  # LIKELY UNCHANGED, review startup/shutdown hooks
│   ├── settings.py                              # UNCHANGED
│   ├── models/                                  # UNCHANGED (call.py, lead.py)
│   └── routes/
│       ├── twilio_voice.py                      # REWRITTEN — owns WS receive/send loop directly
│       └── internal_callback.py                 # REVIEW ONLY — likely unchanged
├── data/                                         # UNCHANGED
└── scripts/
    ├── test_stt.py                               # RE-POINT at agent/streaming/deepgram_stream.py
    ├── test_tts.py                               # RE-POINT at agent/streaming/elevenlabs_stream.py
    └── (others unchanged)
```

### Responsibility of each new file
- **`agent/audio/codecs.py`** — pure functions: μ-law byte chunks ↔ PCM16 numpy/bytes, 8kHz ↔ 16kHz resampling. No I/O, no async — easy to unit test in isolation, which matters a lot given format bugs are your prime suspect (§2, risk 2).
- **`agent/audio/vad.py`** — loads the Silero VAD model once at process start, exposes a simple `is_speech(pcm_chunk) -> bool` or streaming-state call, used directly by `call_session.py` instead of being a Pipecat pipeline stage.
- **`agent/streaming/deepgram_stream.py`** — owns the Deepgram streaming WebSocket connection for one call: send audio in, yield partial/final transcripts out via an async generator or callback.
- **`agent/streaming/gemini_stream.py`** — thin adapter around your existing `CustomGeminiLLMService`: takes a transcript + conversation history, yields streamed text chunks (and surfaces tool-call requests) the same way it presumably already does, just called directly by the orchestrator instead of as a Pipecat frame processor.
- **`agent/streaming/elevenlabs_stream.py`** — owns the ElevenLabs streaming TTS WebSocket for one call: takes text chunks in, yields audio bytes out, exposes an explicit `cancel()` for barge-in.
- **`agent/session/call_session.py`** — the actual replacement for what Pipecat's `Pipeline`/`PipelineTask` used to coordinate: one instance per call, holding turn state (listening / thinking / speaking), the running transcript, and the interruption flag; this is what `twilio_voice.py`'s WebSocket handler drives.

---

## 4. Voice Pipeline Architecture

```
Twilio Media Stream (WS, 8kHz μ-law, base64, ~20ms frames)
        │
        ▼
FastAPI WS endpoint (twilio_voice.py)
   — owns the socket for the call's lifetime
   — demuxes Twilio's JSON envelope (event: "start"/"media"/"stop")
   — decodes base64 → raw μ-law bytes
        │
        ▼
CallSession (session/call_session.py)
   — feeds raw audio to VAD (audio/vad.py) and, in parallel, to Deepgram (streaming/deepgram_stream.py)
   — on VAD-detected speech-end or Deepgram's own endpointing: finalize the caller's turn
        │
        ▼
Gemini streaming (streaming/gemini_stream.py)
   — receives finalized transcript + running history
   — streams text tokens back, and/or emits a tool-call request (capture_lead, check_city_coverage, get_faq, handoff)
   — tool calls execute inline (they're already plain async/sync functions — unchanged from Phase 3/4)
        │
        ▼
Sentence-boundary chunker (small piece of call_session.py, not a separate file)
   — buffers Gemini's streamed tokens, releases text to TTS at clause/sentence boundaries
   — this is the manual replacement for what Pipecat did implicitly
        │
        ▼
ElevenLabs streaming (streaming/elevenlabs_stream.py)
   — synthesizes each text chunk as it arrives, streams audio bytes back
        │
        ▼
codecs.py: PCM/whatever ElevenLabs returns → μ-law 8kHz
        │
        ▼
FastAPI WS endpoint — base64-encodes, wraps in Twilio's "media" event, sends back over the same socket
```

### 4.1 Component communication
- **Twilio ↔ FastAPI:** one long-lived WebSocket per call. Twilio sends a `start` event once (carrying `streamSid`, `callSid`), then a continuous stream of `media` events (base64 μ-law), then `stop`. Your endpoint must echo `streamSid` on every outbound `media` event or Twilio silently drops it — this is one of the most common causes of exactly the "agent never speaks" symptom you're migrating to fix, so it's worth checking first regardless of framework.
- **FastAPI ↔ Deepgram:** a second, independent WebSocket per call, opened when the Twilio stream starts. Audio bytes forwarded essentially 1:1 (after any needed resampling); Deepgram pushes partial and final transcript JSON messages back asynchronously.
- **FastAPI ↔ Gemini:** not a persistent connection — a streaming request per conversational turn, using the `google-genai` SDK's streaming call, yielding chunks as an async generator.
- **FastAPI ↔ ElevenLabs:** a WebSocket (ElevenLabs supports streaming input-text/output-audio over WS) opened per turn or kept warm per call, depending on which gives better latency in your testing — start per-turn for simplicity, optimize to a kept-open connection only if profiling shows connection setup is a meaningful chunk of your latency budget.

### 4.2 Lifecycle of a phone call
1. Twilio hits `POST /twilio/voice` → your existing TwiML response (unchanged) tells Twilio to open the Media Stream.
2. Twilio opens `WS /twilio/media-stream`. Your handler accepts it, reads the `start` event, extracts `callSid`/`streamSid`, instantiates a `CallSession`.
3. `CallSession` opens its Deepgram WebSocket and starts the VAD loop; both run as background asyncio tasks fed by incoming Twilio `media` events.
4. Caller speaks → Deepgram streams partials → VAD/Deepgram endpointing signals turn-end → `CallSession` finalizes the transcript and calls into `gemini_stream`.
5. Gemini streams back text (and/or a tool call, executed inline, with its result fed back into the same Gemini turn per your existing tool-calling loop from Phase 3/5).
6. As sentence-sized chunks of Gemini's output become available, they're pushed into `elevenlabs_stream`, which starts returning audio almost immediately rather than waiting for the full reply.
7. Audio chunks are transcoded and sent back over the Twilio WebSocket as they arrive — this is what makes the reply start playing quickly instead of after a long dead-air wait.
8. If the caller speaks while TTS audio is still being sent (barge-in) — see §4.2 barge-in below.
9. On `stop` event or socket close: `CallSession` closes its Deepgram/ElevenLabs connections, finalizes the transcript, persists it via `call_logger.py` (unchanged), and finalizes any captured `Lead` — same as current Phase 5 behavior, just triggered from your own cleanup code instead of Pipecat's pipeline teardown.

### Connection management
- One `CallSession` object per call, keyed by `callSid`, held in an in-memory dict on the FastAPI app (or `app.state`) for the process lifetime of that call — this replaces whatever registry Pipecat maintained internally.
- Each `CallSession` owns exactly two outbound connections (Deepgram, ElevenLabs) plus the one inbound Twilio socket it was constructed from. All three need explicit try/finally cleanup so a crash on one doesn't leak the others.

### Session management
- Session state lives entirely in the `CallSession` instance — no shared global mutable state across calls, which also makes concurrent calls (once you're past solo-dev testing) safe by construction rather than by accident.

### Error recovery / reconnection strategy
- **Twilio socket:** if it drops mid-call, there's no reconnecting to the same call — treat it as call-end, run normal cleanup, log the abnormal termination distinctly from a normal hangup so Phase 8's analytics can tell the difference.
- **Deepgram socket:** if it drops mid-call, attempt one immediate reconnect with the same session context; if that fails, fall back to a "sorry, having trouble hearing you" TTS line and a graceful handoff/end rather than a silent failure — this directly targets the symptom you're currently fighting.
- **ElevenLabs socket:** same pattern — one reconnect attempt, then fall back to a pre-recorded apology + handoff rather than dead air.
- **Gemini call:** wrap in a timeout; on failure or timeout, fall back to a scripted "let me get someone to help you" line and trigger `handoff.py` rather than hanging.

### Conversation state management
- Reuses your existing Phase 3 conversation-history structure (whatever `CustomGeminiLLMService` already expects) — the orchestrator just needs to hold that history inside `CallSession` and pass it into each turn's Gemini call, same shape as before, different caller.

### Async task management
- Per call, expect roughly: 1 task reading the Twilio WS, 1 task running the Deepgram receive loop, 1 task running VAD, and short-lived tasks per turn for the Gemini→TTS chunk-streaming pipeline. Use `asyncio.TaskGroup` (Python 3.11+, matches your stated 3.11+ target) per `CallSession` so a failure in any subtask can be caught and the whole session torn down cleanly instead of leaking orphaned tasks.

### Queue management
- An `asyncio.Queue` between "Gemini token stream" and "TTS input" is the cleanest way to implement the sentence-chunker without tightly coupling the two streaming clients — the chunker task pulls tokens, pushes completed chunks onto the queue, and the TTS task consumes from it. This also gives you a natural place to insert the barge-in cancellation.

### Logging strategy
- Log at every hop with the `callSid` as a correlation ID: Twilio frame received, Deepgram partial/final, Gemini turn start/end (with tool calls named), TTS chunk sent, Twilio frame sent. Given your specific bug history (no audio reaching the caller), having an explicit log line for "TTS audio chunk written to Twilio socket" is the single highest-value line to add — if that line never fires, you've isolated the bug to before that point; if it fires but the caller hears nothing, the bug is Twilio-side (streamSid mismatch, wrong track, closed socket).

### Performance optimization
- Start ElevenLabs synthesis on the first complete sentence rather than waiting for Gemini's full response — this is the single biggest latency win and directly targets the ~1.2–1.5s round-trip budget from your original INDEX.md risk #1.
- Keep Deepgram and ElevenLabs connections warm across turns within the same call (open once at call-start, not once per turn) if your testing shows connection setup time matters — validate with the same latency-logging approach from your original Phase 2 rather than assuming.

### 4.1 Audio Transcoding & Sample Rate Handling
- **Twilio → your app:** 8kHz μ-law, base64-encoded, ~20ms frames per Twilio's Media Streams spec.
- **Deepgram:** accepts μ-law directly if you tell it the encoding (`encoding=mulaw&sample_rate=8000` on the streaming connection) — **no transcoding needed on the inbound leg if you configure Deepgram correctly.** This is worth double-checking against current Deepgram docs before writing conversion code you don't need.
- **Gemini:** text in, text out for the conversational turn — no audio touches Gemini directly in this architecture (you're not using Gemini's native audio-in/out mode, based on your stack description), so no transcoding concern here.
- **ElevenLabs streaming output:** typically PCM at a configurable sample rate (commonly 16kHz or higher) or μ-law if you request it directly — **check whether ElevenLabs' streaming API supports requesting 8kHz μ-law output directly**, since if it does, you can skip transcoding entirely on the outbound leg too, same as Deepgram inbound. If not, you need PCM→μ-law + resample-to-8kHz on every outbound chunk.
- **Where conversions happen:** all conversion logic lives in `agent/audio/codecs.py` as pure, synchronous, dependency-light functions (avoid pulling in heavy audio libraries if `audioop`-equivalent logic or a small numpy routine suffices — μ-law encode/decode and simple linear resampling don't need a heavyweight DSP library).
- **Recommended approach:** confirm both vendors' native format support first (§ above) — the fastest, lowest-latency, and lowest-bug-surface path is configuring Deepgram/ElevenLabs to match Twilio's 8kHz μ-law directly and doing zero transcoding, rather than defaulting to a resampling pipeline you don't actually need. Only build the resampler if one vendor genuinely can't match the format.
- **Low-latency implementation strategy:** process audio in the same small frame sizes Twilio sends (~20ms) rather than buffering into larger chunks before conversion — buffering for "efficiency" here directly fights your latency budget.

### 4.2 Barge-In (User Interruption)
- **Detection:** VAD running continuously on the *inbound* audio stream, independent of whatever the outbound TTS is doing. The moment VAD flags speech onset while `CallSession.state == "speaking"`, that's your interruption trigger — no need to wait for Deepgram's endpointing here, VAD's speech-onset signal alone is enough to react fast.
- **STT continuity:** Deepgram's streaming connection should already be running continuously regardless of TTS playback state — you're always listening, so no special handling needed to "keep STT running," just make sure you never pause forwarding audio to Deepgram while TTS plays.
- **Stopping AI speech immediately:** on interruption trigger, (a) cancel the `elevenlabs_stream` task feeding audio out — call its `cancel()`/close the WS, (b) stop pulling from the token→TTS queue, (c) crucially, send Twilio's `clear` event on the Media Stream WS immediately — this tells Twilio to flush any audio you've already sent that hasn't played yet, which is necessary because otherwise the caller keeps hearing buffered audio for a moment even after you stop sending new chunks.
- **Cancelling active Gemini generation:** cancel the asyncio task driving the Gemini streaming call (`task.cancel()`) so token generation stops server-side-request-wise as soon as possible; don't let it keep streaming into a queue nobody's reading.
- **Stopping ElevenLabs synthesis:** close or reset the ElevenLabs streaming connection for that turn rather than trying to "pause" it — cleaner state, and you'll open a fresh one for the next turn anyway.
- **Resuming the conversation:** the caller's new speech, already being captured by the continuously-running Deepgram connection, becomes the next turn's input once VAD/Deepgram signals turn-end — `CallSession.state` transitions back to `listening`, then the pipeline runs forward exactly as in §4's normal lifecycle.
- **Avoiding race conditions:** the main hazard is a TTS audio chunk that was already in-flight to the Twilio socket landing *after* you've sent `clear` — guard this with a per-turn generation counter/token: every chunk carries the turn ID it belongs to, and the send loop drops any chunk whose turn ID doesn't match `CallSession.current_turn_id` (bumped on every interruption). This is a standard pattern for exactly this class of bug and is worth building in from the start rather than retrofitting after you hit the race in testing.
- **Best practices:** keep the interruption path short and dumb (cancel tasks, send `clear`, bump the turn counter) — resist the urge to make the interruption handler "smart" (e.g., trying to splice in a partial acknowledgment); that complexity is exactly what made Pipecat's abstraction valuable, and re-implementing it minimally, not cleverly, is the safer choice for a hand-rolled version.

---

## 5. Development Order

Each step is scoped to be independently testable, so you're never debugging two unknowns at once.

### Step 1 — Audio codec utilities (isolated, no network)
- **Objective:** Prove μ-law/PCM/resampling logic is correct in isolation.
- **Files:** `agent/audio/codecs.py`
- **Dependencies:** None.
- **Expected output:** Pure functions, unit-testable with a known sample WAV/μ-law fixture (you already have `data/samples/` audio — reuse it).
- **Testing approach:** Round-trip test — encode then decode a known clip, diff against original; confirm output byte length matches Twilio's expected frame size.
- **Success criteria:** Round-trip audio is bit-identical (or within acceptable lossy tolerance for μ-law) and frame sizes match Twilio's spec.

### Step 2 — Raw Twilio WebSocket echo (no STT/LLM/TTS yet)
- **Objective:** Confirm the raw FastAPI WS can receive Twilio's `start`/`media`/`stop` events and send audio back that Twilio actually plays — this is the exact layer your current bug lives in, so proving it in total isolation first is critical.
- **Files:** `backend/app/routes/twilio_voice.py` (temporary echo-mode branch, or a scratch script), reusing `backend/static/welcome.wav` from Phase 1.
- **Dependencies:** Step 1 (codecs) if `welcome.wav` isn't already 8kHz μ-law.
- **Expected output:** Calling the Twilio number plays back the static welcome clip, exactly like your original Phase 1 acceptance test — the same test, on the new transport.
- **Testing approach:** Live test call, listen for the clip.
- **Success criteria:** You hear the clip. If you don't, the bug is isolated to this transport layer, before any vendor complexity is added — the single most valuable checkpoint in this whole migration.

### Step 3 — Deepgram streaming client, standalone
- **Objective:** Confirm the raw Deepgram streaming client (promoted from your Phase 2 script) correctly transcribes live-forwarded call audio.
- **Files:** `agent/streaming/deepgram_stream.py`
- **Dependencies:** Step 2 (need real inbound audio to feed it).
- **Expected output:** Live transcripts logged during a real call, echo response unchanged (still playing the static clip).
- **Testing approach:** Live test call, speak, watch transcript logs.
- **Success criteria:** Partial and final transcripts appear with reasonable latency, matching or beating your original Phase 2 benchmark numbers.

### Step 4 — ElevenLabs streaming client, standalone
- **Objective:** Confirm the raw ElevenLabs streaming client produces audio Twilio will actually play, replacing the static clip with dynamic (but not yet LLM-driven) TTS.
- **Files:** `agent/streaming/elevenlabs_stream.py`
- **Dependencies:** Step 1 (codecs, if transcoding is needed per §4.1).
- **Expected output:** Calling in plays a synthesized (not pre-recorded) greeting.
- **Testing approach:** Live test call.
- **Success criteria:** Synthesized audio is heard clearly, latency to first audio byte matches or beats Phase 2's benchmark.

### Step 5 — VAD integration
- **Objective:** Detect speech start/end on live call audio without yet acting on it.
- **Files:** `agent/audio/vad.py`
- **Dependencies:** Step 2.
- **Expected output:** Log lines for speech-start/speech-end events during a live call.
- **Testing approach:** Live test call, talk and pause, confirm log events line up with actual speech.
- **Success criteria:** VAD events match your actual speech timing within a reasonable margin.

### Step 6 — CallSession wiring: STT → Gemini → TTS, no interruption handling yet
- **Objective:** Full happy-path turn: caller speaks, Deepgram transcribes, Gemini responds (reusing existing tool-calling loop unchanged), ElevenLabs speaks it back.
- **Files:** `agent/session/call_session.py`, `agent/streaming/gemini_stream.py`, wiring in `agent/pipeline.py`
- **Dependencies:** Steps 1–5.
- **Expected output:** This is essentially the original Phase 5 acceptance test — "call in, ask to find/check a city, get a sensible spoken answer, a Lead row created if applicable."
- **Testing approach:** Live test call following your original Phase 5 checklist.
- **Success criteria:** Matches your original Phase 5 acceptance criteria exactly.

### Step 7 — Barge-in handling
- **Objective:** Implement the turn-ID-guarded interruption path from §4.2.
- **Files:** `agent/session/call_session.py` (extended), `agent/streaming/elevenlabs_stream.py` (add `cancel()`)
- **Dependencies:** Step 6.
- **Expected output:** Interrupting mid-sentence stops playback promptly and the agent responds to the new input.
- **Testing approach:** Live test call, deliberately talk over the agent.
- **Success criteria:** No audio overlap/race, agent responds to what you actually said, matches original Phase 5's barge-in acceptance criteria.

### Step 8 — Error recovery paths
- **Objective:** Verify the fallback behaviors from §4 (Deepgram/ElevenLabs/Gemini failures) degrade gracefully instead of hanging.
- **Files:** `agent/session/call_session.py` (extended)
- **Dependencies:** Step 7.
- **Expected output:** Simulated failures (e.g., temporarily invalidate an API key, or add a forced exception) result in a graceful apology + handoff, not dead air.
- **Testing approach:** Deliberately trigger each failure mode individually.
- **Success criteria:** Every simulated failure produces an audible, sensible response rather than silence or a crash.

### Step 9 — Outbound calls re-validation (Phase 6)
- **Objective:** Confirm `internal_callback.py` still correctly originates calls into the new pipeline with the right `opening_intent`.
- **Files:** Likely none, or a small adjustment if it referenced Pipecat internals.
- **Dependencies:** Step 6.
- **Expected output:** Same as original Phase 6 acceptance test.
- **Testing approach:** Trigger the endpoint for your own verified number.
- **Success criteria:** Matches original Phase 6 criteria.

### Step 10 — Full Phase 8 checklist re-run
- **Objective:** Re-validate every scenario from your original test-call checklist against the new pipeline.
- **Files:** None new — `docs/test_call_checklist.md` if it exists, reused as-is.
- **Dependencies:** Steps 1–9 all passing.
- **Expected output:** Full checklist pass.
- **Testing approach:** As originally scoped in Phase 8.
- **Success criteria:** Matches original Phase 8 acceptance criteria.

---

## 6. Preserving Existing Functionality — Explicit Confirmation

| Component | Preserved as-is? |
|---|---|
| System prompt (`system_prompt.md`) | Yes — no changes needed. |
| FAQ retrieval (`get_faq.py`) | Yes — called the same way from Gemini's tool-calling loop. |
| Lead capture (`capture_lead.py`) | Yes — same function, same `data/leads.json` target. |
| City coverage (`check_city_coverage.py`) | Yes — unchanged. |
| Call handoff (`handoff.py`) | Yes — unchanged logic; only the *transport-level* reaction (ending the WS cleanly) moves into `call_session.py`. |
| Logging (`call_logger.py`) | Yes — unchanged, still called on call-end. |
| Analytics (Phase 8 scripts) | Yes — reads the same `calls.json`/`leads.json` shape, unaffected by the transport rewrite. |
| Backend routes (`internal_callback.py`, the TwiML half of `twilio_voice.py`) | Yes, mostly — see §1.4/§3 for the one route that's rewritten. |
| Data storage (`data/*.json`) | Yes — completely unaffected; the migration is upstream of storage. |

**Nothing about your business logic, persona, tool-calling contract, or data model changes.** The blast radius is fully contained to: how audio physically gets from Twilio to your STT/LLM/TTS calls and back, and how interruption is detected and enforced.

---

## 7. Design Principles Applied

- **Low latency:** streaming at every stage (§4.2 optimization notes), native-format audio where possible to avoid transcoding overhead (§4.1), sentence-boundary TTS chunking rather than wait-for-full-response.
- **Privacy/security:** no new data leaves your existing vendor set (Twilio/Deepgram/Gemini/ElevenLabs) — the migration doesn't introduce new third parties.
- **Production readiness / maintainability:** explicit, inspectable stages (§1.6 file layout) instead of a framework's implicit frame graph — directly targets your stated pain point of not being able to debug why audio wasn't flowing.
- **Modular design / separation of responsibilities:** `audio/`, `streaming/`, `session/` cleanly separate "format conversion," "vendor I/O," and "call state," so a bug in one is easy to isolate (this is the whole point of the Development Order in §5 being staged the way it is).
- **Async-first:** `asyncio.TaskGroup`-based per-call task management (§4, async task management).
- **Minimal unnecessary dependencies:** no new orchestration framework; only the vendor SDKs/clients you already have keys for, plus VAD and audio-utility libraries you likely already had via Pipecat's own dependency tree.

---

## Open questions worth confirming before Step 1

1. **Root cause first?** Given §2 risk 2 — is it worth a short diagnostic pass on the *current* Pipecat pipeline (verbose logging on one test call) to confirm the "doesn't speak" bug isn't something format/config-level that would resurface in the rewrite too?
2. **Docker timing** — your task doc lists Docker as a later deployment target, which differs from the original Phase 9's "no Docker in v1." Confirming this doesn't affect the migration itself, but worth flagging so Phase 9 planning isn't a surprise later.
3. **ElevenLabs/Deepgram native format support** — confirming both vendors' current docs for direct 8kHz μ-law support (§4.1) before deciding whether `codecs.py` needs a full resampler or just μ-law encode/decode.
