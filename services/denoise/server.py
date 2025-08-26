import grpc
from concurrent import futures

from config import DENOISE_PORT

from .protos import denoise_pb2, denoise_pb2_grpc


class DenoiseServicer(denoise_pb2_grpc.DenoiseServicer):
    """Trivial denoise service that echoes input audio."""

    def Clean(self, request: denoise_pb2.Audio, context):  # type: ignore[override]
        return denoise_pb2.Audio(pcm=request.pcm, sample_rate=request.sample_rate)


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    denoise_pb2_grpc.add_DenoiseServicer_to_server(DenoiseServicer(), server)
    server.add_insecure_port(f"[::]:{DENOISE_PORT}")
    print(f"\u2705 Denoise gRPC service started (port={DENOISE_PORT})")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
