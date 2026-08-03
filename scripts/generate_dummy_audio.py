import wave
import struct
import math
import os

def generate_dummy_audio():
    # Target the backend/static folder so FastAPI can serve it
    static_dir = os.path.join(os.path.dirname(__file__), "..", "backend", "static")
    os.makedirs(static_dir, exist_ok=True)
    file_path = os.path.join(static_dir, "welcome.wav")
    
    sample_rate = 8000 # 8kHz telephony standard
    duration_seconds = 1
    num_samples = sample_rate * duration_seconds

    print("Generating standard uncompressed dummy audio...")
    
    with wave.open(file_path, 'wb') as wf:
        wf.setnchannels(1)       # Mono
        wf.setsampwidth(2)       # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.setcomptype('NONE', 'not compressed')
        
        for i in range(num_samples):
            value = int(16000.0 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            data = struct.pack('<h', value)
            wf.writeframesraw(data)
            
    print(f"Success! Audio saved to: {file_path}")

if __name__ == '__main__':
    generate_dummy_audio()