import os
import sys
import httpx
import asyncio

# Add backend to path to import settings
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.settings import settings

async def check_twilio():
    missing = []
    if not settings.TWILIO_ACCOUNT_SID: missing.append("TWILIO_ACCOUNT_SID")
    if not settings.TWILIO_AUTH_TOKEN: missing.append("TWILIO_AUTH_TOKEN")
    if not settings.TWILIO_NUMBER: missing.append("TWILIO_NUMBER")
    
    if missing:
        print(f"[-] Twilio: Missing credentials ({', '.join(missing)})")
        return
        
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}.json"
    auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, auth=auth)
            if resp.status_code == 200:
                print(f"[+] Twilio: OK (Number: {settings.TWILIO_NUMBER})")
            else:
                print(f"[-] Twilio: Failed ({resp.status_code}) - {resp.text.strip()}")
        except Exception as e:
            print(f"[-] Twilio: Error - {e}")

async def check_deepgram():
    if not settings.DEEPGRAM_API_KEY:
        print("[-] Deepgram: Missing DEEPGRAM_API_KEY")
        return
    url = "https://api.deepgram.com/v1/projects"
    headers = {"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                print("[+] Deepgram: OK")
            else:
                print(f"[-] Deepgram: Failed ({resp.status_code}) - {resp.text.strip()}")
        except Exception as e:
            print(f"[-] Deepgram: Error - {e}")

async def check_elevenlabs():
    if not settings.ELEVENLABS_API_KEY:
        print("[-] ElevenLabs: Missing ELEVENLABS_API_KEY")
        return
    url = "https://api.elevenlabs.io/v1/models"
    headers = {"xi-api-key": settings.ELEVENLABS_API_KEY}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                print("[+] ElevenLabs: OK")
            else:
                print(f"[-] ElevenLabs: Failed ({resp.status_code}) - {resp.text.strip()}")
        except Exception as e:
            print(f"[-] ElevenLabs: Error - {e}")

async def check_gemini():
    if not settings.GEMINI_API_KEY:
        print("[-] Gemini: Missing GEMINI_API_KEY")
        return
    model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.GEMINI_API_KEY}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                print(f"[+] Gemini: OK (Model: {model})")
            else:
                print(f"[-] Gemini: Failed ({resp.status_code}) - {resp.text.strip()}")
        except Exception as e:
            print(f"[-] Gemini: Error - {e}")

async def main():
    print("==================================================")
    print(" Ultimate Smile Design Agent - Service Key Diagnostic")
    print("==================================================" + "\n")
    
    await asyncio.gather(
        check_twilio(),
        check_deepgram(),
        check_elevenlabs(),
        check_gemini()
    )
    print("\nDiagnostic complete.")

if __name__ == "__main__":
    asyncio.run(main())
