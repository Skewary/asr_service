import asyncio, json, websockets, numpy as np, soundfile as sf

async def send_only(ws_url, wav_path, flow="f001", dev="devA"):
    y, sr = sf.read(wav_path, dtype="float32")
    if y.ndim>1: y = y.mean(axis=1)
    pcm = (np.clip(y,-1,1)*32767).astype(np.int16).tobytes()
    step = int(16000*0.02)*2  # 20ms

    # 连接后发 start(no_reply) -> 仅上行音频 -> 直接关闭
    async with websockets.connect(f"{ws_url}?flowId={flow}&deviceId={dev}&no_reply=1") as w:
        await w.send(json.dumps({"type":"start","no_reply":True}))
        for i in range(0,len(pcm),step):
            await w.send(pcm[i:i+step])
        # 甚至可以不发 'flush'，让服务端在 on_close() 自动 flush
        # await w.send("flush")
    # 直接退出，不读任何返回

asyncio.run(send_only("ws://localhost:9001/ws/vad", "test.wav"))

