import logging
import grpc
from concurrent import futures

from config import DENOISE_PORT, configure_logging

from .protos import denoise_pb2, denoise_pb2_grpc

logger = logging.getLogger(__name__)


class DenoiseServicer(denoise_pb2_grpc.DenoiseServicer):
    """Trivial denoise service that echoes input audio."""

    def Clean(self, request: denoise_pb2.Audio, context):  # type: ignore[override]
        try:
            pcm_in = request.pcm
            logger.debug("recv %d bytes", len(pcm_in))
            resp = denoise_pb2.Audio(pcm=pcm_in, sample_rate=request.sample_rate)
            logger.debug("emit %d bytes", len(resp.pcm))
            return resp
        except Exception:
            logger.exception("Denoise clean error")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Denoise clean error")
            return denoise_pb2.Audio(pcm=b"", sample_rate=request.sample_rate)


def serve() -> None:
    configure_logging()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    denoise_pb2_grpc.add_DenoiseServicer_to_server(DenoiseServicer(), server)
    server.add_insecure_port(f"[::]:{DENOISE_PORT}")
    logger.info("Denoise gRPC service started (port=%s)", DENOISE_PORT)
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
