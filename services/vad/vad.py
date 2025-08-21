import os
import io
from collections import deque
from typing import List, Optional

import numpy as np
import soundfile as sf
import sherpa_onnx  # pip install sherpa-onnx

# -------- VAD 配置 --------
DEFAULT_SR = int(os.environ.get("VAD_SR", "16000"))
VAD_BUFFER_SEC = float(os.environ.get("VAD_BUFFER_SEC", "60"))
VAD_CHUNK_MS = int(os.environ.get("VAD_CHUNK_MS", "20"))
VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.48"))
VAD_PAD_START_MS = int(os.environ.get("VAD_PAD_START_MS", "100"))
VAD_PAD_END_MS = int(os.environ.get("VAD_PAD_END_MS", "80"))


def _default_model_path() -> str:
    return os.environ.get(
        "VAD_MODEL",
        os.path.join(os.path.dirname(__file__), "..", "..", "models", "ten-vad.onnx"),
    )


def pcm16_bytes_to_float32(pcm: bytes) -> np.ndarray:
    """Convert PCM16 bytes to float32 numpy array."""
    if not pcm:
        return np.empty((0,), dtype=np.float32)
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return np.ascontiguousarray(arr)


def make_vad_session(
    model_path: Optional[str] = None,
    sr: int = DEFAULT_SR,
    buffer_sec: float = VAD_BUFFER_SEC,
    chunk_ms: int = VAD_CHUNK_MS,
    threshold: float = VAD_THRESHOLD,
    pad_start_ms: int = VAD_PAD_START_MS,
    pad_end_ms: int = VAD_PAD_END_MS,
):
    """Create a VAD session based on sherpa-onnx."""
    model_path = model_path or _default_model_path()
    cfg = sherpa_onnx.VadModelConfig()
    cfg.sample_rate = sr
    if hasattr(cfg, "ten_vad"):
        cfg.ten_vad.model = model_path
        try:
            if hasattr(cfg.ten_vad, "threshold"):
                cfg.ten_vad.threshold = float(threshold)
        except Exception:
            pass
    else:
        try:
            cfg.model = model_path
        except Exception:
            pass
    return VadSession(cfg, sr, buffer_sec, chunk_ms, pad_start_ms, pad_end_ms)


class VadSession:
    """Wrap sherpa-onnx voice activity detection."""

    def __init__(self, cfg, sr, buffer_sec, chunk_ms, pad_start_ms, pad_end_ms):
        self.vad = sherpa_onnx.VoiceActivityDetector(
            cfg, buffer_size_in_seconds=buffer_sec
        )
        self.sr = sr
        self.chunk_ms = chunk_ms
        self.chunk_samples = int(sr * chunk_ms / 1000.0)
        self.pad_start_frames = max(0, int(pad_start_ms // chunk_ms))
        self.pad_end_frames = max(0, int(pad_end_ms // chunk_ms))
        self._pre = deque(maxlen=self.pad_start_frames)
        self._in_seg = False
        self._cur: List[np.ndarray] = []
        self._final: List[np.ndarray] = []
        self._tail_left = 0

    def _drain(self):
        try:
            while not self.vad.empty():
                _ = self.vad.front
                self.vad.pop()
        except Exception:
            pass

    def accept_f32(self, samples: np.ndarray):
        if samples.size == 0:
            return
        for i in range(0, samples.size, self.chunk_samples):
            c = samples[i : i + self.chunk_samples]
            if c.size == 0:
                break
            if self.pad_start_frames:
                self._pre.append(c.copy())
            self.vad.accept_waveform(c)
            speech = bool(self.vad.is_speech_detected())

            if not self._in_seg and speech:
                if self._pre:
                    self._cur.extend(list(self._pre))
                else:
                    self._cur.append(c)
                self._in_seg = True
                self._tail_left = self.pad_end_frames
            elif self._in_seg and speech:
                self._cur.append(c)
                self._tail_left = self.pad_end_frames
            elif self._in_seg and (not speech):
                if self._tail_left > 0:
                    self._cur.append(c)
                    self._tail_left -= 1
                else:
                    self._final.append(np.concatenate(self._cur, axis=0))
                    self._cur = []
                    self._in_seg = False

            self._drain()

    def pop_pcm(self) -> bytes:
        """Return and clear buffered speech segments as PCM16 bytes."""
        if not self._final:
            return b""
        out = np.concatenate(self._final, axis=0)
        self._final = []
        return (out * 32768.0).astype(np.int16).tobytes()

    def flush_pcm(self) -> bytes:
        """Flush remaining audio and return PCM16 bytes."""
        self.vad.flush()
        self._drain()
        if self._in_seg:
            self._final.append(np.concatenate(self._cur, axis=0))
            self._cur = []
            self._in_seg = False
        return self.pop_pcm()

    def flush_wav(self) -> Optional[bytes]:
        """Flush remaining audio and return a WAV file (for server-side use)."""
        pcm = self.flush_pcm()
        if not pcm:
            return None
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        buf = io.BytesIO()
        sf.write(buf, arr, self.sr, format="WAV")
        return buf.getvalue()