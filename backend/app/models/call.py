from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid

class Call(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    twilio_call_sid: str
    direction: str
    from_number: str
    to_number: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    transcript: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "started"

    def to_dict(self):
        d = self.model_dump()
        d["started_at"] = self.started_at.isoformat() if self.started_at else None
        d["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        return d
