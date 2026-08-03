import math
import struct
from agent.audio.codecs import mulaw_to_pcm16, pcm16_to_mulaw, resample_pcm16

def generate_sine_wave_pcm16(frequency: float, duration_sec: float, sample_rate: int) -> bytes:
    """Helper to generate a simple sine wave in 16-bit PCM."""
    num_samples = int(duration_sec * sample_rate)
    pcm_data = bytearray()
    for i in range(num_samples):
        # Generate sine wave
        t = i / sample_rate
        value = int(32767 * math.sin(2 * math.pi * frequency * t))
        # Pack as 16-bit PCM
        pcm_data.extend(struct.pack("<h", value))
    return bytes(pcm_data)

def test_mulaw_pcm_roundtrip():
    # 20ms of audio at 8kHz is 160 samples (Twilio frame size)
    original_pcm = generate_sine_wave_pcm16(440.0, 0.02, 8000)
    
    # PCM -> mulaw
    mulaw = pcm16_to_mulaw(original_pcm)
    assert len(mulaw) == 160, "8kHz mulaw for 20ms should be 160 bytes"
    
    # mulaw -> PCM
    recovered_pcm = mulaw_to_pcm16(mulaw)
    assert len(recovered_pcm) == 320, "8kHz 16-bit PCM for 20ms should be 320 bytes"
    
    # Since mu-law is lossy, we don't expect bit-identical round trip, 
    # but the length should match.
    assert len(original_pcm) == len(recovered_pcm)

def test_resampling():
    original_pcm_8k = generate_sine_wave_pcm16(440.0, 0.02, 8000)
    assert len(original_pcm_8k) == 320
    
    # Resample 8kHz -> 16kHz
    resampled_16k, state = resample_pcm16(original_pcm_8k, 8000, 16000)
    assert 636 <= len(resampled_16k) <= 642, f"Expected ~640 bytes, got {len(resampled_16k)}"
    
    # Resample back 16kHz -> 8kHz
    resampled_8k, _ = resample_pcm16(resampled_16k, 16000, 8000, state)
    assert len(resampled_8k) == 320, "8kHz 16-bit PCM should be back to 320 bytes"
