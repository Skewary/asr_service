"""gRPC client for the VAD service."""

import asyncio
import grpc

from services.vad.protos import vad_pb2, vad_pb2_grpc


class VadClient:
    def __init__(self, target: str = "localhost:9001", flow_id: str = "default"):
        self.flow_id = flow_id
        self.channel = grpc.aio.insecure_channel(target)
        self.stub = vad_pb2_grpc.VoiceActivityStub(self.channel)
        self.stream = None

    async def _ensure_stream(self) -> None:
        if self.stream is None:
            self.stream = self.stub.Stream()
            start = vad_pb2.Start(flow_id=self.flow_id, sample_rate=16000)
            await self.stream.write(vad_pb2.ClientFrame(start=start))

    async def send(self, pcm_bytes: bytes) -> bytes:
        await self._ensure_stream()
        await self.stream.write(vad_pb2.ClientFrame(pcm=vad_pb2.Pcm(data=pcm_bytes)))
        out = b""
        while True:
            try:
                resp = await asyncio.wait_for(self.stream.read(), timeout=0)
                out += resp.pcm.data
            except asyncio.TimeoutError:
                break
        return out

    async def flush(self) -> bytes:
        if not self.stream:
            return b""
        await self.stream.write(vad_pb2.ClientFrame(flush=vad_pb2.Flush()))
        await self.stream.done_writing()
        out = b""
        async for resp in self.stream:
            out += resp.pcm.data
        self.stream = None
        return out
