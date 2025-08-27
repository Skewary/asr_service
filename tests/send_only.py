"""Send a PCM WAV to the VAD service and log responses/errors."""

import asyncio, logging
import numpy as np, soundfile as sf, grpc
from pathlib import Path

from config import VAD_PORT
from services.vad.protos import vad_pb2, vad_pb2_grpc


async def send_only(target=f"localhost:{VAD_PORT}", wav_path: str | None = None):
    logging.basicConfig(level="INFO")
    logger = logging.getLogger(__name__)
    wav_path = wav_path or str(Path(__file__).with_name("test.wav"))
    try:
        y, sr = sf.read(wav_path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        logger.info("loaded %s (%d samples @ %d Hz)", wav_path, y.size, sr)
        pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()
        step = int(16000 * 0.02) * 2  # 20ms frames

        chan = grpc.aio.insecure_channel(target)
        try:
            await asyncio.wait_for(chan.channel_ready(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error("gRPC channel %s not ready", target)
            return
        stub = vad_pb2_grpc.VoiceActivityStub(chan)
        stream = stub.Stream()

        async def read_responses():
            try:
                while True:
                    resp = await asyncio.wait_for(stream.read(), timeout=5.0)
                    if resp is grpc.aio.EOF:
                        break
                    if resp.pcm.data:
                        logger.info("received %d bytes", len(resp.pcm.data))
            except asyncio.TimeoutError:
                logger.error("timeout waiting for server response")
            except grpc.RpcError as e:
                logger.error("stream read error: %s", e)

        reader = asyncio.create_task(read_responses())

        await stream.write(
            vad_pb2.ClientFrame(start=vad_pb2.Start(flow_id="test", sample_rate=16000))
        )
        for i in range(0, len(pcm), step):
            chunk = pcm[i : i + step]
            logger.debug("sending %d bytes", len(chunk))
            await stream.write(vad_pb2.ClientFrame(pcm=vad_pb2.Pcm(data=chunk)))

        await stream.write(vad_pb2.ClientFrame(flush=vad_pb2.Flush()))
        await stream.done_writing()
        await reader
        await chan.close()
    except grpc.RpcError as e:
        logger.error("gRPC error: %s", e)
    except Exception:
        logger.exception("send_only failed")


if __name__ == "__main__":
    asyncio.run(send_only())
