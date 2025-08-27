"""gRPC client for denoising service."""

import logging
import grpc

from config import DENOISE_PORT
from services.denoise.protos import denoise_pb2, denoise_pb2_grpc  # type: ignore

logger = logging.getLogger(__name__)


class DenoiseClient:
    def __init__(self, target: str = f"localhost:{DENOISE_PORT}") -> None:
        self.channel = grpc.aio.insecure_channel(target)
        self.stub = denoise_pb2_grpc.DenoiseStub(self.channel)

    async def send(self, pcm_bytes: bytes) -> bytes:
        logger.debug("denoise send %d bytes", len(pcm_bytes))
        request = denoise_pb2.Audio(pcm=pcm_bytes, sample_rate=16000)
        response = await self.stub.Clean(request)
        logger.debug("denoise recv %d bytes", len(response.pcm))
        return response.pcm

    def close(self) -> None:
        self.channel.close()
