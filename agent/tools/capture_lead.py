"""
Tool: capture_lead
Saves a caller's lead details to persistent storage (JSON file for Phase 3,
promoted to a real database table in Phase 5).
"""

import json
import uuid
import os
from datetime import datetime, timezone
from typing import Optional

# Phase 3: file-backed store. Phase 5 will swap this for a DB table.
LEADS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "leads.json")

VALID_LANGUAGES = {"en", "hi", "gu"}

def _load_leads() -> list:
    if not os.path.exists(LEADS_FILE):
        return []
    with open(LEADS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def _save_leads(leads: list) -> None:
    os.makedirs(os.path.dirname(LEADS_FILE), exist_ok=True)
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2, ensure_ascii=False)

def capture_lead(
    name: str,
    phone: str,
    city: str,
    intent: str,
    notes: Optional[str] = None,
    preferred_language: str = "en",
    call_id: Optional[str] = None,
) -> dict:
    """
    Persists caller lead details.

    Args:
        name:               Caller's full name.
        phone:              Caller's phone number (with country code ideally).
        city:               City where the caller wants dental services.
        intent:             One of: consultation, find_dentist, warranty_verification, faq, other.
        notes:              Any additional notes from the conversation.
        preferred_language: Caller's language preference — en | hi | gu.
        call_id:            The call ID this lead originates from (FK to calls table in Phase 5).

    Returns:
        A dict with the saved lead and a status message in the caller's language.
    """
    if preferred_language not in VALID_LANGUAGES:
        preferred_language = "en"

    lead = {
        "id": str(uuid.uuid4()),
        "call_id": call_id,
        "name": name.strip(),
        "phone": phone.strip(),
        "city": city.strip(),
        "intent": intent.strip(),
        "notes": notes.strip() if notes else None,
        "preferred_language": preferred_language,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    leads = _load_leads()
    leads.append(lead)
    _save_leads(leads)

    # Confirmation messages in all three languages
    confirmations = {
        "en": (
            f"Thank you, {name}! I've saved your details. "
            f"Our team will call you back at {phone} shortly."
        ),
        "hi": (
            f"धन्यवाद, {name}! आपकी जानकारी save कर ली गई है। "
            f"हमारी team जल्द ही {phone} पर आपको callback करेगी।"
        ),
        "gu": (
            f"આભાર, {name}! આपकी details save थई गई छे। "
            f"અmāri team ṭhūṃk samay māṃ {phone} par āpne callback karśe."
        ),
    }

    return {
        "status": "success",
        "lead_id": lead["id"],
        "message": confirmations[preferred_language],
        "lead": lead,
    }
