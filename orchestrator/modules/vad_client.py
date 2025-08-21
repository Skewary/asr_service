"""Local VAD client that wraps the shared sherpa-onnx session."""

from services.vad.vad import make_vad_session, pcm16_bytes_to_float32


class VadClient:
    """Simple in-process VAD using sherpa-onnx."""

    def __init__(self):
        self.sess = make_vad_session()

    async def send(self, pcm_bytes: bytes) -> bytes:
        self.sess.accept_f32(pcm16_bytes_to_float32(pcm_bytes))
        return self.sess.pop_pcm()

    async def flush(self) -> bytes:
        return self.sess.flush_pcm()
