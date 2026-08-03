import os
import urllib.request
import numpy as np
import onnxruntime as ort
from typing import Any

class SileroVADStream:
    """
    Lightweight wrapper around Silero VAD using ONNX Runtime.
    Avoids a massive PyTorch dependency by running the model directly in ONNX.
    Buffers incoming PCM16 audio into chunks suitable for the model (e.g., 512 samples for 8kHz = 64ms).
    """
    def __init__(self, sample_rate=8000, threshold=0.5, window_size_samples=256):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.window_size_samples = window_size_samples
        
        # Load ONNX model, download if missing
        model_path = os.path.join(os.path.dirname(__file__), "silero_vad.onnx")
        if not os.path.exists(model_path):
            print("[VAD] Downloading Silero VAD ONNX model...")
            url = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
            urllib.request.urlretrieve(url, model_path)
            print("[VAD] Download complete.")
            
        # Initialize ONNX inference session
        self.session = ort.InferenceSession(model_path)
        
        # Internal state for Silero V5/V6 recurrent network
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        
        self.buffer = bytearray()
        self.is_speaking = False
        
    def process_audio(self, pcm_bytes: bytes) -> list[str]:
        """
        Takes raw 16-bit PCM bytes (must match self.sample_rate).
        Yields events: 'speech_started' or 'speech_ended'.
        """
        self.buffer.extend(pcm_bytes)
        
        bytes_per_sample = 2
        chunk_bytes = self.window_size_samples * bytes_per_sample
        
        events = []
        
        # Silero requires fixed size chunks (e.g. 512 samples)
        # We loop until our buffer has less than one chunk left.
        while len(self.buffer) >= chunk_bytes:
            chunk = self.buffer[:chunk_bytes]
            self.buffer = self.buffer[chunk_bytes:]
            
            # Convert PCM16 bytes to float32 numpy array normalized to [-1.0, 1.0]
            audio_data = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            audio_data = np.expand_dims(audio_data, axis=0) # shape (batch_size=1, sequence_length)
            
            # Run inference
            inputs = {
                'input': audio_data,
                'sr': np.array(self.sample_rate, dtype=np.int64),
                'state': self.state
            }
            
            outputs: Any = self.session.run(None, inputs)
            out, self.state = outputs
            prob = out[0][0]
            
            # State machine for speech onset/offset
            if prob > self.threshold and not self.is_speaking:
                self.is_speaking = True
                events.append("speech_started")
            elif prob < (self.threshold - 0.15) and self.is_speaking:
                self.is_speaking = False
                events.append("speech_ended")
                
        return events
