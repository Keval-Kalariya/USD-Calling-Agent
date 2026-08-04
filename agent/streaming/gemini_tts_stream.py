"""
Standalone asynchronous streaming Text-to-Speech (TTS) client utilizing Google Gemini Models API.
Designed as an interoperable, drop-in alternative to ElevenLabsStreamClient without importing or
colliding with the Gemini LLM conversational chat client. Includes exponential backoff rate-limit
handling, strict barge-in cleanup, timeout protection, and comprehensive structured logging.
"""

import os
import re
import time
import asyncio
import inspect
from typing import AsyncGenerator, List, Optional, Tuple

from google import genai
from google.genai import types as genai_types
from backend.app.settings import settings
from agent.audio.codecs import resample_pcm16, pcm16_to_mulaw


class GeminiTTSStreamClient:
    """
    An asynchronous streaming client for Google Gemini Native TTS using the official google-genai SDK.
    Matches the public interface of ElevenLabsStreamClient while providing robust transcoding,
    resampling, rate-limit retry with exponential backoff, error handling, and long-text sentence segmentation.
    """
    def __init__(
        self,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        output_format: str = "ulaw_8000",
        timeout: Optional[float] = None
    ):
        # Single source of truth from settings with optional environment runtime overrides
        self.api_key = os.environ.get("GEMINI_API_KEY") or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set in settings or environment.")
            
        # Instantiate a dedicated, stateless Gemini client for TTS generation
        self.client = genai.Client(api_key=self.api_key)
        
        self.voice_id = voice_id or settings.GEMINI_TTS_VOICE
        self.model_id = model_id or settings.GEMINI_TTS_MODEL
        self.timeout = timeout or settings.GEMINI_TTS_TIMEOUT
        self.output_format = output_format  # Supports "ulaw_8000" (Twilio standard) or "pcm_24000" (raw SDK output)
        
        # Configure Speech and Modality options for audio generation
        self._speech_config = genai_types.SpeechConfig(
            voice_config=genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                    voice_name=self.voice_id
                )
            )
        )
        self._generate_config = genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=self._speech_config
        )
        
        self._closed: bool = False
        print(f"[Gemini TTS Stream] Provider selected: gemini | Model: {self.model_id} | Voice: {self.voice_id} | Format: {self.output_format} | Timeout: {self.timeout}s")

    async def finish(self) -> None:
        """Gracefully tears down the TTS streaming interface and marks client closed."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        try:
            if hasattr(self.client, "aio") and hasattr(self.client.aio, "close") and callable(self.client.aio.close):
                res = self.client.aio.close()
                if inspect.isawaitable(res):
                    await res
            elif hasattr(self.client, "close") and callable(self.client.close):
                res = self.client.close()
                if inspect.isawaitable(res):
                    await res
        except Exception as e:
            print(f"[Gemini TTS Error] Exception during finish: {e}")
        print("[Gemini TTS Stream] Client finished and network resources closed.")

    async def close(self) -> None:
        """Alias for finish to maintain a uniform lifecycle interface."""
        await self.finish()

    def _split_long_sentence(self, sentence: str, max_length: int) -> List[str]:
        """Helper to safely segment an oversized single sentence along word boundaries."""
        words = sentence.split()
        chunks: List[str] = []
        temp_chunk = ""
        for word in words:
            if len(temp_chunk) + len(word) + 1 <= max_length:
                temp_chunk = f"{temp_chunk} {word}".strip() if temp_chunk else word
            else:
                if temp_chunk:
                    chunks.append(temp_chunk)
                temp_chunk = word
        if temp_chunk:
            chunks.append(temp_chunk)
        return chunks

    def _segment_text(self, text: str, max_length: int = 400) -> List[str]:
        """
        Long Text Handling Strategy:
        Generative audio models perform best on focused conversational utterances. If an incoming text
        exceeds `max_length` characters, feeding it in a single API call increases latency to first byte,
        risks network timeouts, and may trigger model hallucinations or silent audio padding.
        
        This method safely segments long text by splitting along grammatical sentence boundaries
        (periods, exclamation points, question marks, semicolons, or newlines) while ensuring no segment
        exceeds `max_length`. If an individual sentence exceeds `max_length`, it falls back to word-boundary
        splitting. Each segment is sequentially streamed in order to maintain continuous vocal flow.
        """
        text = text.strip()
        if not text:
            return []
        if len(text) <= max_length:
            return [text]

        # Split along major sentence punctuation while retaining the delimiter
        raw_splits = re.split(r'(?<=[.!?;\n])\s+', text)
        segments: List[str] = []
        current_chunk = ""

        for sentence in raw_splits:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # If combining with current chunk stays within limit, accumulate
            if not current_chunk:
                if len(sentence) <= max_length:
                    current_chunk = sentence
                else:
                    word_chunks = self._split_long_sentence(sentence, max_length)
                    segments.extend(word_chunks[:-1])
                    current_chunk = word_chunks[-1] if word_chunks else ""
            elif len(current_chunk) + len(sentence) + 1 <= max_length:
                current_chunk = f"{current_chunk} {sentence}"
            else:
                segments.append(current_chunk)
                if len(sentence) <= max_length:
                    current_chunk = sentence
                else:
                    word_chunks = self._split_long_sentence(sentence, max_length)
                    segments.extend(word_chunks[:-1])
                    current_chunk = word_chunks[-1] if word_chunks else ""

        if current_chunk:
            segments.append(current_chunk)
            
        return segments

    async def generate_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Connects to Gemini Models streaming endpoint, generates audio from text segments,
        and yields either resampled 8kHz u-law bytes (matching Twilio & ElevenLabs standards)
        or raw 24kHz linear PCM bytes depending on configured `output_format`.
        
        Includes robust error handling, rate-limit retry with exponential backoff,
        timeout protection, and immediate resource release upon barge-in cancellation.
        """
        if getattr(self, "_closed", False):
            print("[Gemini TTS Error] Cannot generate stream: client is closed.")
            return

        if not text or not text.strip():
            print("[Gemini TTS Warning] Ignored empty or whitespace-only TTS input.")
            return

        segments = self._segment_text(text)
        if not segments:
            return

        request_start_time = time.perf_counter()
        print(f"[Gemini TTS] Request start (Provider: gemini, Model: {self.model_id}, Voice: {self.voice_id}): '{text[:60]}...' ({len(segments)} segment(s))")
        
        # Audio resampling state for maintaining continuous filter state across streamed packets
        resample_state: Optional[tuple] = None
        # Buffer for holding any odd byte in case network chunks arrive split across a 16-bit sample boundary
        pcm_remainder: bytes = b""
        first_chunk_logged = False
        max_retries = 3

        try:
            for segment_index, segment in enumerate(segments):
                if self._closed:
                    break
                
                attempt = 0
                stream_resp = None
                while attempt < max_retries:
                    attempt += 1
                    try:
                        # Initiate streaming request with explicit timeout
                        stream_resp = await asyncio.wait_for(
                            self.client.aio.models.generate_content_stream(
                                model=self.model_id,
                                contents=segment,
                                config=self._generate_config
                            ),
                            timeout=self.timeout
                        )
                        break  # Successfully acquired generator; break out of retry loop
                    except asyncio.CancelledError:
                        raise
                    except asyncio.TimeoutError:
                        print(f"[Gemini TTS Error] Timeout ({self.timeout}s) occurred on request start (segment {segment_index + 1}). Terminating cleanly.")
                        return
                    except Exception as e:
                        # Detect rate limiting (e.g. HTTP 429, ResourceExhausted, quota errors) or transient connection drops
                        err_str = str(e).lower()
                        is_rate_limit = "429" in err_str or "resourceexhausted" in err_str or "quota" in err_str or "rate" in err_str or "limit" in err_str
                        if attempt < max_retries:
                            backoff_delay = 1.5 ** attempt
                            reason = "Rate-limit encountered" if is_rate_limit else f"Transient API error: {e}"
                            print(f"[Gemini TTS Warning] {reason}. Retrying in {backoff_delay:.2f}s (attempt {attempt}/{max_retries})...")
                            await asyncio.sleep(backoff_delay)
                        else:
                            print(f"[Gemini TTS Error] Max retries exhausted ({max_retries}) on segment {segment_index + 1}: {e}")
                            return

                if not stream_resp:
                    continue

                try:
                    # Iterate over arriving audio packets from gRPC/REST stream
                    while True:
                        try:
                            chunk = await asyncio.wait_for(stream_resp.__anext__(), timeout=self.timeout)
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            print(f"[Gemini TTS Error] Timeout ({self.timeout}s) occurred while waiting for streaming audio chunk on segment {segment_index + 1}.")
                            break
                            
                        # Safely ignore trailing metadata packets or chunks lacking audio data blobs
                        if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                            continue
                        
                        for part in chunk.candidates[0].content.parts:
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data is None:
                                continue
                                
                            raw_data = getattr(inline_data, "data", None)
                            if not raw_data:
                                continue
                                
                            if not first_chunk_logged:
                                ttfb = time.perf_counter() - request_start_time
                                print(f"[Gemini TTS] First audio chunk generated in {ttfb:.3f}s (TTFB).")
                                first_chunk_logged = True
                                
                            # Ensure 16-bit alignment (pairs of bytes) for PCM processing
                            combined_bytes = pcm_remainder + raw_data
                            if len(combined_bytes) % 2 != 0:
                                pcm_remainder = combined_bytes[-1:]
                                valid_pcm = combined_bytes[:-1]
                            else:
                                pcm_remainder = b""
                                valid_pcm = combined_bytes
                                
                            if not valid_pcm:
                                continue
                                
                            if self.output_format == "pcm_24000":
                                yield valid_pcm
                            else:
                                # Transcode from 24000Hz 16-bit linear PCM down to 8000Hz PCM, then to u-law
                                resampled_pcm, resample_state = resample_pcm16(
                                    pcm_bytes=valid_pcm,
                                    in_rate=24000,
                                    out_rate=8000,
                                    state=resample_state
                                )
                                if resampled_pcm:
                                    mulaw_bytes = pcm16_to_mulaw(resampled_pcm)
                                    # Segment large bursts into chunks <= 2048 bytes (matching ElevenLabs & Twilio jitter buffers)
                                    chunk_size = 2048
                                    for idx in range(0, len(mulaw_bytes), chunk_size):
                                        slice_chunk = mulaw_bytes[idx:idx + chunk_size]
                                        if slice_chunk:
                                            yield slice_chunk

                finally:
                    # Cleanly close underlying generator if available to avoid network socket leaks
                    if hasattr(stream_resp, "aclose") and callable(stream_resp.aclose):
                        try:
                            res = stream_resp.aclose()
                            if inspect.isawaitable(res):
                                await res
                        except Exception:
                            pass

        except asyncio.CancelledError:
            print("[Gemini TTS Stream] Generation task cancelled by caller/orchestrator (barge-in). Releasing network resources.")
            raise
        except Exception as e:
            print(f"[Gemini TTS Error] Unexpected exception during speech synthesis: {e}")
        finally:
            total_latency = time.perf_counter() - request_start_time
            print(f"[Gemini TTS Stream] Synthesis complete. Total latency: {total_latency:.3f}s.")
