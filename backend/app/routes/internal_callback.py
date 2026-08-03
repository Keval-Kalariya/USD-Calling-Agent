import os
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from twilio.rest import Client
import sys

from backend.app.settings import settings
from backend.app.models.call import Call

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from agent.utils.call_logger import save_calls, load_calls

router = APIRouter()

class TriggerCallbackRequest(BaseModel):
    lead_id: str

# NOTE: This in-memory rate limit works for testing but will reset on deploy. 
# It should be replaced with Redis or a database table for production.
# In-memory rate limiting dictionary: { phone_number: last_called_timestamp }
rate_limit_cache = {}

def get_internal_key(request: Request):
    key = request.headers.get("X-Internal-Key")
    if not key or key != settings.INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return key

@router.post("/internal/trigger-callback")
async def trigger_callback(payload: TriggerCallbackRequest, request: Request, _ = Depends(get_internal_key)):
    # 1. Load lead
    leads_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "leads.json"))
    if not os.path.exists(leads_file):
        raise HTTPException(status_code=404, detail="No leads data found")
        
    with open(leads_file, "r", encoding="utf-8") as f:
        try:
            leads = json.load(f)
        except json.JSONDecodeError:
            leads = []
            
    lead = next((l for l in leads if l["id"] == payload.lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    phone = lead.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")
        
    # Format phone for E.164 if needed (assuming India +91 if not specified)
    if not phone.startswith("+"):
        if len(phone) == 10:
            phone = "+91" + phone
        else:
            phone = "+" + phone
            
    # 2. Check ALLOWED_NUMBERS
    allowed = [n.strip() for n in settings.ALLOWED_NUMBERS.split(",") if n.strip()]
    if allowed and phone not in allowed:
        raise HTTPException(status_code=403, detail=f"Phone number {phone} is not in ALLOWED_NUMBERS")
        
    # 3. Check rate limits (1 call per 5 minutes)
    now = datetime.now(timezone.utc).timestamp()
    last_called = rate_limit_cache.get(phone, 0)
    if now - last_called < 300:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait 5 minutes before calling this number again.")
        
    # 4. Initiate call via Twilio
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_NUMBER:
        raise HTTPException(status_code=500, detail="Twilio credentials missing")
        
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    
    host = request.headers.get("host", "localhost:8000")
    protocol = "https" if "ngrok.app" in host or "ngrok-free.app" in host or request.url.scheme == "https" else "http"
    
    import urllib.parse
    webhook_url = f"{protocol}://{host}/twilio/voice?opening_intent=follow-up&lead_id={urllib.parse.quote(payload.lead_id)}"
    status_callback_url = f"{protocol}://{host}/twilio/status-callback"
    
    # Pre-log the call as initiated using a local UUID
    # NOTE: This in-memory rate limit works for testing but will reset on deploy. Use Redis/DB for production.
    internal_call_id = str(uuid.uuid4())
    call_log = Call(
        id=internal_call_id,
        twilio_call_sid="",
        direction="outbound",
        from_number=settings.TWILIO_NUMBER,
        to_number=phone,
        status="initiated"
    )
    calls_db = load_calls()
    calls_db[internal_call_id] = call_log.to_dict()
    save_calls(calls_db)
    
    try:
        call = client.calls.create(
            to=phone,
            from_=settings.TWILIO_NUMBER,
            url=webhook_url,
            method="POST",
            status_callback=status_callback_url,
            status_callback_event=["initiated", "ringing", "answered", "completed"]
        )
        
        # Update the log with Twilio's SID
        calls_db = load_calls()
        if internal_call_id in calls_db:
            call_data = calls_db.pop(internal_call_id)
            call_data["twilio_call_sid"] = call.sid
            calls_db[call.sid] = call_data
            save_calls(calls_db)
        
        rate_limit_cache[phone] = now
        
        return {"status": "success", "call_sid": call.sid}
    except Exception as e:
        calls_db = load_calls()
        if internal_call_id in calls_db:
            calls_db[internal_call_id]["status"] = "failed"
            save_calls(calls_db)
        raise HTTPException(status_code=500, detail=str(e))
