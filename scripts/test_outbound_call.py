import os
import sys
from twilio.rest import Client

# Add project root to path so 'backend' package is discoverable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from backend.app.settings import settings
except ImportError as e:
    print(f"Failed to import settings: {e}")
    sys.exit(1)

def make_outbound_call(to_number: str, webhook_url: str):
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_NUMBER:
        print("Missing Twilio credentials in environment. Check your .env file.")
        sys.exit(1)
        
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    
    print(f"Initiating call from {settings.TWILIO_NUMBER} to {to_number}...")
    print(f"Webhook URL: {webhook_url}")
    
    call = client.calls.create(
        to=to_number,
        from_=settings.TWILIO_NUMBER,
        url=webhook_url,
        method="POST"
    )
    
    print(f"Call initiated successfully. Call SID: {call.sid}")
    print("Check your FastAPI server logs for the incoming webhook!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_outbound_call.py <destination_number> <ngrok_webhook_url>")
        print("Example: python scripts/test_outbound_call.py +918758657212 https://drumliest-nonculpably-song.ngrok-free.dev/twilio/voice")
        sys.exit(1)
        
    make_outbound_call(sys.argv[1], sys.argv[2])