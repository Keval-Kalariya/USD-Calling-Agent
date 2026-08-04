"""
Framework-agnostic voice pipeline orchestrator replacing legacy Pipecat pipeline.
Coordinates Twilio Media Streams, Deepgram real-time STT, Gemini LLM token streaming,
sentence boundary chunking, and ElevenLabs real-time TTS synthesis.
"""

import os
import asyncio
import json
import base64
from datetime import datetime, timezone
from typing import Optional

from backend.app.settings import settings
from agent.audio.codecs import mulaw_to_pcm16
from agent.audio.vad import SileroVADStream
from agent.streaming.deepgram_stream import DeepgramStreamClient
from agent.streaming.elevenlabs_stream import ElevenLabsStreamClient
from agent.streaming.gemini_tts_stream import GeminiTTSStreamClient
from agent.streaming.gemini_stream import GeminiStreamClient
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

        # Initialize core components
        self.session = CallSession(call_id=call_id, opening_intent=opening_intent, lead_id=lead_id)
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

    def _on_stt_transcript(self, text: str, is_final: bool) -> None:
        """Callback invoked whenever Deepgram emits a partial or final transcript."""
        if self.session.state == "listening":
            self.session.append_stt_fragment(text, is_final)
            if is_final:
                self._stt_final_received.set()
                # If VAD speech already ended and no turn trigger task is active, check if we should trigger turn
                if not self.vad_client.is_speaking and (self._turn_trigger_task is None or self._turn_trigger_task.done()):
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

    async def start(self) -> None:
        """Starts the voice pipeline connections and initiates the opening greeting."""
        self._is_running = True
        print(f"[Orchestrator] Starting voice pipeline for CallSid: {self.call_id}, StreamSid: {self.stream_sid}")
        try:
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
        
        # Send raw ulaw audio directly to Deepgram STT stream
        await self.dg_client.send_audio(audio_bytes)

        # In Step 6, to avoid self-interruption or speaker acoustic feedback without full barge-in guards,
        # we only monitor VAD turn transitions while in the "listening" state
        if self.session.state != "listening":
            return

        pcm_bytes = mulaw_to_pcm16(audio_bytes)
        vad_events = self.vad_client.process_audio(pcm_bytes)
        
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

    async def _wait_and_trigger_turn(self) -> None:
        """
        Waits for Deepgram to emit a final transcript (is_final=True) for the current utterance
        after speech ends, guaranteeing complete sentences before calling the LLM.
        """
        try:
            # Wait up to 800ms for Deepgram to send a final transcript if it hasn't already arrived
            if not self._stt_final_received.is_set():
                try:
                    await asyncio.wait_for(self._stt_final_received.wait(), timeout=0.8)
                except (TimeoutError, asyncio.TimeoutError):
                    print("[Orchestrator] Timeout waiting for Deepgram is_final. Proceeding with buffered transcript.")
            
            # Additional tiny grace period (50ms) to ensure any trailing network packets or multi-channel text are merged
            await asyncio.sleep(0.05)
            
            # Ensure user did not resume speaking and STT connection is active during the wait
            if self.vad_client.is_speaking or not self._is_running or self.session.state != "listening" or not self.dg_client._is_connected:
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
        chunker_task: Optional[asyncio.Task] = None
        try:
            # Flush any stale items or sentinels in TTS queue from a previously interrupted turn
            while not self.session.tts_queue.empty():
                try:
                    self.session.tts_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                    
            token_stream = self.gemini_client.generate_turn_stream(user_text, session=self.session)
            
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
        if not text.strip():
            return
        try:
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
        for client_name, client in [("Deepgram STT", self.dg_client), ("Gemini LLM", self.gemini_client), (f"{getattr(self, 'tts_provider_name', 'TTS')} Client", self.tts_client)]:
            if client and hasattr(client, "finish"):
                try:
                    await client.finish()
                except Exception as e:
                    print(f"[Orchestrator Error] Failed to cleanly finish {client_name}: {e}")
                    
        print(f"[Orchestrator] Call Session complete. Total turns: {len(self.session.conversation_history)}")