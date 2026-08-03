import os
import httpx
from typing import AsyncGenerator
from backend.app.settings import settings

class ElevenLabsStreamClient:
    """
    An asynchronous streaming client for ElevenLabs TTS.
    Configured to request ulaw_8000 to match Twilio's expected outbound format perfectly,
    allowing us to bypass any local transcoding.
    """
    def __init__(self, voice_id: str | None = None, model_id: str = "eleven_multilingual_v2"):
        self.api_key = settings.ELEVENLABS_API_KEY
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY is not set in settings or environment.")
        
        self.voice_id = voice_id or settings.ELEVENLABS_VOICE_ID
        self.model_id = model_id
        # Requests ulaw 8000Hz directly from ElevenLabs
        self.output_format = "ulaw_8000"
        
        self.url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream?output_format={self.output_format}"
        self._closed: bool = False

    async def finish(self) -> None:
        """Gracefully tears down the TTS streaming interface and marks client closed."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        print("[ElevenLabs Stream] Client finished and session closed.")

    async def close(self) -> None:
        """Alias for finish to maintain a uniform lifecycle interface."""
        await self.finish()

    async def generate_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Connects to ElevenLabs via an HTTP chunked stream and yields raw ulaw_8000 bytes.
        We use raw httpx to ensure true async streaming without blocking the event loop.
        """
        if getattr(self, "_closed", False):
            print("[ElevenLabs Error] Cannot generate stream: client is closed.")
            return
        headers = {
            "Accept": "audio/basic",  # Usually standard for ulaw/pcm streaming
            "xi-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        data = {
            "text": text,
            "model_id": self.model_id
        }
        
        print(f"[ElevenLabs] Requesting TTS stream for: '{text}'")
        try:
            # We use an async HTTP client to stream the chunks as they are generated
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", self.url, headers=headers, json=data) as response:
                    if response.status_code != 200:
                        await response.aread()
                        print(f"[ElevenLabs Error] HTTP {response.status_code}: {response.text}")
                        return
                        
                    # Iterate over the chunks as they arrive from the network
                    # A smaller chunk size ensures lower latency delivery to Twilio
                    async for chunk in response.aiter_bytes(chunk_size=2048):
                        if chunk:
                            yield chunk
            print("[ElevenLabs] TTS stream completed successfully.")
        except Exception as e:
            print(f"[ElevenLabs Error] Connection or streaming failed: {e}")
