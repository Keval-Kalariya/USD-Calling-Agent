import os
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

# Load environment variables from .env file
load_dotenv()

# Initialize the ElevenLabs client
api_key = os.getenv("ELEVENLABS_API_KEY")
if not api_key:
    print("Error: ELEVENLABS_API_KEY not found in environment variables.")
    exit(1)

client = ElevenLabs(api_key=api_key)

# Using Rachel (universal multilingual female voice)
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
MODEL_ID = "eleven_multilingual_v2"

# Ensure the output directory exists
output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "samples")
os.makedirs(output_dir, exist_ok=True)

test_cases = {
    "tts_en.wav": "Thank you for calling Ultimate Smile Design.",
    "tts_hi.wav": "धन्यवाद, Ultimate Smile Design में आपका स्वागत है।",
    "tts_gu.wav": "આભાર, Ultimate Smile Design માં આપનું સ્વાગત છે."
}

print("Testing ElevenLabs TTS with streaming support...\n")

for filename, text in test_cases.items():
    file_path = os.path.join(output_dir, filename)
    print(f"Generating: {filename} ({text})")
    
    try:
        # Request audio stream from ElevenLabs
        audio_stream = client.text_to_speech.convert(
            voice_id=VOICE_ID,
            model_id=MODEL_ID,
            text=text,
            output_format="mp3_44100_128"
        )
        
        # Correctly write the streaming chunks to file
        with open(file_path, "wb") as f:
            for chunk in audio_stream:
                if isinstance(chunk, bytes):
                    f.write(chunk)
                    
        print(f"Successfully saved to: {file_path}\n")
        
    except Exception as e:
        print(f"Failed to generate {filename}: {e}\n")

print("All TTS tests completed!")