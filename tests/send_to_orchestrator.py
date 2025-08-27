#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
send_to_orchestrator.py
将本地 WAV(16k/mono/PCM16) 流式发送到“编排器”的 WebSocket 入口，并打印返回事件。
用法示例：
    python send_to_orchestrator.py --ws ws://127.0.0.1:9000/ws/stream --input input.wav --chunk-ms 30 --realtime
依赖：
    pip install websockets
"""
import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

import websockets


def read_wav_raw(path: Path):
    with wave.open(str(path), "rb") as wf:
        nch = wf.getnchannels()
        sr = wf.getframerate()
        sw = wf.getsampwidth()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
    return raw, sr, nch, sw


def chunk_bytes(raw: bytes, sr: int, nch: int, sampwidth: int, chunk_ms: int):
    # 每片样本数
    samples_per_chunk = int(sr * chunk_ms / 1000)
    # 每片字节数
    bytes_per_chunk = samples_per_chunk * nch * sampwidth
    for i in range(0, len(raw), bytes_per_chunk):
        yield raw[i:i + bytes_per_chunk]


async def receiver(ws, save_binary_prefix: str = "recv"):
    """
    并行接收服务端事件：若为文本帧（JSON），解析打印；若为二进制帧，简单落盘（若检测到WAV头）。
    """
    bin_idx = 0
    try:
        async for msg in ws:
            ts = time.strftime("%H:%M:%S")
            if isinstance(msg, (bytes, bytearray)):
                # 简单二进制处理：若像 WAV（'RIFF' 开头），则保存
                header = bytes(msg[:4])
                if header == b"RIFF":
                    out = f"{save_binary_prefix}_{bin_idx:02d}.wav"
                    Path(out).write_bytes(msg)
                    print(f"[{ts}] [binary] -> saved WAV: {out} ({len(msg)} bytes)")
                else:
                    out = f"{save_binary_prefix}_{bin_idx:02d}.bin"
                    Path(out).write_bytes(msg)
                    print(f"[{ts}] [binary] -> saved BIN: {out} ({len(msg)} bytes)")
                bin_idx += 1
            else:
                # 文本帧：尽量按 JSON 打印关键信息
                try:
                    data = json.loads(msg)
                    etype = data.get("type")
                    if etype in ("ack", "lid", "asr_partial", "asr_final", "record_url", "metrics", "error", "end"):
                        print(f"[{ts}] [{etype}] {json.dumps(data, ensure_ascii=False)}")
                    else:
                        print(f"[{ts}] [event] {json.dumps(data, ensure_ascii=False)}")
                except Exception:
                    print(f"[{ts}] [text] {msg}")
    except websockets.ConnectionClosedOK:
        print("[receiver] connection closed normally")
    except websockets.ConnectionClosedError as e:
        print(f"[receiver] connection closed with error: {e}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", required=True, help="编排器 WebSocket 入口，如 ws://127.0.0.1:9000/ws/stream")
    ap.add_argument("--input", required=True, help="输入 WAV (16k/mono/PCM16)")
    ap.add_argument("--chunk-ms", type=int, default=30, help="分片时长，默认30ms")
    ap.add_argument("--realtime", action="store_true", help="按真实时间节奏发送（每片sleep chunk_ms）")
    ap.add_argument("--stream-name", default="test-stream", help="可选：流名/会话名")
    args = ap.parse_args()

    wav_path = Path(args.input)
    raw, sr, nch, sw = read_wav_raw(wav_path)

    # 基础校验：16k / mono / 16-bit PCM
    if sr != 16000 or nch != 1 or sw != 2:
        raise ValueError(
            f"需要 16k/mono/PCM16，实际为 sr={sr}, nch={nch}, sampwidth={sw}。"
            f"请先转换：ffmpeg -i in.wav -ar 16000 -ac 1 -sample_fmt s16 out.wav"
        )

    # 连接编排器
    async with websockets.connect(args.ws, max_size=None) as ws:
        # 启动接收任务
        recv_task = asyncio.create_task(receiver(ws))

        # 1) 发送 start 控制帧（文本 JSON）
        start_msg = {
            "type": "start",
            "format": "pcm16",  # 也可支持 "opus"（若你的编排器已接入 Opus）
            "sr": sr,
            "channels": nch,
            "stream": args.stream_name,
            "metadata": {
                "client": "send_to_orchestrator.py",
                "ts": int(time.time()),
            },
            # 视你的后端实现，也可增加 no_reply/use_accelerate等自定义字段
        }
        await ws.send(json.dumps(start_msg))
        print(f"[start] -> {start_msg}")

        # 2) 连续发送音频二进制帧
        bytes_sent = 0
        chunk_count = 0
        for b in chunk_bytes(raw, sr, nch, sw, args.chunk_ms):
            if not b:
                continue
            await ws.send(b)  # 二进制帧
            bytes_sent += len(b)
            chunk_count += 1
            if args.realtime:
                await asyncio.sleep(args.chunk_ms / 1000.0)

        print(f"[audio] sent chunks={chunk_count}, bytes={bytes_sent}")

        # 3) 发送 flush（文本帧）
        await ws.send(json.dumps({"type": "flush"}))
        print("[flush] sent")

        # 4) 等待“end”事件或超时后关闭（这里简单等待几秒）
        try:
            await asyncio.wait_for(recv_task, timeout=10.0)
        except asyncio.TimeoutError:
            print("[wait] timeout; closing connection")
        finally:
            await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
