"""
Framework-agnostic voice pipeline orchestrator.
Coordinates Twilio Media Streams and Gemini Live real-time bidirectional audio streaming and tool calling.
"""

import os
import asyncio
import json
import base64
import inspect
import audioop
from typing import Optional

from agent.streaming.gemini_live_stream import GeminiLiveStreamClient
from agent.session.call_session import CallSession


class VoicePipelineOrchestrator:
    """
    Orchestrates real-time bi-directional conversational voice turns for a single phone call using Gemini Live API.
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

        # Initialize session and Gemini Live client
        self.session = CallSession(call_id=call_id, opening_intent=opening_intent, lead_id=lead_id)
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
        self.tts_provider_name = "Gemini Live"
        self.mulaw_frame_size = 160
        self.output_buffer = bytearray()
        
        self._is_running: bool = False
        self._stopped: bool = False

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
        print(f"[Orchestrator] Starting voice pipeline for CallSid: {self.call_id}, StreamSid: {self.stream_sid}")
        
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

    async def handle_media_payload(self, ulaw_base64: str) -> None:
        """
        Processes an inbound chunk of 8kHz ulaw audio from Twilio Media Streams and sends to Gemini Live.
        """
        if not self._is_running:
            return

        audio_bytes = base64.b64decode(ulaw_base64)
        
        if self.gemini_live_client and not getattr(self.gemini_live_client, "_closed", False):
            try:
                pcm8k = audioop.ulaw2lin(audio_bytes, 2)
                pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
                await self.gemini_live_client.send_audio(pcm16k)
            except Exception as e:
                print(f"[Orchestrator Error] Failed to process and send live audio: {e}")

    async def stop(self) -> None:
        """Tears down client connections deterministically."""
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self._is_running = False
        print(f"[Orchestrator] Stopping voice pipeline for CallSid: {self.call_id}")
        
        if getattr(self, "gemini_live_client", None):
            try:
                await self.gemini_live_client.finish()
            except Exception as e:
                print(f"[Orchestrator Error] Failed to cleanly finish Gemini Live Client: {e}")
                
        print(f"[Orchestrator] Call Session complete. Total turns: {len(self.session.conversation_history)}")