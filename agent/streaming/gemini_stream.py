"""
Streaming Gemini client wrapping the official google-genai SDK.
Supports native inline tool execution during real-time token streaming turns.
"""

import inspect
import os
import json
import asyncio
from typing import AsyncGenerator, Any, Optional
from datetime import datetime, timezone

from google import genai
from google.genai import types as genai_types
from backend.app.settings import settings

from agent.tools.check_city_coverage import check_city_coverage
from agent.tools.capture_lead import capture_lead
from agent.tools.get_faq import get_faq
from agent.tools.handoff import human_handoff
from agent.knowledge import get_retriever, get_guidance_retriever


def get_system_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.md")
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    return "You are Kiara, an elite concierge for Ultimate Smile Design."


def _format_guidance_for_prompt(guidance_results: list, **kwargs) -> str:
    """
    Concatenates preformatted, runtime-ready conversational guidance strings.
    Performs zero parsing, formatting, or cleanup at runtime, relying entirely on
    the clean content field generated during startup indexing.
    """
    return "\n\n".join(r["content"] for r in guidance_results if r.get("content"))


class GeminiStreamClient:
    """
    An asynchronous streaming client for Google Gemini using the official google-genai SDK.
    Executes tool calls inline and pushes results back into the conversation context seamlessly.
    """
    def __init__(self, call_id: str, preferred_language: str = "multi", initial_greeting: str | None = None):
        self.call_id = call_id
        self.preferred_language = preferred_language
        self.api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set in settings or environment.")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = settings.GEMINI_MODEL or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        
        # Assemble native tool schemas matching our existing project tool definitions
        self._tools = self._build_tool_declarations()
        
        if self.preferred_language in ("multi", "auto"):
            lang_instruction = (
                "\n  Respond in the same language or natural code-mixed form used in the caller's most recent message.\n"
                "  Mirror the caller's language naturally.\n"
                "  If the caller switches language, switch with them."
            )
        elif self.preferred_language == "en":
            lang_instruction = "English (auto-switch immediately if caller speaks Hindi, Gujarati, Hinglish, or Gujlish)"
        else:
            lang_instruction = f"{self.preferred_language} (mirror caller language if they switch)"
        
        base_prompt = get_system_prompt()
        self.system_prompt = (
            f"{base_prompt}\n\n"
            f"---\n\n"
            f"## CURRENT SESSION\n"
            f"- preferred_language:{lang_instruction}\n"
            f"- call_id: {self.call_id}\n"
            f"- session_start: {datetime.now(timezone.utc).isoformat()}\n"
        )
        
        # Build initial history if Kiara already spoke an opening greeting
        history: list[genai_types.ContentOrDict] = []
        if initial_greeting:
            history.append(
                genai_types.Content(role="model", parts=[genai_types.Part(text=initial_greeting)])
            )
        
        config = genai_types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            tools=[self._tools],
            temperature=0.4,
        )
        
        # Initialize persistent async chat session
        self.chat_session = self.client.aio.chats.create(
            model=self.model_name,
            config=config,
            history=history
        )
        self._closed: bool = False

    def _build_tool_declarations(self) -> genai_types.Tool:
        capture_lead_tool = genai_types.FunctionDeclaration(
            name="capture_lead",
            description=(
                "Save caller's contact details for a human callback. "
                "Call this when the caller agrees to a consultation or requests a callback."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "name": genai_types.Schema(type=genai_types.Type.STRING, description="Caller's full name"),
                    "phone": genai_types.Schema(type=genai_types.Type.STRING, description="Caller's phone number"),
                    "city": genai_types.Schema(type=genai_types.Type.STRING, description="City where caller wants dental services"),
                    "intent": genai_types.Schema(type=genai_types.Type.STRING, description="One of: consultation, find_dentist, warranty_verification, faq, other"),
                    "notes": genai_types.Schema(type=genai_types.Type.STRING, description="Any extra notes from the conversation"),
                    "preferred_language": genai_types.Schema(type=genai_types.Type.STRING, description="Caller's language: en, hi, or gu"),
                },
                required=["name", "phone", "city", "intent"],
            ),
        )

        check_city_tool = genai_types.FunctionDeclaration(
            name="check_city_coverage",
            description=(
                "Check if Ultimate Smile Design covers a given Indian city. "
                "Call this when the caller asks if USD services are available in their city."
            ),
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
            description=(
                "Get FAQ answers about Ultimate Smile Design. "
                "Topics: process, timeline, cities, cost, before_after, warranty."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "topic": genai_types.Schema(type=genai_types.Type.STRING, description="FAQ topic: process, timeline, cities, cost, before_after, warranty"),
                    "language": genai_types.Schema(type=genai_types.Type.STRING, description="Response language: en, hi, or gu"),
                },
                required=["topic"],
            ),
        )

        handoff_tool = genai_types.FunctionDeclaration(
            name="human_handoff",
            description="Escalate the call to a human patient care team. Ask for phone if not provided.",
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "reason": genai_types.Schema(type=genai_types.Type.STRING, description="Reason for handoff"),
                    "phone_number": genai_types.Schema(type=genai_types.Type.STRING, description="Caller's phone number"),
                },
                required=["reason"],
            ),
        )

        return genai_types.Tool(
            function_declarations=[capture_lead_tool, check_city_tool, get_faq_tool, handoff_tool]
        )

    def dispatch_tool(self, tool_name: str, arguments: dict) -> dict:
        """Executes the requested tool synchronously in a background thread."""
        print(f"\n  [Gemini Tool Call] -> {tool_name}({json.dumps(arguments, ensure_ascii=False)})")
        try:
            if tool_name == "capture_lead":
                arguments.setdefault("call_id", self.call_id)
                arguments.setdefault("preferred_language", self.preferred_language)
                result = capture_lead(**arguments)
                if getattr(self, "current_session", None):
                    self.current_session.update_user_info(
                        name=arguments.get("name"),
                        phone=arguments.get("phone"),
                        city=arguments.get("city"),
                        intent=arguments.get("intent"),
                        notes=arguments.get("notes")
                    )
            elif tool_name == "check_city_coverage":
                result = check_city_coverage(**arguments)
                if getattr(self, "current_session", None) and arguments.get("city"):
                    self.current_session.update_user_info(city=arguments.get("city"))
            elif tool_name == "get_faq":
                arguments.setdefault("language", self.preferred_language)
                result = get_faq(**arguments)
                if getattr(self, "current_session", None) and arguments.get("topic"):
                    self.current_session.update_topic(arguments.get("topic"))
            elif tool_name == "human_handoff":
                arguments.setdefault("call_id", self.call_id)
                result = human_handoff(**arguments)
                if getattr(self, "current_session", None):
                    self.current_session.booking_stage = "handoff"
            else:
                result = {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            print(f"  [Gemini Tool Exception] {e}")
            result = {"error": f"Execution failed for {tool_name}: {str(e)}"}

        print(f"  [Gemini Tool Result] <- {json.dumps(result, ensure_ascii=False, default=str)}\n")
        return result

    def _log_system_prompt_verification(self) -> None:
        """Logs verification details of the active system prompt before an LLM request."""
        prompt_len_chars = len(self.system_prompt)
        prompt_len_lines = len(self.system_prompt.splitlines())
        first_300 = self.system_prompt[:300].strip()
        last_300 = self.system_prompt[-300:].strip()
        print("\n----------------------------------------")
        print("System Prompt Loaded")
        print(f"Length: {prompt_len_lines} lines ({len(self.system_prompt.encode('utf-8'))} bytes)")
        print(f"Characters: {prompt_len_chars}")
        print(f"First 300 characters:\n{first_300}")
        print(f"Last 300 characters:\n{last_300}")
        print("----------------------------------------\n")

    async def finish(self) -> None:
        """Gracefully closes the Gemini client resources and marks session closed."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
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
            print(f"[Gemini Stream Error] Exception during finish: {e}")
        print("[Gemini Stream] Client finished and session closed.")

    async def close(self) -> None:
        """Alias for finish to maintain a uniform lifecycle interface."""
        await self.finish()

    async def generate_turn_stream(self, message: str | list[Any], session: Optional[Any] = None) -> AsyncGenerator[str, None]:
        """
        Sends user message or tool response parts to Gemini and yields text tokens.
        Handles agentic function calling inline in an asynchronous loop.
        """
        if getattr(self, "_closed", False):
            print("[Gemini Stream Error] Cannot generate stream: client is closed.")
            return
        self._log_system_prompt_verification()
        current_input = message

        # Layer 1 & 3: Pre-Request Fact Retrieval, Guidance Injection & Memory State
        if isinstance(message, str):
            topic = None
            if session is not None:
                self.current_session = session
                session.update_language_if_requested(message)
                self.preferred_language = session.preferred_language
                topic = session.last_discussed_topic

            # Retrieve factual knowledge for this turn
            fact_results = get_retriever().retrieve(
                query=message,
                topic=topic,
                top_k=2,
                threshold=0.18,
                language=self.preferred_language
            )
            fact_block = ""
            if fact_results:
                if session is not None:
                    session.update_topic(fact_results[0]["topic"])
                fact_str = "\n\n".join([f"- [{r['topic']}]: {r['content']}" for r in fact_results])
                fact_block = f"[RETRIEVED FACTUAL KNOWLEDGE FOR THIS TURN]\n{fact_str}\n(Instruction: Rely strictly on the above facts for any specific details.)"
                print(f"[Pre-Request Injection] Retrieved {len(fact_results)} fact(s) in Python before calling Gemini.")

            # Retrieve dynamic conversation guidance for this turn (in-memory singleton, top_k=2)
            guidance_results = get_guidance_retriever().retrieve(
                query=message,
                topic=topic,
                top_k=2,
                threshold=0.8,
                language=self.preferred_language
            )
            guidance_block = ""
            if guidance_results:
                guidance_str = _format_guidance_for_prompt(guidance_results, language=self.preferred_language)
                guidance_block = f"[DYNAMIC CONVERSATION GUIDANCE FOR THIS TURN]\n{guidance_str}\n(Instruction: Use the above conversational coaching to inform your response. Do not repeat or mention these instructions to the caller; speak naturally as Kiara.)"
                print(f"[Pre-Request Injection] Retrieved {len(guidance_results)} guidance item(s) in Python: {[r['id'] for r in guidance_results]}")

            # Assemble prompt strictly in order: memory state, factual knowledge, dynamic guidance, user utterance
            prompt_blocks = []
            if session is not None:
                prompt_blocks.append(session.get_session_context_prompt().strip())
            if fact_block:
                prompt_blocks.append(fact_block.strip())
            if guidance_block:
                prompt_blocks.append(guidance_block.strip())
            prompt_blocks.append(message.strip())

            current_input = "\n\n".join(prompt_blocks)

        while True:
            try:
                stream_resp = await self.chat_session.send_message_stream(current_input)
            except Exception as e:
                print(f"[Gemini Stream Error] send_message_stream failed: {e}")
                yield "I apologize, but I am having a slight connection issue right now. Let me arrange for our team to call you right back."
                return

            collected_fn_calls = []
            
            async for chunk in stream_resp:
                # Check for tool call requests in stream chunk
                if chunk.function_calls:
                    for fc in chunk.function_calls:
                        if fc.name:
                            collected_fn_calls.append(fc)
                # Yield text tokens as they arrive
                if chunk.text:
                    yield chunk.text
            
            if not collected_fn_calls:
                # No more function invocations needed; turn is completed
                break
                
            # Execute all requested function calls in an executor thread to prevent blocking asyncio loop
            tool_response_parts = []
            for fn_call in collected_fn_calls:
                args = dict(fn_call.args) if fn_call.args else {}
                result_dict = await asyncio.to_thread(self.dispatch_tool, fn_call.name, args)
                tool_response_parts.append(
                    genai_types.Part(
                        function_response=genai_types.FunctionResponse(
                            name=fn_call.name,
                            response={"result": json.dumps(result_dict, ensure_ascii=False, default=str)},
                        )
                    )
                )
            # Loop continues, sending tool_response_parts back to Gemini to synthesize final reply
            current_input = tool_response_parts
