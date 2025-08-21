"""Opus encoding utilities."""

from __future__ import annotations

import numpy as np
from opuslib import Encoder, APPLICATION_AUDIO


class PcmToOpus:
    """Incrementally encode PCM16 audio into Opus packets."""

    def __init__(self, sr: int = 16000, frame_ms: int = 20, bitrate: int = 20000) -> None:
        self.sr = sr
        self.frame_ms = frame_ms
        self.bitrate = bitrate
        self.samples = sr * frame_ms // 1000
        self.enc = Encoder(sr, 1, APPLICATION_AUDIO)
        self.enc.bitrate = bitrate

    def encode(self, pcm_bytes: bytes):
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        for i in range(0, len(pcm), self.samples):
            frame = pcm[i : i + self.samples]
            if len(frame) < self.samples:
                break
            yield self.enc.encode(frame.tobytes(), self.samples)
