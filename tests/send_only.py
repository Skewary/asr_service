import asyncio, numpy as np, soundfile as sf, grpc
from pathlib import Path

from config import VAD_PORT
from services.vad.protos import vad_pb2, vad_pb2_grpc


async def send_only(target=f"localhost:{VAD_PORT}", wav_path: str | None = None):
    wav_path = wav_path or str(Path(__file__).with_name("test.wav"))
    y, sr = sf.read(wav_path, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()
    step = int(16000 * 0.02) * 2  # 20ms frames

    chan = grpc.aio.insecure_channel(target)
    stub = vad_pb2_grpc.VoiceActivityStub(chan)
    stream = stub.Stream()
    await stream.write(vad_pb2.ClientFrame(start=vad_pb2.Start(flow_id="test", sample_rate=16000)))
    for i in range(0, len(pcm), step):
        await stream.write(vad_pb2.ClientFrame(pcm=vad_pb2.Pcm(data=pcm[i:i+step])))
        while True:
            try:
                resp = await asyncio.wait_for(stream.read(), timeout=0)
                if resp.pcm.data:
                    pass
            except asyncio.TimeoutError:
                break
    await stream.write(vad_pb2.ClientFrame(flush=vad_pb2.Flush()))
    await stream.done_writing()
    async for _ in stream:
        pass
    await chan.close()


if __name__ == "__main__":
    asyncio.run(send_only())
