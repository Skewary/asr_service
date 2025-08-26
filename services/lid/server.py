"""Minimal gRPC LID service using SpeechBrain."""
import asyncio
import io
import logging
import os
import tempfile
import wave
from pathlib import Path

import grpc
from speechbrain.inference.classifiers import EncoderClassifier

from config import LID_PORT, configure_logging

from .protos import lid_pb2, lid_pb2_grpc

# Persist model weights under repository's models directory
MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "lid"

# Load model at module import so it can be shared across requests.
lid_model = EncoderClassifier.from_hparams(
    source="speechbrain/lang-id-commonlanguage_ecapa", savedir=str(MODEL_DIR)
)


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM bytes into a WAV container."""
    with io.BytesIO() as buf:
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()


class LIDServicer(lid_pb2_grpc.LIDServicer):
    async def Detect(self, request: lid_pb2.LIDRequest, context) -> lid_pb2.LIDResponse:
        wav_bytes = pcm_to_wav_bytes(request.pcm, request.sample_rate or 16000)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            out_prob, score, index, language = lid_model.classify_file(tmp_path)
            return lid_pb2.LIDResponse(language=language[0], score=float(score))
        finally:
            os.remove(tmp_path)


def serve() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    server = grpc.aio.server()
    lid_pb2_grpc.add_LIDServicer_to_server(LIDServicer(), server)
    server.add_insecure_port(f"[::]:{LID_PORT}")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(server.start())
    logger.info("LID gRPC server started on port %s", LID_PORT)
    loop.run_until_complete(server.wait_for_termination())


if __name__ == "__main__":
    serve()
