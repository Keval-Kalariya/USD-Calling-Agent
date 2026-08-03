import json
import os

CALLS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "calls.json")

def load_calls():
    if not os.path.exists(CALLS_FILE):
        return {}
    with open(CALLS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_calls(calls: dict):
    os.makedirs(os.path.dirname(CALLS_FILE), exist_ok=True)
    with open(CALLS_FILE, "w", encoding="utf-8") as f:
        json.dump(calls, f, indent=2, ensure_ascii=False)

def log_call_end(call_id: str, transcript: list, duration_seconds: float, status: str):
    calls = load_calls()
    if call_id in calls:
        calls[call_id]["transcript"] = transcript
        calls[call_id]["duration_seconds"] = duration_seconds
        calls[call_id]["status"] = status
    save_calls(calls)

def load_usage():
    usage_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "usage.json")
    if not os.path.exists(usage_file):
        return []
    with open(usage_file, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def log_usage(call_id: str, stt_seconds: float, tts_chars: int, llm_tokens: int):
    from datetime import datetime, timezone
    usage_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "usage.json")
    usages = load_usage()
    usages.append({
        "call_id": call_id,
        "stt_seconds": stt_seconds,
        "tts_chars": tts_chars,
        "llm_tokens": llm_tokens,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    os.makedirs(os.path.dirname(usage_file), exist_ok=True)
    with open(usage_file, "w", encoding="utf-8") as f:
        json.dump(usages, f, indent=2, ensure_ascii=False)
