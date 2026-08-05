"""
Phase 3 — CLI Chat Harness for the USD Calling Agent.

Tests all 5 intents in English, Hindi, and Gujarati using Google Gemini
natively via the official google-genai SDK, with live tool execution.

Usage (from project root):
    python agent/cli_harness.py

Requirements:
    GEMINI_API_KEY must be set in the .env file in the project root.
"""

import os
import sys
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path setup — allow importing from backend/app and agent/tools
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)

from app.settings import settings

# ---------------------------------------------------------------------------
# Tool imports
# ---------------------------------------------------------------------------
from agent.tools.capture_lead import capture_lead
from agent.tools.check_city_coverage import check_city_coverage
from agent.tools.get_faq import get_faq
from agent.knowledge import get_retriever, get_guidance_retriever
from agent.session.call_session import CallSession
from agent.knowledge.guidance import _format_guidance_for_prompt

# ---------------------------------------------------------------------------
# google-genai SDK (new official package: pip install google-genai)
# ---------------------------------------------------------------------------
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import types as genai_types

# ---------------------------------------------------------------------------
# System prompt loader
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_PATH = os.path.join(ROOT, "agent", "prompts", "system_prompt.md")

def load_system_prompt(language: str, call_id: str) -> str:
    with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        base_prompt = f.read()
    return (
        f"{base_prompt}\n\n"
        f"---\n\n"
        f"## CURRENT SESSION\n"
        f"- preferred_language: {language}\n"
        f"- call_id: {call_id}\n"
        f"- session_start: {datetime.now(timezone.utc).isoformat()}\n"
    )

# ---------------------------------------------------------------------------
# Tool dispatcher — executes a tool by name and returns JSON result string
# ---------------------------------------------------------------------------
def dispatch_tool(tool_name: str, arguments: dict, call_id: str, session: Any = None) -> str:
    print(f"\n  [TOOL CALL] -> {tool_name}({json.dumps(arguments, ensure_ascii=False)})")

    if tool_name == "capture_lead":
        arguments.setdefault("call_id", call_id)
        result = capture_lead(**arguments)
        if session:
            session.update_user_info(
                name=arguments.get("name"),
                phone=arguments.get("phone"),
                city=arguments.get("city"),
                intent=arguments.get("intent"),
                notes=arguments.get("notes")
            )
    elif tool_name == "check_city_coverage":
        result = check_city_coverage(**arguments)
        if session and arguments.get("city"):
            session.update_user_info(city=arguments.get("city"))
    elif tool_name == "get_faq":
        result = get_faq(**arguments)
        if session and arguments.get("topic"):
            session.update_topic(arguments.get("topic"))
    else:
        result = {"error": f"Unknown tool: {tool_name}"}

    print(f"  [TOOL RESULT] <- {json.dumps(result, ensure_ascii=False, default=str)}\n")
    return json.dumps(result, ensure_ascii=False, default=str)

# ---------------------------------------------------------------------------
# Native google-genai Tool declarations
# ---------------------------------------------------------------------------
CAPTURE_LEAD_TOOL = genai_types.FunctionDeclaration(
    name="capture_lead",
    description=(
        "Save caller's contact details for a human callback. "
        "Call this when the caller agrees to a consultation or requests a callback."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "name":               genai_types.Schema(type=genai_types.Type.STRING, description="Caller's full name"),
            "phone":              genai_types.Schema(type=genai_types.Type.STRING, description="Caller's phone number"),
            "city":               genai_types.Schema(type=genai_types.Type.STRING, description="City where caller wants dental services"),
            "intent":             genai_types.Schema(type=genai_types.Type.STRING, description="One of: consultation, find_dentist, warranty_verification, faq, other"),
            "notes":              genai_types.Schema(type=genai_types.Type.STRING, description="Any extra notes from the conversation"),
            "preferred_language": genai_types.Schema(type=genai_types.Type.STRING, description="Caller's language: en, hi, or gu"),
            "call_id":            genai_types.Schema(type=genai_types.Type.STRING, description="Current call/session ID"),
        },
        required=["name", "phone", "city", "intent", "preferred_language"],
    ),
)

CHECK_CITY_COVERAGE_TOOL = genai_types.FunctionDeclaration(
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

GET_FAQ_TOOL = genai_types.FunctionDeclaration(
    name="get_faq",
    description=(
        "Get FAQ answers about Ultimate Smile Design. "
        "Topics: process, timeline, cities, cost, before_after, warranty."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "topic":    genai_types.Schema(type=genai_types.Type.STRING, description="FAQ topic: process, timeline, cities, cost, before_after, warranty"),
            "language": genai_types.Schema(type=genai_types.Type.STRING, description="Response language: en, hi, or gu"),
        },
        required=["topic"],
    ),
)

USD_TOOLS = genai_types.Tool(
    function_declarations=[CAPTURE_LEAD_TOOL, CHECK_CITY_COVERAGE_TOOL, GET_FAQ_TOOL]
)

TOOL_NAMES = ["capture_lead", "check_city_coverage", "get_faq"]

# ---------------------------------------------------------------------------
# Gemini client builder
# ---------------------------------------------------------------------------
def _get_client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        print(
            "\n[ERROR] GEMINI_API_KEY is not set. "
            "Add it to your .env file and restart."
        )
        sys.exit(1)
    return genai.Client(api_key=settings.GEMINI_API_KEY)

# ---------------------------------------------------------------------------
# Chat function — Gemini native agentic loop with tool calling
# ---------------------------------------------------------------------------
def chat(messages: list, system_prompt: str, call_id: str, session: Any = None) -> str:
    """
    Send a conversation to Gemini and handle the full agentic tool-calling loop.

    `messages` is a list of dicts: {"role": "user"|"assistant", "content": str}
    Returns the final text response from the model.
    """
    client = _get_client()
    model_name = settings.GEMINI_MODEL or "gemini-2.5-flash"

    # Convert internal message format → google-genai Content objects
    history: list[genai_types.ContentOrDict] = []
    for m in messages[:-1]:  # All but the last message form the history
        role = "model" if m["role"] == "assistant" else "user"
        history.append(
            genai_types.Content(role=role, parts=[genai_types.Part(text=m["content"])])
        )

    # The last message is the current user turn
    last_message = messages[-1]["content"] if messages else "[START_CALL]"
    current_input = last_message

    if last_message != "[START_CALL]":
        if session:
            session.update_language_if_requested(last_message)
            lang = session.preferred_language
            topic = session.last_discussed_topic
        else:
            lang = "en"
            topic = None

        fact_results = get_retriever().retrieve(query=last_message, topic=topic, top_k=2, threshold=0.18, language=lang)
        fact_block = ""
        if fact_results:
            if session:
                session.update_topic(fact_results[0]["topic"])
            fact_str = "\n\n".join([f"- [{r['topic']}]: {r['content']}" for r in fact_results])
            fact_block = f"[RETRIEVED FACTUAL KNOWLEDGE FOR THIS TURN]\n{fact_str}\n(Instruction: Rely strictly on the above facts for any specific details.)"
            print(f"[Pre-Request Injection] Retrieved {len(fact_results)} fact(s) in Python.")

        guidance_results = get_guidance_retriever().retrieve(query=last_message, topic=topic, top_k=2, threshold=0.8, language=lang)
        guidance_block = ""
        if guidance_results:
            guidance_str = _format_guidance_for_prompt(guidance_results, language=lang)
            guidance_block = f"[DYNAMIC CONVERSATION GUIDANCE FOR THIS TURN]\n{guidance_str}\n(Instruction: Use the above conversational coaching to inform your response. Do not repeat or mention these instructions to the caller; speak naturally as Kiara.)"
            print(f"[Pre-Request Injection] Retrieved {len(guidance_results)} guidance item(s) in Python: {[r['id'] for r in guidance_results]}")

        prompt_blocks = []
        if session:
            prompt_blocks.append(session.get_session_context_prompt().strip())
        if fact_block:
            prompt_blocks.append(fact_block.strip())
        if guidance_block:
            prompt_blocks.append(guidance_block.strip())
        prompt_blocks.append(last_message.strip())
        current_input = "\n\n".join(prompt_blocks)
    elif session:
        current_input = f"{session.get_session_context_prompt().strip()}\n\n{last_message}"

    chat_session = client.chats.create(
        model=model_name,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[USD_TOOLS],
            temperature=0.4,
        ),
        history=history,
    )

    response = chat_session.send_message(current_input)

    # Agentic loop — keep processing tool calls until we get a text reply
    while True:
        candidate = response.candidates[0] if (response and response.candidates) else None
        content = candidate.content if candidate else None
        parts = content.parts if (content and content.parts) else []

        # Collect all function calls in this response
        fn_calls = [
            part.function_call
            for part in parts
            if part.function_call is not None
        ]

        if not fn_calls:
            # No tool calls — extract and return the text
            text_parts = [
                part.text
                for part in parts
                if getattr(part, "text", None)
            ]
            return " ".join(text_parts).strip()

        # Execute all requested tool calls and build response parts
        tool_response_parts = []
        for fn_call in fn_calls:
            tool_name= fn_call.name

            if tool_name is None:
                print("[Tool Error] Function call missing name. skipping.")
                continue

            args = dict(fn_call.args) if fn_call.args else {}
            result_str = dispatch_tool(tool_name, args, call_id, session=session)
            tool_response_parts.append(
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=tool_name,
                        response={"result": result_str},
                    )
                )
            )

        # Send tool results back to continue the loop
        response = chat_session.send_message(tool_response_parts)

# ---------------------------------------------------------------------------
# Language selection menu
# ---------------------------------------------------------------------------
LANGUAGE_LABELS = {
    "en": "English",
    "hi": "Hindi (हिंदी)",
    "gu": "Gujarati (ગુજરાતી)",
}

def select_language() -> str:
    print("\n" + "=" * 55)
    print("  Ultimate Smile Design — AI Calling Agent (Phase 3)")
    print("  CLI Chat Harness  |  Powered by Google Gemini")
    print("=" * 55)
    print("\nSelect conversation language:")
    print("  [1] English")
    print("  [2] Hindi (हिंदी)")
    print("  [3] Gujarati (ગુજરાતી)")
    print()

    while True:
        choice = input("Enter 1, 2, or 3: ").strip()
        if choice == "1":
            return "en"
        elif choice == "2":
            return "hi"
        elif choice == "3":
            return "gu"
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

# ---------------------------------------------------------------------------
# Main CLI loop
# ---------------------------------------------------------------------------
def main():
    language = select_language()
    call_id = str(uuid.uuid4())
    session = CallSession(call_id=call_id, opening_intent="cli_test")
    session.preferred_language = language

    model_name = settings.GEMINI_MODEL or "gemini-2.5-flash"
    print(f"\n[Session] Language : {LANGUAGE_LABELS[language]}")
    print(f"[Session] Model    : {model_name}")
    print(f"[Session] Call ID  : {call_id}")
    print("[Session] Commands : 'quit'/'exit' to end | 'tools' to list | 'lang:<en|hi|gu>' to switch language")
    print("-" * 55)

    system_prompt = load_system_prompt(language, call_id)
    messages = [{"role": "user", "content": "[START_CALL]"}]

    # Trigger the opening greeting
    opening = chat(messages=messages, system_prompt=system_prompt, call_id=call_id, session=session)
    print(f"\nAgent: {opening}\n")
    messages.append({"role": "assistant", "content": opening})

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n[Session ended by user.]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("\n[Session ended. Goodbye!]")
            break

        if user_input.lower() == "tools":
            print(f"\nAvailable tools: {TOOL_NAMES}")
            continue

        if user_input.lower().startswith("lang:"):
            new_lang = user_input.split(":")[1].strip().lower()
            if new_lang in LANGUAGE_LABELS:
                language = new_lang
                session.preferred_language = language
                system_prompt = load_system_prompt(language, call_id)
                print(f"[Language switched to: {LANGUAGE_LABELS[language]}]")
            else:
                print("[Invalid language code. Use: en, hi, or gu]")
            continue

        messages.append({"role": "user", "content": user_input})
        response = chat(messages=messages, system_prompt=system_prompt, call_id=call_id, session=session)
        messages.append({"role": "assistant", "content": response})
        print(f"\nAgent: {response}\n")

if __name__ == "__main__":
    main()