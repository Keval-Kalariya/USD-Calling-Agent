"""
Production-ready asynchronous client for Google Gemini Multimodal Live API using google-genai SDK.
Supports real-time bidirectional audio streaming, interruption handling, and inline tool execution.
Independent component designed for voice pipeline integration without video or demo frontend code.
"""

import os
import json
import asyncio
import inspect
import traceback
from typing import AsyncGenerator, Any, Optional, Callable, Dict, List
from datetime import datetime, timezone

from google import genai
from google.genai import types as genai_types
from backend.app.settings import settings

from agent.tools.check_city_coverage import check_city_coverage
from agent.tools.capture_lead import capture_lead
from agent.tools.get_faq import get_faq
from agent.tools.handoff import human_handoff


def get_system_prompt() -> str:
    """Loads the system prompt from project prompts directory with fallback."""
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.md")
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    return "You are Kiara, an elite concierge for Ultimate Smile Design."


class GeminiLiveStreamClient:
    """
    An asynchronous streaming client for Google Gemini Multimodal Live API using the official google-genai SDK.
    Handles real-time audio PCM streams, server-side activity endpointing, interruption events, and native tool execution.
    """
    def __init__(
        self,
        call_id: Optional[str] = None,
        preferred_language: str = "multi",
        initial_greeting: Optional[str] = None,
        input_sample_rate: int = 16000,
        model_name: Optional[str] = None,
        voice_name: Optional[str] = None,
        tools: Optional[list] = None,
        tool_mapping: Optional[Dict[str, Callable]] = None,
        system_instruction: Optional[str] = None,
    ):
        self.call_id = call_id or "live-session"
        self.preferred_language = preferred_language
        self.input_sample_rate = input_sample_rate
        
        # Load credentials and configuration from settings with fallback to environment
        self.api_key = getattr(settings, "GEMINI_API_KEY", None) or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set in settings or environment.")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = (
            model_name 
            or getattr(settings, "GEMINI_LIVE_MODEL", None) 
            or os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
        )
        self.voice_name = (
            voice_name 
            or getattr(settings, "GEMINI_LIVE_VOICE", None) 
            or os.environ.get("GEMINI_LIVE_VOICE", "Puck")
        )

        # Build system instruction incorporating conversational context
        if system_instruction is not None:
            self.system_instruction = system_instruction
        else:
            base_prompt = get_system_prompt()
            lang_instruction = (
                "Mirror caller language naturally (English, Hindi, Gujarati, Hinglish, or Gujlish). "
                "Switch automatically when the caller switches."
                if self.preferred_language in ("multi", "auto")
                else f"{self.preferred_language} (mirror caller language if they switch)"
            )
            self.system_instruction = (
                f"{base_prompt}\n\n"
                f"---\n\n"
                f"## CURRENT SESSION (LIVE VOICE CALL)\n"
                f"- preferred_language: {lang_instruction}\n"
                f"- call_id: {self.call_id}\n"
                f"- session_start: {datetime.now(timezone.utc).isoformat()}\n"
                f"- call_mode: REAL-TIME TELEPHONY AUDIO STREAM (Keep voice replies strictly to 1-2 conversational sentences with warmth and brevity. No lists or monologues).\n"
            )

        if initial_greeting:
            self.system_instruction += f"\nNote: You have just initiated the conversation by greeting the caller: '{initial_greeting}'"

        # Initialize native tool schemas and execution dispatch mapping
        if tools is not None:
            self.tools = tools
        else:
            self.tools = [self._build_tool_declarations()]
            
        if tool_mapping is not None:
            self.tool_mapping = tool_mapping
        else:
            self.tool_mapping = self._build_default_tool_mapping()

        # Input queues and state flags
        self._audio_input_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._text_input_queue: asyncio.Queue[str] = asyncio.Queue()
        self._session_task: Optional[asyncio.Task] = None
        self._closed: bool = False
        self._is_connected: bool = False

    def _build_tool_declarations(self) -> genai_types.Tool:
        """Assembles native tool schemas matching project enterprise tools."""
        capture_lead_tool = genai_types.FunctionDeclaration(
            name="capture_lead",
            description="Save caller contact details for a human callback or consultation booking.",
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "name": genai_types.Schema(type=genai_types.Type.STRING, description="Caller's full name"),
                    "phone": genai_types.Schema(type=genai_types.Type.STRING, description="Caller's phone number"),
                    "city": genai_types.Schema(type=genai_types.Type.STRING, description="City where caller wants dental services"),
                    "intent": genai_types.Schema(type=genai_types.Type.STRING, description="Intent: consultation, find_dentist, warranty_verification, faq, other"),
                    "notes": genai_types.Schema(type=genai_types.Type.STRING, description="Any extra conversation notes"),
                    "preferred_language": genai_types.Schema(type=genai_types.Type.STRING, description="Caller language: en, hi, gu"),
                },
                required=["name", "phone", "city", "intent"],
            ),
        )

        check_city_tool = genai_types.FunctionDeclaration(
            name="check_city_coverage",
            description="Check if Ultimate Smile Design services are available in a specific Indian city.",
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "city": genai_types.Schema(type=genai_types.Type.STRING, description="City name to check coverage for"),
                },
                required=["city"],
            ),
        )

        get_faq_tool = genai_types.FunctionDeclaration(
            name="get_faq",
            description="Retrieve authoritative FAQ answers about Ultimate Smile Design process, timeline, cities, cost, before_after, or warranty.",
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "topic": genai_types.Schema(type=genai_types.Type.STRING, description="FAQ topic: process, timeline, cities, cost, before_after, warranty"),
                    "language": genai_types.Schema(type=genai_types.Type.STRING, description="Response language: en, hi, gu"),
                },
                required=["topic"],
            ),
        )

        handoff_tool = genai_types.FunctionDeclaration(
            name="human_handoff",
            description="Escalate the call to a human patient care specialist when requested or necessary.",
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "reason": genai_types.Schema(type=genai_types.Type.STRING, description="Reason for escalation"),
                    "phone_number": genai_types.Schema(type=genai_types.Type.STRING, description="Caller phone number"),
                },
                required=["reason"],
            ),
        )

        return genai_types.Tool(
            function_declarations=[capture_lead_tool, check_city_tool, get_faq_tool, handoff_tool]
        )

    def _build_default_tool_mapping(self) -> Dict[str, Callable]:
        """Maps schema names to callable execution wrappers supplying session parameters."""
        def wrap_capture_lead(**kwargs):
            kwargs.setdefault("call_id", self.call_id)
            kwargs.setdefault("preferred_language", self.preferred_language)
            return capture_lead(**kwargs)

        def wrap_get_faq(**kwargs):
            kwargs.setdefault("language", self.preferred_language)
            return get_faq(**kwargs)

        def wrap_handoff(**kwargs):
            kwargs.setdefault("call_id", self.call_id)
            return human_handoff(**kwargs)

        return {
            "capture_lead": wrap_capture_lead,
            "check_city_coverage": check_city_coverage,
            "get_faq": wrap_get_faq,
            "human_handoff": wrap_handoff,
        }

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Enqueues linear 16-bit PCM (16kHz) audio bytes for transmission to Gemini Live."""
        if self._closed:
            return
        await self._audio_input_queue.put(audio_chunk)

    async def send_text(self, text: str) -> None:
        """Enqueues dynamic text instructions, RAG facts, or conversational updates into the live stream."""
        if self._closed or not text.strip():
            return
        await self._text_input_queue.put(text)

    async def start_session(
        self,
        audio_output_callback: Optional[Callable[[bytes], Any]] = None,
        audio_interrupt_callback: Optional[Callable[[], Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Opens the Gemini Live bidirectional session context and runs sender/receiver loops.
        Yields normalized event dictionaries for transcription, turns, tool calls, and errors.
        """
        config = genai_types.LiveConnectConfig(
            response_modalities=[genai_types.Modality.AUDIO],
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
            system_instruction=genai_types.Content(
                parts=[genai_types.Part(text=self.system_instruction)]
            ),
            input_audio_transcription=genai_types.AudioTranscriptionConfig(),
            output_audio_transcription=genai_types.AudioTranscriptionConfig(),
            realtime_input_config=genai_types.RealtimeInputConfig(
                turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",
            ),
            tools=self.tools if self.tools else None,
        )

        print(f"[Gemini Live Stream] Connecting to Live API with model={self.model_name}, voice={self.voice_name}")
        self._is_connected = True

        try:
            async with self.client.aio.live.connect(model=self.model_name, config=config) as session:
                print("[Gemini Live Stream] Session established successfully.")

                async def send_audio_loop():
                    try:
                        while True:
                            chunk = await self._audio_input_queue.get()
                            await session.send_realtime_input(
                                audio=genai_types.Blob(
                                    data=chunk,
                                    mime_type=f"audio/pcm;rate={self.input_sample_rate}"
                                )
                            )
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        print(f"[Gemini Live Stream Error] send_audio exception: {e}")

                async def send_text_loop():
                    try:
                        while True:
                            text = await self._text_input_queue.get()
                            print(f"[Gemini Live Stream] Sending text input to model: {text[:80]}...")
                            await session.send_realtime_input(text=text)
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        print(f"[Gemini Live Stream Error] send_text exception: {e}")

                event_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

                async def receive_loop():
                    try:
                        async for response in session.receive():
                            if getattr(response, "go_away", None):
                                print(f"[Gemini Live Stream Warning] Received GoAway notice: {response.go_away}")
                            
                            server_content = getattr(response, "server_content", None)
                            tool_call = getattr(response, "tool_call", None)

                            if server_content:
                                if getattr(server_content, "model_turn", None):
                                    for part in server_content.model_turn.parts:
                                        if getattr(part, "inline_data", None) and part.inline_data.data:
                                            if audio_output_callback:
                                                if inspect.iscoroutinefunction(audio_output_callback):
                                                    await audio_output_callback(part.inline_data.data)
                                                else:
                                                    audio_output_callback(part.inline_data.data)

                                if getattr(server_content, "input_transcription", None) and server_content.input_transcription.text:
                                    await event_queue.put({
                                        "type": "user",
                                        "text": server_content.input_transcription.text
                                    })

                                if getattr(server_content, "output_transcription", None) and server_content.output_transcription.text:
                                    await event_queue.put({
                                        "type": "gemini",
                                        "text": server_content.output_transcription.text
                                    })

                                if getattr(server_content, "turn_complete", False):
                                    await event_queue.put({"type": "turn_complete"})

                                if getattr(server_content, "interrupted", False):
                                    print("[Gemini Live Stream] Interruption detected by model.")
                                    if audio_interrupt_callback:
                                        if inspect.iscoroutinefunction(audio_interrupt_callback):
                                            await audio_interrupt_callback()
                                        else:
                                            audio_interrupt_callback()
                                    await event_queue.put({"type": "interrupted"})

                            if tool_call:
                                function_responses = []
                                for fc in getattr(tool_call, "function_calls", []):
                                    func_name = fc.name
                                    args = dict(fc.args) if fc.args else {}
                                    print(f"\n  [Gemini Live Tool Call] -> {func_name}({json.dumps(args, ensure_ascii=False)})")
                                    
                                    result_data = None
                                    if func_name in self.tool_mapping:
                                        try:
                                            tool_func = self.tool_mapping[func_name]
                                            if inspect.iscoroutinefunction(tool_func):
                                                result_data = await tool_func(**args)
                                            else:
                                                result_data = await asyncio.to_thread(tool_func, **args)
                                        except Exception as e:
                                            print(f"  [Gemini Live Tool Exception] {e}")
                                            result_data = {"error": f"Execution failed for {func_name}: {str(e)}"}
                                    else:
                                        result_data = {"error": f"Unknown tool: {func_name}"}

                                    print(f"  [Gemini Live Tool Result] <- {json.dumps(result_data, ensure_ascii=False, default=str)}\n")
                                    
                                    function_responses.append(
                                        genai_types.FunctionResponse(
                                            name=func_name,
                                            id=getattr(fc, "id", None),
                                            response={"result": json.dumps(result_data, ensure_ascii=False, default=str)}
                                        )
                                    )
                                await session.send_tool_response(function_responses=function_responses)
                                await event_queue.put({"type": "tool_call", "function_calls": [fc.name for fc in tool_call.function_calls]})

                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        print(f"[Gemini Live Stream Error] receive_loop error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                        await event_queue.put({"type": "error", "error": str(e)})
                    finally:
                        await event_queue.put(None)

                # Launch concurrent IO tasks
                audio_task = asyncio.create_task(send_audio_loop())
                text_task = asyncio.create_task(send_text_loop())
                recv_task = asyncio.create_task(receive_loop())

                try:
                    while True:
                        event = await event_queue.get()
                        if event is None:
                            break
                        yield event
                        if event.get("type") == "error":
                            break
                finally:
                    print("[Gemini Live Stream] Cleaning up session IO tasks.")
                    audio_task.cancel()
                    text_task.cancel()
                    recv_task.cancel()
                    await asyncio.gather(audio_task, text_task, recv_task, return_exceptions=True)

        except Exception as e:
            print(f"[Gemini Live Stream Error] Connection failure: {type(e).__name__}: {e}")
            raise
        finally:
            self._is_connected = False
            print("[Gemini Live Stream] Session closed.")

    async def connect(
        self,
        audio_output_callback: Optional[Callable[[bytes], Any]] = None,
        audio_interrupt_callback: Optional[Callable[[], Any]] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        """
        Non-blocking lifecycle connection entrypoint.
        Starts session execution in a background task and dispatches event notifications to optional callback.
        """
        if self._session_task and not self._session_task.done():
            return

        async def _runner():
            try:
                async for event in self.start_session(
                    audio_output_callback=audio_output_callback,
                    audio_interrupt_callback=audio_interrupt_callback,
                ):
                    if event and event_callback:
                        if inspect.iscoroutinefunction(event_callback):
                            await event_callback(event)
                        else:
                            event_callback(event)
            except asyncio.CancelledError:
                print("[Gemini Live Stream] Background connect runner cancelled.")
            except Exception as e:
                print(f"[Gemini Live Stream Error] Background runner error: {e}")

        self._session_task = asyncio.create_task(_runner())

    async def finish(self) -> None:
        """Gracefully shuts down background tasks and closes GenAI SDK client resources."""
        if self._closed:
            return
        self._closed = True
        print("[Gemini Live Stream] Finishing client operations...")
        if self._session_task and not self._session_task.done():
            self._session_task.cancel()
            try:
                await self._session_task
            except (asyncio.CancelledError, Exception):
                pass
            self._session_task = None

        try:
            if hasattr(self.client, "aio") and hasattr(self.client.aio, "close") and callable(self.client.aio.close):
                res = self.client.aio.close()
                if inspect.isawaitable(res):
                    await res
            elif hasattr(self.client, "close") and callable(self.client.close):
                res = self.client.close()
                if inspect.isawaitable(res):
                    await res
        except Exception as e:
            print(f"[Gemini Live Stream Error] Exception during GenAI client closure: {e}")
        print("[Gemini Live Stream] Client finished and resources cleanly released.")

    async def close(self) -> None:
        """Alias for finish to maintain uniform lifecycle interface."""
        await self.finish()
