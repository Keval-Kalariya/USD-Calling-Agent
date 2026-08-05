import base64
import json
import asyncio
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
import urllib.parse

# Corrected module import matching project root setup
from backend.app.models.call import Call

from agent.utils.call_logger import save_calls, load_calls, log_call_end, log_usage
from agent.pipeline import VoicePipelineOrchestrator

router = APIRouter()

@router.post("/twilio/voice")
async def twilio_voice_webhook(request: Request):
    """
    Handles the initial POST webhook from Twilio when a call connects.
    Returns TwiML instructing Twilio to open a WebSocket media stream.
    """
    form_data = await request.form()
    
    call_sid = form_data.get("CallSid", "")
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")
    direction = form_data.get("Direction", "inbound")
    
    opening_intent = request.query_params.get("opening_intent")
    lead_id = request.query_params.get("lead_id")

    # Log the new call to data/calls.json
    call_log = Call(
        twilio_call_sid=str(call_sid),
        direction=str(direction),
        from_number=str(from_number),
        to_number=str(to_number)
    )
    
    calls_db = load_calls()
    calls_db[call_sid] = call_log.to_dict()
    save_calls(calls_db)
    
    # Determine the host for the websocket stream
    host = request.headers.get("host", "localhost:8000")
    protocol = "wss" if "ngrok.app" in host or "ngrok-free.app" in host or request.url.scheme == "https" else "ws"
    
    base_url = f"{protocol}://{host}/twilio/media-stream?call_sid={call_sid}"
    
    if opening_intent:
        base_url += f"&opening_intent={urllib.parse.quote(opening_intent)}"
    if lead_id:
        base_url += f"&lead_id={urllib.parse.quote(lead_id)}"
        
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{base_url}" />
    </Connect>
</Response>"""

    return Response(content=twiml, media_type="application/xml")

@router.post("/twilio/status-callback")
async def twilio_status_callback(request: Request):
    """
    Handles Twilio status callbacks to keep our call record lifecycle up to date.
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    
    if call_sid and call_status:
        calls_db = load_calls()
        if call_sid in calls_db:
            calls_db[call_sid]["status"] = call_status
            save_calls(calls_db)
            
    return Response(status_code=200)

@router.websocket("/twilio/media-stream")
async def twilio_media_stream(websocket: WebSocket, call_sid: str = "", opening_intent: str | None = None, lead_id: str | None = None):
    """
    Accepts bidirectional audio stream from Twilio and delegates real-time conversational
    turns to the VoicePipelineOrchestrator powered by Google Gemini Live API.
    """
    await websocket.accept()
    call_sid = call_sid or websocket.query_params.get("call_sid", "")
    print(f"[WS] Connection accepted for CallSid: {call_sid}")
    
    lead_name = None
    lead_city = None
    if lead_id:
        try:
            leads_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "leads.json")
            if os.path.exists(leads_path):
                with open(leads_path, "r", encoding="utf-8") as f:
                    leads = json.load(f)
                    for l in leads:
                        if l.get("id") == lead_id:
                            lead_name = l.get("name")
                            lead_city = l.get("city")
                            break
        except Exception as e:
            print(f"[WS] Could not look up lead details for {lead_id}: {e}")
            
    orchestrator = None

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event_type = data.get("event")

            if event_type == "connected":
                print("[WS] Twilio connected event received.")
                
            elif event_type == "start":
                stream_sid = data["start"]["streamSid"]
                call_sid = data["start"].get("callSid", call_sid)
                print(f"[WS] Stream started. StreamSid: {stream_sid}, CallSid: {call_sid}")
                
                orchestrator = VoicePipelineOrchestrator(
                    websocket=websocket,
                    call_id=str(call_sid),
                    stream_sid=str(stream_sid),
                    opening_intent=opening_intent,
                    lead_id=lead_id,
                    lead_name=lead_name,
                    lead_city=lead_city
                )
                await orchestrator.start()
                
            elif event_type == "media":
                if orchestrator is not None:
                    payload = data["media"]["payload"]
                    await orchestrator.handle_media_payload(payload)
                
            elif event_type == "stop":
                print(f"[WS] Stream stopped by Twilio.")
                break
                
    except WebSocketDisconnect:
        print(f"[WS] WebSocket disconnected for CallSid: {call_sid}")
    except Exception as e:
        print(f"[WS] Error handling stream for CallSid {call_sid}: {e}")
    finally:
        if orchestrator is not None:
            await orchestrator.stop()
        print(f"[WS] Cleaned up stream for CallSid: {call_sid}")