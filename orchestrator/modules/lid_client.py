"""gRPC client for language identification."""

import grpc
from services.lid.protos import lid_pb2, lid_pb2_grpc  # type: ignore


class LidClient:
    def __init__(self, flow_id: str, target: str = "lid:50052") -> None:
        self.flow_id = flow_id
        self.channel = grpc.aio.insecure_channel(target)
        self.stub = lid_pb2_grpc.LIDStub(self.channel)
        self.buffer = bytearray()

    def feed(self, pcm_bytes: bytes) -> None:
        """Collect PCM for language identification."""
        self.buffer.extend(pcm_bytes)

    async def flush(self) -> str | None:
        """Send accumulated audio and return detected language."""
        if not self.buffer:
            return None
        request = lid_pb2.LIDRequest(pcm=bytes(self.buffer), sample_rate=16000)
        resp = await self.stub.Detect(request)
        self.buffer.clear()
        return resp.language

    def close(self) -> None:
        self.channel.close()
