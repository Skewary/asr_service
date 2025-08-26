"""gRPC client for streaming ASR service."""

import asyncio
import grpc

from config import ASR_PORT
from ..protos import asr_pb2, asr_pb2_grpc


class AsrClient:
    def __init__(self, flow_id: str, target: str = f"asr:{ASR_PORT}") -> None:
        self.flow_id = flow_id
        self.channel = grpc.aio.insecure_channel(target)
        self.stub = asr_pb2_grpc.RecognizeStub(self.channel)
        self.stream = None

    async def send(self, opus_pkt: bytes, language: str | None = None) -> None:
        if not self.stream:
            self.stream = self.stub.Stream()
            start = asr_pb2.Start(flow_id=self.flow_id, codec="opus", sr=16000, language=language)
            await self.stream.write(asr_pb2.ClientFrame(start=start))
        await self.stream.write(
            asr_pb2.ClientFrame(opus=asr_pb2.OpusPacket(data=opus_pkt))
        )

    async def flush(self) -> None:
        if self.stream:
            await self.stream.done_writing()
            async for evt in self.stream:
                # In real implementation the result would be forwarded.
                print("ASR result:", evt)

    def close(self) -> None:
        if self.channel:
            self.channel.close()
