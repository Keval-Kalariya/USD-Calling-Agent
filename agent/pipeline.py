"""
Framework-agnostic voice pipeline orchestrator replacing legacy Pipecat pipeline.
Coordinates Twilio Media Streams, Deepgram real-time STT, Gemini LLM token streaming,
sentence boundary chunking, and ElevenLabs real-time TTS synthesis.
"""

import os
import asyncio
import json
import base64
import inspect
import audioop
from datetime import datetime, timezone
from typing import Optional

from backend.app.settings import settings
from agent.audio.codecs import mulaw_to_pcm16
from agent.audio.vad import SileroVADStream
from agent.streaming.deepgram_stream import DeepgramStreamClient
from agent.streaming.elevenlabs_stream import ElevenLabsStreamClient
from agent.streaming.gemini_tts_stream import GeminiTTSStreamClient
from agent.streaming.gemini_stream import GeminiStreamClient
from agent.streaming.gemini_live_stream import GeminiLiveStreamClient
from agent.session.call_session import CallSession


class VoicePipelineOrchestrator:
    """
    Orchestrates real-time bi-directional conversational voice turns for a single phone call.
    """
    def __init__(
        self,
        websocket,
        call_id: str,
        stream_sid: str,
        opening_intent: Optional[str] = None,
        lead_id: Optional[str] = None,
        lead_name: Optional[str] = None,
        lead_city: Optional[str] = None
    ):
        self.websocket = websocket
        self.call_id = call_id
        self.stream_sid = stream_sid
        self.opening_intent = opening_intent
        self.lead_id = lead_id
        self.lead_name = lead_name
        self.lead_city = lead_city

        # Determine greeting based on call intent
        if self.opening_intent == "follow-up":
            name = self.lead_name or "there"
            city = self.lead_city or "your city's"
            self.greeting = (
                f"Hi {name}, this is Kiara from Ultimate Smile Design, "
                f"following up on your {city} smile consultation enquiry. How can I help you today? "
                f"Which language would you prefer to speak? English, Hindi, or Gujarati?"
            )
        else:
            self.greeting = (
                "Hello! Thank you for calling Ultimate Smile Design. "
                "My name is Kiara. Which language would you like to speak? English, Hindi, or Gujarati?"
            )

        # Initialize core components & determine voice engine mode
        self.session = CallSession(call_id=call_id, opening_intent=opening_intent, lead_id=lead_id)
        self.pipeline_mode = (os.environ.get("PIPELINE_MODE") or getattr(settings, "PIPELINE_MODE", "cascaded")).strip().lower()

        if self.pipeline_mode == "live":
            print(f"[Orchestrator] Pipeline Mode: LIVE (using GeminiLiveStreamClient for CallSid: {call_id})")
            from agent.tools.check_city_coverage import check_city_coverage
            from agent.tools.capture_lead import capture_lead
            from agent.tools.get_faq import get_faq
            from agent.tools.handoff import human_handoff

            def live_capture_lead(**kwargs):
                kwargs.setdefault("call_id", self.call_id)
                kwargs.setdefault("preferred_language", self.session.preferred_language)
                res = capture_lead(**kwargs)
                self.session.update_user_info(
                    name=kwargs.get("name"),
                    phone=kwargs.get("phone"),
                    city=kwargs.get("city"),
                    intent=kwargs.get("intent"),
                    notes=kwargs.get("notes")
                )
                return res

            def live_check_city(**kwargs):
                res = check_city_coverage(**kwargs)
                if kwargs.get("city"):
                    self.session.update_user_info(city=kwargs.get("city"))
                return res

            def live_get_faq(**kwargs):
                kwargs.setdefault("language", self.session.preferred_language)
                res = get_faq(**kwargs)
                if kwargs.get("topic"):
                    self.session.update_topic(kwargs.get("topic"))
                return res

            def live_handoff(**kwargs):
                kwargs.setdefault("call_id", self.call_id)
                res = human_handoff(**kwargs)
                self.session.booking_stage = "handoff"
                return res

            live_tool_mapping = {
                "capture_lead": live_capture_lead,
                "check_city_coverage": live_check_city,
                "get_faq": live_get_faq,
                "human_handoff": live_handoff,
            }

            self.gemini_live_client = GeminiLiveStreamClient(
                call_id=call_id,
                preferred_language="multi",
                initial_greeting=self.greeting,
                tool_mapping=live_tool_mapping
            )
            self.dg_client = None
            self.tts_client = None
            self.gemini_client = None
            self.vad_client = None
            self.tts_provider_name = "Gemini Live"
            self.mulaw_frame_size = 160
            self.output_buffer = bytearray()
        else:
            print(f"[Orchestrator] Pipeline Mode: CASCADED (using Deepgram -> Gemini -> TTS for CallSid: {call_id})")
            self.gemini_live_client = None
            self.dg_client = DeepgramStreamClient(
                sample_rate=8000,
                encoding="mulaw",
                language="multi",
                on_transcript=self._on_stt_transcript,
                on_unexpected_disconnect=self._on_dg_unexpected_disconnect,
                on_reconnect=self._on_dg_reconnected
            )
            provider = (os.environ.get("TTS_PROVIDER") or getattr(settings, "TTS_PROVIDER", "elevenlabs")).strip().lower()
            if provider == "elevenlabs":
                self.tts_client = ElevenLabsStreamClient()
                self.tts_provider_name = "ElevenLabs"
                print("[Orchestrator] TTS Provider selected: elevenlabs (using ElevenLabsStreamClient)")
            elif provider == "gemini":
                self.tts_client = GeminiTTSStreamClient()
                self.tts_provider_name = "Gemini"
                print("[Orchestrator] TTS Provider selected: gemini (using GeminiTTSStreamClient)")
            else:
                raise ValueError(f"Unsupported TTS_PROVIDER value: '{provider}'. Supported values are 'elevenlabs' and 'gemini'.")
            self.gemini_client = GeminiStreamClient(
                call_id=call_id,
                preferred_language="multi",
                initial_greeting=self.greeting
            )
            self.vad_client = SileroVADStream(sample_rate=8000, threshold=0.5, window_size_samples=256)
        
        # Turn state synchronization
        self._active_turn_task: Optional[asyncio.Task] = None
        self._turn_trigger_task: Optional[asyncio.Task] = None
        self._stt_final_received: asyncio.Event = asyncio.Event()
        self._is_running: bool = False
        self._stopped: bool = False
        self.barge_in_frame_threshold: int = 15  # ~300ms sustained VAD speech onset threshold to prevent speaker echo false triggers
        self._barge_in_speech_frames: int = 0

    def _on_stt_transcript(self, text: str, is_final: bool) -> None:
        """Callback invoked whenever Deepgram emits a partial or final transcript."""
        if self.vad_client is None:
            return
        if self.session.state == "listening":
            self.session.append_stt_fragment(text, is_final)
            if is_final:
                self._stt_final_received.set()
                # If VAD speech already ended and no turn trigger task is active, check if we should trigger turn
                if self.vad_client is not None and not self.vad_client.is_speaking and (self._turn_trigger_task is None or self._turn_trigger_task.done()):
                    self._turn_trigger_task = asyncio.create_task(self._wait_and_trigger_turn())
        elif self.session.state in ("speaking", "thinking"):
            # Word-level confidence barge-in check to catch interruption while assistant speaks
            clean_text = text.strip()
            word_count = len(clean_text.split())
            if (is_final and len(clean_text) >= 3) or (word_count >= 2 and self.vad_client is not None and self.vad_client.is_speaking):
                asyncio.create_task(self._confirm_barge_in(reason=f"STT confidence interruption ('{clean_text[:30]}')", initial_text=clean_text, is_final=is_final))

    async def _confirm_barge_in(self, reason: str, initial_text: Optional[str] = None, is_final: bool = False) -> None:
        """
        Executes immediate production-grade barge-in cancellation when caller interruption is confirmed.
        Halts generative loops, dumps Twilio playback buffer via WebSocket clear event, and restores listening state.
        """
        if self.session.state == "listening" or self._stopped or self.vad_client is None:
            return  # Turn already ended or call stopped
            
        print(f"[Orchestrator] Barge-in confirmed ({reason})! Cancelling active assistant turn and clearing Twilio playback buffer.")
        self._barge_in_speech_frames = 0
        
        # 1. Immediately cancel active turn generation and TTS streaming tasks
        if self._active_turn_task and not self._active_turn_task.done():
            self._active_turn_task.cancel()
        if self._turn_trigger_task and not self._turn_trigger_task.done():
            self._turn_trigger_task.cancel()
            
        # 2. Flush all pending items from TTS sentence queue
        while not self.session.tts_queue.empty():
            try:
                self.session.tts_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
                
        # 3. Send Twilio Media Streams 'clear' event to empty playback audio buffer instantaneously
        if self.websocket and not getattr(self.websocket, "client_state", None) == "DISCONNECTED":
            try:
                await self.websocket.send_text(json.dumps({
                    "event": "clear",
                    "streamSid": self.stream_sid
                }))
                print(f"[Orchestrator] Sent Twilio 'clear' event to immediately dump cellular audio buffer for StreamSid: {self.stream_sid}")
            except Exception as e:
                print(f"[Orchestrator Warning] Failed to send Twilio clear event during barge-in: {e}")

        # 4. Transition session back to listening state and reset synchronization flags
        self.session.transition_state("listening")
        self._stt_final_received.clear()
        
        # 5. Continue capturing caller's interrupting speech without restarting call session
        if initial_text:
            self.session.append_stt_fragment(initial_text, is_final=is_final)
            if is_final and self.vad_client is not None and not self.vad_client.is_speaking:
                self._stt_final_received.set()
                if self._turn_trigger_task is None or self._turn_trigger_task.done():
                    self._turn_trigger_task = asyncio.create_task(self._wait_and_trigger_turn())

    def _on_dg_unexpected_disconnect(self) -> None:
        """Sanitization hook executed ONLY upon unexpected Deepgram network disconnection."""
        print("[Orchestrator] Unexpected STT disconnection detected. Sanitizing stale interim state.")
        if self._turn_trigger_task and not self._turn_trigger_task.done():
            self._turn_trigger_task.cancel()
            self._turn_trigger_task = None
        self.session.purge_interim_state()

    def _on_dg_reconnected(self) -> None:
        """Reset turn synchronization flags upon successful STT reconnection."""
        print("[Orchestrator] STT reconnection confirmed. Resetting turn synchronization event.")
        self._stt_final_received.clear()

    async def _send_buffered_live_audio(self) -> None:
        """Send buffered audio to Twilio WebSocket in consistent 160-byte (20ms) mulaw frames in live mode."""
        while len(self.output_buffer) >= getattr(self, "mulaw_frame_size", 160) and self._is_running:
            frame = bytes(self.output_buffer[:self.mulaw_frame_size])
            del self.output_buffer[:self.mulaw_frame_size]
            payload = base64.b64encode(frame).decode("utf-8")
            media_message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": payload},
            }
            if self.websocket and not getattr(self.websocket, "client_state", None) == "DISCONNECTED":
                try:
                    await self.websocket.send_text(json.dumps(media_message))
                except Exception as e:
                    print(f"[Orchestrator Warning] Failed to send buffered live audio: {e}")
                    break
            else:
                break

    async def _on_live_audio_output(self, data: bytes) -> None:
        """Callback for Gemini Live audio output chunks (24kHz 16-bit PCM)."""
        if not self._is_running or self._stopped or not self.stream_sid:
            return
        try:
            intermediate, _ = audioop.ratecv(data, 2, 1, 24000, 16000, None)
            resampled_data, _ = audioop.ratecv(intermediate, 2, 1, 16000, 8000, None)
            mulaw_data = audioop.lin2ulaw(resampled_data, 2)
            self.output_buffer.extend(mulaw_data)
            self.session.transition_state("speaking")
            await self._send_buffered_live_audio()
        except Exception as e:
            print(f"[Orchestrator Error] Error sending live audio to Twilio: {e}")

    async def _on_live_interruption(self) -> None:
        """Callback invoked when Gemini Live detects caller interruption (barge-in)."""
        if self._stopped:
            return
        print("[Orchestrator] Gemini Live server interruption received! Clearing output buffer and Twilio stream.")
        self.output_buffer.clear()
        self.session.transition_state("listening")
        if self.websocket and not getattr(self.websocket, "client_state", None) == "DISCONNECTED":
            try:
                await self.websocket.send_text(json.dumps({
                    "event": "clear",
                    "streamSid": self.stream_sid
                }))
                print(f"[Orchestrator] Sent Twilio 'clear' event for StreamSid: {self.stream_sid}")
            except Exception as e:
                print(f"[Orchestrator Warning] Failed to send Twilio clear event during live interruption: {e}")

    async def _on_live_event(self, event: dict) -> None:
        """Callback for general Gemini Live events (transcripts, turn completions, tool calls)."""
        if not event or not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "user":
            text = event.get("text", "").strip()
            if text:
                print(f"[Live STT Transcript] User: '{text}'")
                self.session.add_transcript(text, role="user")
                self.session.update_language_if_requested(text)
        elif event_type == "gemini":
            text = event.get("text", "").strip()
            if text:
                print(f"[Live Output Transcript] Assistant: '{text}'")
                self.session.add_transcript(text, role="assistant")
        elif event_type == "turn_complete":
            self.session.transition_state("listening")
            print("[Orchestrator] Live turn complete; transitioned to listening.")
        elif event_type == "error":
            print(f"[Orchestrator Error] Gemini Live event error: {event.get('error')}")

    async def start(self) -> None:
        """Starts the voice pipeline connections and initiates the opening greeting."""
        self._is_running = True
        print(f"[Orchestrator] Starting voice pipeline for CallSid: {self.call_id}, StreamSid: {self.stream_sid} (Mode: {self.pipeline_mode.upper()})")
        
        if self.pipeline_mode == "live":
            self.session.add_transcript(self.greeting, role="assistant")
            self.session.transition_state("listening")
            try:
                if self.gemini_live_client:
                    await self.gemini_live_client.connect(
                        audio_output_callback=self._on_live_audio_output,
                        audio_interrupt_callback=self._on_live_interruption,
                        event_callback=self._on_live_event,
                    )
                    await self.gemini_live_client.send_text(f"Greet the caller by saying exactly: '{self.greeting}' and wait for their reply.")
            except Exception as e:
                print(f"[Orchestrator] Failed to open Gemini Live connection: {e}")
                await self.stop()
                try:
                    await self.websocket.close()
                except Exception:
                    pass
            return

        if self.dg_client is None:
            print("[Orchestrator] Deepgram client is not initialized in cascaded mode.")
            await self.stop()
            try:
                await self.websocket.close()
            except Exception:
                pass
            return

        try:
            if self.dg_client is not None:
                await self.dg_client.connect()
        except Exception as e:
            print(f"[Orchestrator] Failed to open Deepgram connection: {e}")
            await self.stop()
            try:
                await self.websocket.close()
            except Exception:
                pass
            return

        # Record opening greeting in session history and speak it
        self.session.add_transcript(self.greeting, role="assistant")
        self.session.transition_state("speaking")
        self._active_turn_task = asyncio.create_task(self._play_greeting())

    async def _play_greeting(self) -> None:
        """Plays the opening greeting with complete exception and task lifecycle cleanup."""
        try:
            await self._play_tts_text(self.greeting)
        except asyncio.CancelledError:
            print("[Orchestrator] Opening greeting playback cancelled.")
        except Exception as e:
            print(f"[Orchestrator Error] Exception during greeting playback: {e}")
        finally:
            self.session.transition_state("listening")
            if self._active_turn_task and asyncio.current_task() is self._active_turn_task:
                self._active_turn_task = None

    async def handle_media_payload(self, ulaw_base64: str) -> None:
        """
        Processes an inbound chunk of 8kHz ulaw audio from Twilio Media Streams.
        """
        if not self._is_running:
            return

        # Decode base64 to ulaw bytes
        audio_bytes = base64.b64decode(ulaw_base64)
        
        if self.pipeline_mode == "live":
            if self.gemini_live_client and not getattr(self.gemini_live_client, "_closed", False):
                try:
                    pcm8k = audioop.ulaw2lin(audio_bytes, 2)
                    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
                    await self.gemini_live_client.send_audio(pcm16k)
                except Exception as e:
                    print(f"[Orchestrator Error] Failed to process and send live audio: {e}")
            return

        if self.dg_client is None or self.vad_client is None:
            return

        # Send raw ulaw audio directly to Deepgram STT stream
        if self.dg_client is not None:
            await self.dg_client.send_audio(audio_bytes)

        pcm_bytes = mulaw_to_pcm16(audio_bytes)
        if self.vad_client is not None:
            vad_events = self.vad_client.process_audio(pcm_bytes)
        else:
            vad_events = []
        
        if self.session.state == "listening":
            self._barge_in_speech_frames = 0
            for event in vad_events:
                if event == "speech_started":
                    # Speech onset detected while listening: user is speaking or resumed speaking
                    if self._turn_trigger_task and not self._turn_trigger_task.done():
                        print("[Orchestrator] Speech resumed before turn triggered. Cancelling turn wait task.")
                        self._turn_trigger_task.cancel()
                        try:
                            await self._turn_trigger_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        self._turn_trigger_task = None
                    self._stt_final_received.clear()
                elif event == "speech_ended":
                    print("[Orchestrator] VAD speech_ended detected. Waiting for Deepgram final transcript before triggering LLM...")
                    if self._turn_trigger_task is None or self._turn_trigger_task.done():
                        self._turn_trigger_task = asyncio.create_task(self._wait_and_trigger_turn())
        elif self.session.state in ("speaking", "thinking"):
            # Continuous VAD monitoring for telephony barge-in while assistant speaks
            if self.vad_client is not None and self.vad_client.is_speaking:
                self._barge_in_speech_frames += 1
                if self._barge_in_speech_frames >= getattr(self, "barge_in_frame_threshold", 15):
                    await self._confirm_barge_in(reason=f"Sustained VAD speech onset ({self._barge_in_speech_frames} frames)")
            else:
                self._barge_in_speech_frames = 0

    async def _wait_and_trigger_turn(self) -> None:
        """
        Waits for Deepgram to emit a final transcript (is_final=True) for the current utterance
        after speech ends, guaranteeing complete sentences before calling the LLM.
        """
        try:
            # Wait up to 350ms for Deepgram to send a final transcript if it hasn't already arrived
            if not self._stt_final_received.is_set():
                try:
                    await asyncio.wait_for(self._stt_final_received.wait(), timeout=0.35)
                except (TimeoutError, asyncio.TimeoutError):
                    print("[Orchestrator] Timeout (350ms) waiting for Deepgram is_final. Proceeding with buffered transcript.")
                    # Tiny grace settle (15ms) only when relying on unconfirmed interim buffer
                    await asyncio.sleep(0.015)
            # When is_final arrived cleanly, skip artificial delays to trigger LLM instantaneously
            
            # Ensure user did not resume speaking and STT connection is active during the wait
            if (
                self.vad_client is None
                or self.vad_client.is_speaking
                or not self._is_running
                or self.session.state != "listening"
                or self.dg_client is None
                or not self.dg_client._is_connected
            ):
                return

            # Reset synchronization flags
            self._stt_final_received.clear()
            
            # Invoke agent conversational turn
            await self._trigger_agent_turn()
            
        except asyncio.CancelledError:
            # Task was cancelled because the user resumed speaking
            pass
        finally:
            if self._turn_trigger_task and asyncio.current_task() is self._turn_trigger_task:
                self._turn_trigger_task = None

    async def _trigger_agent_turn(self) -> None:
        """Transitions from listening to thinking/speaking and runs the LLM -> TTS pipeline using verified finalized text."""
        # Get merged, deduplicated finalized text without wiping buffer or forcing interim text
        user_text = self.session.get_merged_transcript(include_interim=False)
        
        if not user_text:
            # No finalized speech transcribed (e.g. background noise, brief throat clear, or timeout on unconfirmed interim).
            # The safest behavior is to remain in listening state without triggering the LLM.
            print("[Orchestrator] No finalized transcript available. Staying in listening state without triggering LLM.")
            return

        self.session.transition_state("thinking")
        print(f"[Final Transcript Sent to LLM] {user_text}")
        self.session.add_transcript(user_text, role="user")
        
        # Spawn async turn task to generate conversational response
        self._active_turn_task = asyncio.create_task(self._run_turn_lifecycle(user_text))
        
        # Clear transcript buffers ONLY after the LLM has begun consuming them
        self.session.clear_transcripts()

    async def _run_turn_lifecycle(self, user_text: str) -> None:
        """Runs the Gemini streaming response loop and coordinates chunked TTS playback."""
        if self.gemini_client is None:
            return
        chunker_task: Optional[asyncio.Task] = None
        try:
            # Flush any stale items or sentinels in TTS queue from a previously interrupted turn
            while not self.session.tts_queue.empty():
                try:
                    self.session.tts_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                    
            if self.gemini_client is not None:
                token_stream = self.gemini_client.generate_turn_stream(user_text, session=self.session)
            else:
                return
            
            # Start sentence boundary chunker producer task
            chunker_task = asyncio.create_task(self.session.buffer_gemini_to_tts_queue(token_stream))
            
            self.session.transition_state("speaking")
            full_assistant_reply = []
            
            while True:
                sentence_chunk = await self.session.tts_queue.get()
                if sentence_chunk is None:
                    # End of turn sentinel received
                    break
                
                full_assistant_reply.append(sentence_chunk)
                await self._play_tts_text(sentence_chunk)
            
            if not chunker_task.done():
                await chunker_task
            
            final_reply_str = " ".join(full_assistant_reply).strip()
            if final_reply_str:
                self.session.add_transcript(final_reply_str, role="assistant")
            print(f"[Orchestrator] Turn finished. Assistant replied: '{final_reply_str}'")
            
        except asyncio.CancelledError:
            print("[Orchestrator] Turn lifecycle was cancelled.")
        except Exception as e:
            print(f"[Orchestrator Error] Exception during turn lifecycle: {e}")
        finally:
            if chunker_task and not chunker_task.done():
                print("[Orchestrator] Cancelling sentence boundary chunker task during turn cleanup...")
                chunker_task.cancel()
                try:
                    await chunker_task
                except (asyncio.CancelledError, Exception) as e:
                    if not isinstance(e, asyncio.CancelledError):
                        print(f"[Sentence Chunker Error] Exception retrieved during turn cancellation: {e}")
            self.session.transition_state("listening")
            if self._active_turn_task and asyncio.current_task() is self._active_turn_task:
                self._active_turn_task = None

    async def _play_tts_text(self, text: str) -> None:
        """Streams ulaw_8000 audio chunks from ElevenLabs directly to Twilio WebSocket."""
        if not text.strip() or self.tts_client is None:
            return
        try:
            if self.tts_client is not None:
                async for audio_chunk in self.tts_client.generate_stream(text):
                    if not self._is_running:
                        break
                    payload_b64 = base64.b64encode(audio_chunk).decode("utf-8")
                    media_message = {
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {
                            "payload": payload_b64
                        }
                    }
                    await self.websocket.send_text(json.dumps(media_message))
        except Exception as e:
            print(f"[Orchestrator Error] Failed to stream TTS for '{text}': {e}")

    async def stop(self) -> None:
        """Tears down client connections deterministically with robust exception isolation."""
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self._is_running = False
        print(f"[Orchestrator] Stopping voice pipeline for CallSid: {self.call_id}")
        
        # 1. Cancel and await active turn orchestration tasks so no running turn accesses clients during shutdown
        tasks_to_cancel = []
        if self._turn_trigger_task and not self._turn_trigger_task.done():
            self._turn_trigger_task.cancel()
            tasks_to_cancel.append(self._turn_trigger_task)
        if self._active_turn_task and not self._active_turn_task.done():
            self._active_turn_task.cancel()
            tasks_to_cancel.append(self._active_turn_task)
            
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self._turn_trigger_task = None
        self._active_turn_task = None
        
        # 2. Teardown streaming clients uniformly and in a deterministic order with exception isolation
        clients_to_close = []
        if self.pipeline_mode == "live":
            clients_to_close.append(("Gemini Live Client", getattr(self, "gemini_live_client", None)))
        else:
            clients_to_close.extend([
                ("Deepgram STT", getattr(self, "dg_client", None)), 
                ("Gemini LLM", getattr(self, "gemini_client", None)), 
                (f"{getattr(self, 'tts_provider_name', 'TTS')} Client", getattr(self, "tts_client", None))
            ])

        for client_name, client in clients_to_close:
            if client and hasattr(client, "finish"):
                try:
                    await client.finish()
                except Exception as e:
                    print(f"[Orchestrator Error] Failed to cleanly finish {client_name}: {e}")
            elif client and hasattr(client, "close"):
                try:
                    res = client.close()
                    if inspect.isawaitable(res):
                        await res
                except Exception as e:
                    print(f"[Orchestrator Error] Failed to cleanly close {client_name}: {e}")
                    
        print(f"[Orchestrator] Call Session complete. Total turns: {len(self.session.conversation_history)}")