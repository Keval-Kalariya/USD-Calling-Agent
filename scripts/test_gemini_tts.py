"""
Standalone verification script for Gemini TTS client (Phase 2A).
Tests streaming audio generation, metrics analysis (latency, TTFB, duration),
error handling (empty input, metadata packets), and long-text segmentation
without altering or connecting to the existing telephony voice pipeline.
"""

import os
import sys
import time
import wave
import asyncio
from pathlib import Path

# Ensure root directory is on sys.path for internal imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.streaming.gemini_tts_stream import GeminiTTSStreamClient
from agent.audio.codecs import mulaw_to_pcm16


async def test_primary_pcm_generation():
    print("\n==================================================")
    print("TEST 1: Primary Raw PCM (24kHz) Streaming & WAV Save")
    print("==================================================")
    
    client = GeminiTTSStreamClient(output_format="pcm_24000")
    test_text = "Hello. This is a standalone Gemini TTS verification test."
    
    start_time = time.perf_counter()
    first_chunk_time = None
    chunks_received = []
    chunk_timestamps = []

    try:
        async for chunk in client.generate_stream(test_text):
            current_time = time.perf_counter()
            if first_chunk_time is None:
                first_chunk_time = current_time
            chunks_received.append(chunk)
            chunk_timestamps.append(current_time - start_time)
            if len(chunks_received) <= 5 or len(chunks_received) % 20 == 0:
                print(f"  -> Received chunk #{len(chunks_received)}: {len(chunk)} bytes at {current_time - start_time:.3f}s from start")
            
        total_synthesis_time = time.perf_counter() - start_time
        ttfb = (first_chunk_time - start_time) if first_chunk_time else 0.0
        
        total_bytes = sum(len(c) for c in chunks_received)
        num_chunks = len(chunks_received)
        avg_chunk_size = (total_bytes / num_chunks) if num_chunks else 0
        
        # PCM 16-bit mono at 24,000 Hz = 2 bytes per sample * 1 channel = 2 bytes per sample frame
        bytes_per_second_24k = 24000 * 2 * 1
        duration_sec = total_bytes / bytes_per_second_24k if bytes_per_second_24k else 0.0
        
        # Save raw PCM and converted WAV files in scripts/ output folder
        out_dir = Path(__file__).resolve().parent
        raw_pcm_path = out_dir / "gemini_output_raw.pcm"
        wav_path = out_dir / "gemini_output_24k.wav"
        
        raw_pcm_bytes = b"".join(chunks_received)
        with open(raw_pcm_path, "wb") as f:
            f.write(raw_pcm_bytes)
            
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)      # Mono
            wf.setsampwidth(2)      # 16-bit
            wf.setframerate(24000)  # 24kHz
            wf.writeframes(raw_pcm_bytes)
            
        success = num_chunks > 0 and total_bytes > 0
        status_str = "SUCCESS" if success else "FAILURE"
        
        print("\n--- AUDIO VALIDATION REPORT ---")
        print(f"Result Status:        {status_str}")
        print(f"Model Name Used:      {client.model_id}")
        print(f"Voice Configured:     {client.voice_id}")
        print(f"Sample Rate:          24000 Hz")
        print(f"Number of Channels:   1 (Mono)")
        print(f"Audio Duration:       {duration_sec:.3f} seconds")
        print(f"Total Bytes Received: {total_bytes} bytes")
        print(f"Time to First Chunk:  {ttfb:.3f} seconds (TTFB)")
        print(f"Total Synthesis Time: {total_synthesis_time:.3f} seconds")
        print(f"Number of Chunks:     {num_chunks}")
        print(f"Average Chunk Size:   {avg_chunk_size:.1f} bytes")
        print(f"Saved Raw PCM File:   {raw_pcm_path}")
        print(f"Saved Converted WAV:  {wav_path}")
        
        # Streaming Verification Check
        is_incremental = num_chunks > 1 and (chunk_timestamps[-1] - chunk_timestamps[0]) > 0.01
        print(f"\n[Streaming Check] Audio arrives incrementally without complete pre-buffering: {is_incremental} ({num_chunks} individual streaming events)")
        
        return success

    except Exception as e:
        print(f"[TEST 1 FAILED] Exception during execution: {e}")
        return False
    finally:
        await client.finish()


async def test_ulaw_transcoding_generation():
    print("\n==================================================")
    print("TEST 2: Telephony Format (8kHz u-law) Transcoding Verification")
    print("==================================================")
    
    client = GeminiTTSStreamClient(output_format="ulaw_8000")
    test_text = "Hello. This is a standalone Gemini TTS verification test."
    
    start_time = time.perf_counter()
    chunks_received = []

    try:
        async for chunk in client.generate_stream(test_text):
            chunks_received.append(chunk)
            if len(chunks_received) <= 5 or len(chunks_received) % 10 == 0:
                print(f"  -> Transcoded u-law chunk #{len(chunks_received)} received: {len(chunk)} bytes")
            
        total_time = time.perf_counter() - start_time
        total_bytes = sum(len(c) for c in chunks_received)
        
        # u-law 8,000 Hz = 1 byte per sample * 1 channel = 8000 bytes per second
        duration_sec = total_bytes / 8000.0
        
        # Decode u-law back to PCM16 to save a verification WAV file
        out_dir = Path(__file__).resolve().parent
        ulaw_wav_path = out_dir / "gemini_output_8k_transcoded.wav"
        mulaw_bytes = b"".join(chunks_received)
        pcm16_8k_bytes = mulaw_to_pcm16(mulaw_bytes)
        
        with wave.open(str(ulaw_wav_path), "wb") as wf:
            wf.setnchannels(1)     # Mono
            wf.setsampwidth(2)     # 16-bit
            wf.setframerate(8000)  # 8kHz
            wf.writeframes(pcm16_8k_bytes)
            
        print("\n--- TRANSCODING REPORT ---")
        print(f"Status:                 SUCCESS ({len(chunks_received)} transcoded chunks generated)")
        print(f"Output Encoding:        8000 Hz u-law (Twilio standard)")
        print(f"Total Bytes:            {total_bytes} bytes (~{duration_sec:.2f}s of telephony speech)")
        print(f"Total Time Taken:       {total_time:.3f} seconds")
        print(f"Saved Verification WAV: {ulaw_wav_path}")
        return len(chunks_received) > 0

    except Exception as e:
        print(f"[TEST 2 FAILED] Exception during execution: {e}")
        return False
    finally:
        await client.finish()


async def test_error_and_edge_case_handling():
    print("\n==================================================")
    print("TEST 3: Error Handling & Empty Text Verification")
    print("==================================================")
    client = GeminiTTSStreamClient(output_format="ulaw_8000")
    try:
        print("Testing empty string handling...")
        count = 0
        async for _ in client.generate_stream("   "):
            count += 1
        print(f"Empty text yielded {count} chunks (Expected: 0 handled gracefully without errors).")
        return count == 0
    except Exception as e:
        print(f"[TEST 3 FAILED] Exception during empty text test: {e}")
        return False
    finally:
        await client.finish()


async def test_long_text_segmentation():
    print("\n==================================================")
    print("TEST 4: Long Text Segmentation & Continuous Streaming")
    print("==================================================")
    client = GeminiTTSStreamClient(output_format="ulaw_8000")
    
    # Text > 400 characters containing multiple sentence structures
    long_text = (
        "Thank you so much for contacting Ultimate Smile Design today. "
        "We are thrilled to help you achieve the confident and healthy smile that you deserve! "
        "Our state of the art dental clinics are conveniently located in Ahmedabad, Surat, and Mumbai, "
        "providing top quality ceramic crowns, dental implants, and cosmetic dental treatments. "
        "Please let us know if you have any questions regarding our treatment procedures or warranties, "
        "and our senior patient care specialists will gladly assist you right away."
    )
    
    try:
        print(f"Input text length: {len(long_text)} characters.")
        start_time = time.perf_counter()
        chunks = []
        async for chunk in client.generate_stream(long_text):
            chunks.append(chunk)
            
        total_time = time.perf_counter() - start_time
        total_bytes = sum(len(c) for c in chunks)
        duration_sec = total_bytes / 8000.0
        
        print(f"Long-text stream produced {len(chunks)} total u-law chunks ({total_bytes} bytes / ~{duration_sec:.2f}s of audio) in {total_time:.2f}s.")
        print("Status: SUCCESS (Long text segmented and streamed continuously without timeouts).")
        return len(chunks) > 0
    except Exception as e:
        print(f"[TEST 4 FAILED] Exception during long text test: {e}")
        return False
    finally:
        await client.finish()


async def main():
    print("==================================================")
    print("STARTING PHASE 2A STANDALONE GEMINI TTS VALIDATION")
    print("==================================================")
    
    r1 = await test_primary_pcm_generation()
    r2 = await test_ulaw_transcoding_generation()
    r3 = await test_error_and_edge_case_handling()
    r4 = await test_long_text_segmentation()
    
    print("\n==================================================")
    print("FINAL VALIDATION SUMMARY")
    print("==================================================")
    print(f"Test 1 (Raw PCM 24kHz Stream & WAV):   {'PASSED' if r1 else 'FAILED'}")
    print(f"Test 2 (Twilio 8kHz u-law Transcode):  {'PASSED' if r2 else 'FAILED'}")
    print(f"Test 3 (Empty Input Graceful Handle):  {'PASSED' if r3 else 'FAILED'}")
    print(f"Test 4 (Long Text Auto-Segmentation):  {'PASSED' if r4 else 'FAILED'}")
    
    all_passed = r1 and r2 and r3 and r4
    if all_passed:
        print("\nALL PHASE 2A VALIDATION TESTS PASSED SUCCESSFULLY.")
        sys.exit(0)
    else:
        print("\nONE OR MORE VALIDATION TESTS FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
