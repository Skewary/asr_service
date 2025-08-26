"""gRPC client for PCM→Opus compression."""

import asyncio
import numpy as np
import grpc

from config import COMPRESS_PORT
from services.compress.protos import compress_pb2, compress_pb2_grpc  # type: ignore


class CompressClient:
    def __init__(self, target: str = f"localhost:{COMPRESS_PORT}") -> None:
        self.channel = grpc.aio.insecure_channel(target)
        self.stub = compress_pb2_grpc.CompressStub(self.channel)
        self.frame_samples = 16000 * 20 // 1000

    async def encode(self, pcm_bytes: bytes) -> list[bytes]:
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        packets: list[bytes] = []
        for i in range(0, len(pcm), self.frame_samples):
            frame = pcm[i : i + self.frame_samples]
            if len(frame) < self.frame_samples:
                break
            req = compress_pb2.PCM(data=frame.tobytes())
            resp = await self.stub.Encode(req)
            packets.append(resp.data)
        return packets

    def close(self) -> None:
        self.channel.close()


if __name__ == "__main__":
    async def _test():
        import os
        cc = CompressClient()
        pcm = os.urandom(320 * 2)  # dummy 20ms
        out = await cc.encode(pcm)
        print("encoded packets", len(out))
        cc.close()
    asyncio.run(_test())
