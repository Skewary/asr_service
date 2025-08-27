#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gRPC server exposing the VAD session."""

import asyncio
import logging
import grpc

from config import VAD_PORT, configure_logging

from .vad import make_vad_session, pcm16_bytes_to_float32
from .protos import vad_pb2, vad_pb2_grpc

logger = logging.getLogger(__name__)

class VadServicer(vad_pb2_grpc.VoiceActivityServicer):
    async def Stream(self, request_iterator, context):
        sess = make_vad_session()
        try:
            async for frame in request_iterator:
                if frame.HasField("start"):
                    s = frame.start
                    logger.info("stream start: flow_id=%s sr=%s", s.flow_id, s.sample_rate)
                elif frame.HasField("pcm"):
                    pcm_bytes = frame.pcm.data
                    logger.debug("recv %d bytes", len(pcm_bytes))
                    sess.accept_f32(pcm16_bytes_to_float32(pcm_bytes))
                    out = sess.pop_pcm()
                    if out:
                        logger.debug("emit %d bytes", len(out))
                        yield vad_pb2.ServerFrame(pcm=vad_pb2.Pcm(data=out))
                elif frame.HasField("flush"):
                    logger.info("stream flush")
                    out = sess.flush_pcm()
                    if out:
                        logger.debug("emit %d bytes", len(out))
                        yield vad_pb2.ServerFrame(pcm=vad_pb2.Pcm(data=out))
                    break
        except Exception:
            logger.exception("VAD stream error")
            await context.abort(grpc.StatusCode.INTERNAL, "VAD stream error")
        finally:
            logger.info("stream end")


async def serve() -> None:
    configure_logging()
    server = grpc.aio.server()
    vad_pb2_grpc.add_VoiceActivityServicer_to_server(VadServicer(), server)
    server.add_insecure_port(f"[::]:{VAD_PORT}")
    await server.start()
    logger.info("VAD gRPC server listening on %s", VAD_PORT)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
