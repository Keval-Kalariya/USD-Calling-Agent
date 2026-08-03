"""
Lead data model — Phase 3.
File-backed for now; promoted to a real DB table in Phase 5.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import uuid


class Lead(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    call_id: Optional[str] = None          # FK to Call.id — linked in Phase 5
    name: str
    phone: str
    city: str
    intent: str                            # consultation | find_dentist | warranty_verification | faq | other
    notes: Optional[str] = None
    preferred_language: str = "en"        # en | hi | gu — used by Phase 5 for TTS language selection
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
