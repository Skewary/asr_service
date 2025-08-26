#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gRPC server exposing the VAD session."""

import asyncio
import grpc

from config import VAD_PORT

from .vad import make_vad_session, pcm16_bytes_to_float32
from .protos import vad_pb2, vad_pb2_grpc


class VadServicer(vad_pb2_grpc.VoiceActivityServicer):
    async def Stream(self, request_iterator, context):
        sess = make_vad_session()
        async for frame in request_iterator:
            if frame.HasField("pcm"):
                sess.accept_f32(pcm16_bytes_to_float32(frame.pcm.data))
                out = sess.pop_pcm()
                if out:
                    yield vad_pb2.ServerFrame(pcm=vad_pb2.Pcm(data=out))
            elif frame.HasField("flush"):
                out = sess.flush_pcm()
                if out:
                    yield vad_pb2.ServerFrame(pcm=vad_pb2.Pcm(data=out))
                break


async def serve() -> None:
    server = grpc.aio.server()
    vad_pb2_grpc.add_VoiceActivityServicer_to_server(VadServicer(), server)
    server.add_insecure_port(f"[::]:{VAD_PORT}")
    await server.start()
    print(f"VAD gRPC server listening on {VAD_PORT}")
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
