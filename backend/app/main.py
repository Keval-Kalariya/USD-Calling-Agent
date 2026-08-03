from fastapi import FastAPI
from backend.app.routes import twilio_voice, internal_callback

app = FastAPI(title="USD Calling Agent")

app.include_router(twilio_voice.router)
app.include_router(internal_callback.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}
