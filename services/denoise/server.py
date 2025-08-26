import logging
import grpc
from concurrent import futures

from config import DENOISE_PORT, configure_logging

from .protos import denoise_pb2, denoise_pb2_grpc


class DenoiseServicer(denoise_pb2_grpc.DenoiseServicer):
    """Trivial denoise service that echoes input audio."""

    def Clean(self, request: denoise_pb2.Audio, context):  # type: ignore[override]
        return denoise_pb2.Audio(pcm=request.pcm, sample_rate=request.sample_rate)


def serve() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    denoise_pb2_grpc.add_DenoiseServicer_to_server(DenoiseServicer(), server)
    server.add_insecure_port(f"[::]:{DENOISE_PORT}")
    logger.info("Denoise gRPC service started (port=%s)", DENOISE_PORT)
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
