import os
import sys
import time
import asyncio
from deepgram import DeepgramClient, DeepgramClientOptions, LiveTranscriptionEvents, LiveOptions

# Add backend to path to import settings
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))
try:
    from app.settings import settings
except ImportError:
    print("Failed to import settings. Ensure you are running this from the project root.")
    sys.exit(1)

async def test_stt_scenario(scenario_name: str, file_path: str, model: str, language: str):
    print(f"\n{'='*50}")
    print(f"Scenario: {scenario_name}")
    print(f"Model: {model} | Language: {language}")
    print(f"File: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"[-] Missing audio file for {scenario_name}.")
        print(f"    Please record a short WAV file and save it as '{file_path}' to test this scenario.")
        return

    print("Connecting to Deepgram streaming API...")
    try:
        deepgram: DeepgramClient = DeepgramClient(settings.DEEPGRAM_API_KEY)
        dg_connection = deepgram.listen.asyncwebsocket.v("1")
        
        first_partial_time = None
        start_time = None

        async def on_message(self, result, **kwargs):
            nonlocal first_partial_time
            sentence = result.channel.alternatives[0].transcript
            
            if not sentence.strip():
                return
                
            is_final = result.is_final
            
            if start_time is not None and first_partial_time is not None:
                latency_ms = (first_partial_time - start_time) * 1000
                print(f"[Lat] Time to first partial: {latency_ms:.0f}ms")
            
            if is_final:
                print(f"[Final] {sentence}")
            else:
                print(f"[Partial] {sentence}")

        async def on_error(self, error, **kwargs):
            print(f"[Error] {error}")

        dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
        dg_connection.on(LiveTranscriptionEvents.Error, on_error)

        options: LiveOptions = LiveOptions(
            model=model,
            language=language,
            smart_format=True,
            # We assume a standard linear16 wav file for testing, update if using mulaw
            encoding="linear16", 
            sample_rate=16000, 
            interim_results=True,
        )
        
        if await dg_connection.start(options) is False:
            print("Failed to connect to Deepgram")
            return

        start_time = time.time()

        # Send audio file chunks simulating a live stream
        chunk_size = 4096
        with open(file_path, "rb") as audio:
            # Skip WAV header (44 bytes) to send raw PCM stream
            audio.read(44)
            while True:
                data = audio.read(chunk_size)
                if not data:
                    break
                await dg_connection.send(data)
                # Sleep briefly to simulate streaming
                await asyncio.sleep(0.01)

        await dg_connection.finish()
        
        print("\nQuality Note Checklist:")
        print("- Was the transcription accurate?")
        print("- Did it handle code-switching?")
        print("- Latency acceptable? (<300ms)")
        
    except Exception as e:
        print(f"Deepgram Error: {e}")

async def main():
    if not settings.DEEPGRAM_API_KEY:
        print("Missing DEEPGRAM_API_KEY in environment.")
        return
        
    base_dir = os.path.join(os.path.dirname(__file__), '..')
    samples_dir = os.path.join(base_dir, 'data', 'samples')
    os.makedirs(samples_dir, exist_ok=True)
    
    scenarios = [
        {
            "scenario_name": "Pure English",
            "file_path": os.path.join(samples_dir, 'sample_en.wav'),
            "model": "nova-2",
            "language": "en-IN"
        },
        {
            "scenario_name": "Hinglish (Hindi-accented English)",
            "file_path": os.path.join(samples_dir, 'sample_hi_en.wav'),
            "model": "nova-2",
            "language": "hi" # Hindi model often handles Hinglish well
        },
        {
            "scenario_name": "Pure Hindi",
            "file_path": os.path.join(samples_dir, 'sample_hi.wav'),
            "model": "nova-2",
            "language": "hi"
        },
        {
            "scenario_name": "Pure Gujarati",
            "file_path": os.path.join(samples_dir, 'sample_gu.wav'),
            "model": "nova-2",
            "language": "gu"
        }
    ]
    
    for s in scenarios:
        await test_stt_scenario(**s)

if __name__ == "__main__":
    asyncio.run(main())
