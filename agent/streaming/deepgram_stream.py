import os
import asyncio
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from backend.app.settings import settings

class DeepgramStreamClient:
    """
    An asynchronous client for Deepgram's live streaming API via WebSocket.
    Configured by default to accept 8kHz μ-law audio to match Twilio's payload exactly,
    eliminating the need for transcoding. Includes an automatic reconnection watchdog.
    """
    def __init__(self, sample_rate: int = 8000, encoding: str = "mulaw", language: str = "multi", on_transcript=None, on_unexpected_disconnect=None, on_reconnect=None):
        self.sample_rate = sample_rate
        self.encoding = encoding
        self.language = language
        self.on_transcript = on_transcript
        self.on_unexpected_disconnect = on_unexpected_disconnect
        self.on_reconnect = on_reconnect
        
        if not settings.DEEPGRAM_API_KEY:
            raise ValueError("DEEPGRAM_API_KEY is not set in settings or environment.")
            
        self.dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        self.dg_connection = self.dg_client.listen.asyncwebsocket.v("1")
        
        # Watchdog synchronization flags
        self._is_connected: bool = False
        self._should_reconnect: bool = True
        self._reconnect_task: asyncio.Task | None = None
        
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        async def on_message(self_dg, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if not sentence.strip():
                return
            is_final = result.is_final
            if is_final:
                print(f"[Final Transcript] {sentence}")
            else:
                print(f"[Partial Transcript] {sentence}")
            if self.on_transcript:
                self.on_transcript(sentence.strip(), is_final)

        async def on_error(self_dg, error, **kwargs):
            print(f"[Deepgram Error] {error}")
            
        async def on_close(self_dg, close, **kwargs):
            self._is_connected = False
            print("[Deepgram Closed] Connection closed.")
            if self._should_reconnect and (self._reconnect_task is None or self._reconnect_task.done()):
                if self.on_unexpected_disconnect:
                    try:
                        self.on_unexpected_disconnect()
                    except Exception as e:
                        print(f"[Deepgram Error] Exception in on_unexpected_disconnect callback: {e}")
                self._reconnect_task = asyncio.create_task(self._auto_reconnect())

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
        self.dg_connection.on(LiveTranscriptionEvents.Error, on_error)
        self.dg_connection.on(LiveTranscriptionEvents.Close, on_close)

    async def connect(self):
        """Starts the WebSocket connection with the given options."""
        options = LiveOptions(
            model="nova-2",
            language=self.language,
            smart_format=True,
            encoding=self.encoding,
            sample_rate=self.sample_rate,
            interim_results=True,
            endpointing=300
        )
        
        if await self.dg_connection.start(options) is False:
            raise ConnectionError("Failed to connect to Deepgram streaming API")
            
        self._is_connected = True
        print(f"[Deepgram] Connected and listening (Format: {self.encoding}, {self.sample_rate}Hz)...")

    async def _auto_reconnect(self):
        """Watchdog routine that retries establishing the Deepgram WebSocket connection upon an unexpected drop."""
        backoff_delay = 0.5
        max_delay = 4.0
        print("[Deepgram Watchdog] Unexpected disconnection detected. Initiating auto-reconnect loop...")
        while self._should_reconnect and not self._is_connected:
            try:
                print(f"[Deepgram Watchdog] Attempting reconnection in {backoff_delay:.1f}s...")
                await asyncio.sleep(backoff_delay)
                # Re-initialize connection socket handle and re-bind event handlers
                self.dg_connection = self.dg_client.listen.asyncwebsocket.v("1")
                self._setup_event_handlers()
                await self.connect()
                print("[Deepgram Watchdog] Reconnection successful! Speech streaming resumed.")
                if self.on_reconnect:
                    try:
                        self.on_reconnect()
                    except Exception as e:
                        print(f"[Deepgram Watchdog Error] Exception in on_reconnect callback: {e}")
                break
            except Exception as e:
                print(f"[Deepgram Watchdog] Reconnection attempt failed: {e}")
                backoff_delay = min(backoff_delay * 2, max_delay)
        self._reconnect_task = None

    async def send_audio(self, data: bytes):
        """Sends raw audio bytes (must match the configured encoding/sample_rate)."""
        if self.dg_connection and self._is_connected:
            try:
                await self.dg_connection.send(data)
            except Exception as e:
                if self._is_connected:
                    print(f"[Deepgram Error] Failed to send audio packet: {e}")
                    self._is_connected = False
                if self._should_reconnect and (self._reconnect_task is None or self._reconnect_task.done()):
                    if self.on_unexpected_disconnect:
                        try:
                            self.on_unexpected_disconnect()
                        except Exception as e:
                            print(f"[Deepgram Error] Exception in on_unexpected_disconnect callback: {e}")
                    self._reconnect_task = asyncio.create_task(self._auto_reconnect())
            
    async def finish(self):
        """Closes the Deepgram WebSocket connection gracefully and disables the reconnect watchdog."""
        if not self._should_reconnect and not getattr(self, "dg_connection", None):
            return
        self._should_reconnect = False
        self._is_connected = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reconnect_task = None
        conn = self.dg_connection
        self.dg_connection = None
        if conn:
            try:
                await conn.finish()
            except Exception as e:
                print(f"[Deepgram Error] Exception during finish: {e}")
            print("[Deepgram] Client finished and connection closed.")

    async def close(self):
        """Alias for finish to maintain a uniform lifecycle interface."""
        await self.finish()
