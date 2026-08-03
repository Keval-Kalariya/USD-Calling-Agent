"""
Audio codec utilities for μ-law <-> PCM16 conversion and resampling.

This module uses `audioop` (provided by the `audioop-lts` package in Python 3.13+)
for high-performance, C-level audio conversions without heavyweight dependencies 
like scipy or numpy.
"""
import audioop
from typing import Tuple, Optional

def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """
    Converts μ-law audio to 16-bit PCM.
    
    Args:
        mulaw_bytes (bytes): Bytes containing μ-law audio.
        
    Returns:
        bytes: 16-bit PCM audio.
    """
    return audioop.ulaw2lin(mulaw_bytes, 2)

def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """
    Converts 16-bit PCM audio to μ-law.
    
    Args:
        pcm_bytes (bytes): Bytes containing 16-bit PCM audio.
        
    Returns:
        bytes: μ-law audio.
    """
    return audioop.lin2ulaw(pcm_bytes, 2)

def resample_pcm16(
    pcm_bytes: bytes, 
    in_rate: int, 
    out_rate: int, 
    state: Optional[tuple] = None
) -> Tuple[bytes, Optional[tuple]]:
    """
    Resamples 16-bit PCM audio.
    
    Args:
        pcm_bytes (bytes): 16-bit PCM audio.
        in_rate (int): Original sample rate (e.g., 8000).
        out_rate (int): Target sample rate (e.g., 16000).
        state (tuple, optional): State from a previous call for continuous streaming.
        
    Returns:
        Tuple[bytes, tuple]: Resampled audio bytes and the new state for the next chunk.
    """
    if in_rate == out_rate:
        return pcm_bytes, state
    
    # audioop.ratecv(fragment, width, nchannels, inrate, outrate, state[, weightA[, weightB]])
    return audioop.ratecv(pcm_bytes, 2, 1, in_rate, out_rate, state)
