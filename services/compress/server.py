import logging
import grpc
from concurrent import futures
import numpy as np
from opuslib import Encoder, APPLICATION_AUDIO

from config import COMPRESS_PORT, configure_logging

from .protos import compress_pb2, compress_pb2_grpc

logger = logging.getLogger(__name__)


class CompressServicer(compress_pb2_grpc.CompressServicer):
    def __init__(self, sample_rate: int = 16000, frame_ms: int = 20, bitrate: int = 20000):
        self.samples = sample_rate * frame_ms // 1000
        self.encoder = Encoder(sample_rate, 1, APPLICATION_AUDIO)
        self.encoder.bitrate = bitrate

    def Encode(self, request: compress_pb2.PCM, context) -> compress_pb2.Opus:  # type: ignore
        try:
            pcm = np.frombuffer(request.data, dtype=np.int16)
            if len(pcm) < self.samples:
                return compress_pb2.Opus(data=b"")
            pkt = self.encoder.encode(pcm[: self.samples].tobytes(), self.samples)
            return compress_pb2.Opus(data=pkt)
        except Exception:
            logger.exception("Compress encoding error")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Compress encoding error")
            return compress_pb2.Opus(data=b"")


def serve() -> None:
    configure_logging()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    compress_pb2_grpc.add_CompressServicer_to_server(CompressServicer(), server)
    server.add_insecure_port(f"[::]:{COMPRESS_PORT}")
    logger.info("Compress gRPC service started (port=%s)", COMPRESS_PORT)
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
