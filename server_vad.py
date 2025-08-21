#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =========================
# 新 VAD 服务端（支持弱端：no_reply + 直推下游 Compress）
# =========================
import os
import io
import json
import uuid
import asyncio
from collections import deque
from typing import List, Optional, Tuple

import numpy as np
import soundfile as sf
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.httpclient

import sherpa_onnx  # pip install sherpa-onnx

# -------- 配置 --------
VAD_PORT = int(os.environ.get("VAD_PORT", "9001"))
DEFAULT_SR = int(os.environ.get("VAD_SR", "16000"))
VAD_BUFFER_SEC = float(os.environ.get("VAD_BUFFER_SEC", "60"))
VAD_CHUNK_MS = int(os.environ.get("VAD_CHUNK_MS", "20"))
VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.48"))
VAD_PAD_START_MS = int(os.environ.get("VAD_PAD_START_MS", "100"))
VAD_PAD_END_MS = int(os.environ.get("VAD_PAD_END_MS", "80"))

# 弱端相关：空闲超时自动 flush（采集端可不发送 "flush"、可直接断开）
IDLE_FLUSH_SEC = float(os.environ.get("VAD_IDLE_FLUSH_SEC", "3.0"))

# 下游 Compress HTTP（VAD 直推用）
DEFAULT_COMPRESS_URL = os.environ.get("COMPRESS_URL", "http://127.0.0.1:5691/compress")
COMPRESS_HTTP_TIMEOUT = float(os.environ.get("COMPRESS_HTTP_TIMEOUT", "120"))

# -------- 工具 --------
def pcm16_bytes_to_float32(pcm: bytes) -> np.ndarray:
    if not pcm:
        return np.empty((0,), dtype=np.float32)
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return np.ascontiguousarray(arr)

def make_vad_session(
    model_path: str = os.environ.get("VAD_MODEL", "ten-vad.onnx"),
    sr: int = DEFAULT_SR,
    buffer_sec: float = VAD_BUFFER_SEC,
    chunk_ms: int = VAD_CHUNK_MS,
    threshold: float = VAD_THRESHOLD,
    pad_start_ms: int = VAD_PAD_START_MS,
    pad_end_ms: int = VAD_PAD_END_MS,
):
    cfg = sherpa_onnx.VadModelConfig()
    cfg.sample_rate = sr
    if hasattr(cfg, "ten_vad"):
        cfg.ten_vad.model = model_path
        try:
            if hasattr(cfg.ten_vad, "threshold"):
                cfg.ten_vad.threshold = float(threshold)
        except Exception:
            pass
    else:
        try:
            cfg.model = model_path
        except Exception:
            pass
    return _VadSession(cfg, sr, buffer_sec, chunk_ms, pad_start_ms, pad_end_ms)

class _VadSession:
    def __init__(self, cfg, sr, buffer_sec, chunk_ms, pad_start_ms, pad_end_ms):
        self.vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=buffer_sec)
        self.sr = sr
        self.chunk_ms = chunk_ms
        self.chunk_samples = int(sr * chunk_ms / 1000.0)
        self.pad_start_frames = max(0, int(pad_start_ms // chunk_ms))
        self.pad_end_frames = max(0, int(pad_end_ms // chunk_ms))
        self._pre = deque(maxlen=self.pad_start_frames)
        self._in_seg = False
        self._cur: List[np.ndarray] = []
        self._final: List[np.ndarray] = []
        self._tail_left = 0

    def _drain(self):
        try:
            while not self.vad.empty():
                _ = self.vad.front
                self.vad.pop()
        except Exception:
            pass

    def accept_f32(self, samples: np.ndarray):
        if samples.size == 0: return
        for i in range(0, samples.size, self.chunk_samples):
            c = samples[i:i + self.chunk_samples]
            if c.size == 0: break
            if self.pad_start_frames: self._pre.append(c.copy())
            self.vad.accept_waveform(c)
            speech = bool(self.vad.is_speech_detected())

            if not self._in_seg and speech:
                if self._pre:
                    self._cur.extend(list(self._pre))
                else:
                    self._cur.append(c)
                self._in_seg = True
                self._tail_left = self.pad_end_frames
            elif self._in_seg and speech:
                self._cur.append(c)
                self._tail_left = self.pad_end_frames
            elif self._in_seg and (not speech):
                if self._tail_left > 0:
                    self._cur.append(c)
                    self._tail_left -= 1
                else:
                    self._final.append(np.concatenate(self._cur, axis=0))
                    self._cur = []
                    self._in_seg = False

            self._drain()

    def flush_wav(self) -> Optional[bytes]:
        self.vad.flush()
        self._drain()
        if self._in_seg:
            self._final.append(np.concatenate(self._cur, axis=0))
            self._cur = []
            self._in_seg = False
        if not self._final:
            return None
        out = np.concatenate(self._final, axis=0)
        buf = io.BytesIO()
        sf.write(buf, out, self.sr, format="WAV")
        return buf.getvalue()

# 构建 multipart/form-data（最少依赖）
def build_multipart(fields: dict, files: dict) -> Tuple[bytes, str]:
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    crlf = b"\r\n"
    body = bytearray()

    for k, v in (fields or {}).items():
        body.extend(f"--{boundary}".encode()); body.extend(crlf)
        body.extend(f'Content-Disposition: form-data; name="{k}"'.encode()); body.extend(crlf)
        body.extend(crlf)
        body.extend(str(v).encode()); body.extend(crlf)

    for k, (fname, content, ctype) in (files or {}).items():
        body.extend(f"--{boundary}".encode()); body.extend(crlf)
        body.extend(f'Content-Disposition: form-data; name="{k}"; filename="{fname}"'.encode()); body.extend(crlf)
        body.extend(f"Content-Type: {ctype}".encode()); body.extend(crlf)
        body.extend(crlf)
        body.extend(content); body.extend(crlf)

    body.extend(f"--{boundary}--".encode()); body.extend(crlf)
    return bytes(body), f"multipart/form-data; boundary={boundary}"

# -------- Tornado Handlers --------
class Health(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps({"status": "ok", "stage": "vad"}, ensure_ascii=False))

class VADWebSocket(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin): return True

    def open(self):
        self.flowId = self.get_argument("flowId", default=str(id(self)))
        self.deviceId = self.get_argument("deviceId", default="unknown")
        self.no_reply = self.get_argument("no_reply", "0") in ("1", "true", "True")
        self._flushed = False
        self._idle_handle = None

        self.sess = make_vad_session()
        # 默认直推链路（可被 start 控制帧覆盖）
        self.chain_cfg = {
            "type": "compress-http",
            "url": DEFAULT_COMPRESS_URL,
            "params": {"codec": "mp3", "bitrate": "16k", "target_sr": self.sess.sr, "save": True}
        }

        if not self.no_reply:
            # 仅在需要回复时回 ACK
            try:
                self.write_message({"type": "ack", "stage": "vad", "flowId": self.flowId})
            except Exception:
                pass

        self._schedule_idle_flush()

    def _schedule_idle_flush(self):
        self._cancel_idle_flush()
        self._idle_handle = tornado.ioloop.IOLoop.current().call_later(
            IDLE_FLUSH_SEC, lambda: asyncio.ensure_future(self._flush_and_maybe_chain(reason="idle"))
        )

    def _cancel_idle_flush(self):
        if self._idle_handle is not None:
            try:
                tornado.ioloop.IOLoop.current().remove_timeout(self._idle_handle)
            except Exception:
                pass
            self._idle_handle = None

    async def _push_to_compress(self, wav_bytes: bytes):
        if not self.chain_cfg or self.chain_cfg.get("type") != "compress-http":
            return None
        url = self.chain_cfg.get("url") or DEFAULT_COMPRESS_URL
        params = self.chain_cfg.get("params", {}) or {}
        params.setdefault("save", True)
        params.setdefault("target_sr", self.sess.sr)

        fields = {
            "codec": params.get("codec", "mp3"),
            "bitrate": params.get("bitrate", "16k"),
            "target_sr": params.get("target_sr", self.sess.sr),
            "save": "true" if params.get("save") else "false",
            "flowId": self.flowId,
            "deviceId": self.deviceId,
        }
        files = {"file": ("vad_output.wav", wav_bytes, "audio/wav")}
        body, ctype = build_multipart(fields, files)

        client = tornado.httpclient.AsyncHTTPClient()
        resp = await client.fetch(url, method="POST", headers={"Content-Type": ctype},
                                  body=body, request_timeout=COMPRESS_HTTP_TIMEOUT)
        try:
            return json.loads(resp.body.decode("utf-8", "ignore"))
        except Exception:
            return {"status": "unknown", "len": len(resp.body)}

    async def _flush_and_maybe_chain(self, reason="manual"):
        if self._flushed:
            return
        self._flushed = True
        self._cancel_idle_flush()

        try:
            wav = self.sess.flush_wav()
        except Exception as e:
            if not self.no_reply:
                try:
                    self.write_message({"type": "error", "code": "VAD_RUNTIME", "msg": str(e)})
                except Exception:
                    pass
            print(f"[VAD flush error] flow={self.flowId} reason={reason} err={e}")
            return

        if wav is None:
            if not self.no_reply:
                try:
                    self.write_message({"type": "no_voice"})
                    self.write_message({"type": "end", "stage": "vad", "flowId": self.flowId})
                except Exception:
                    pass
            return

        # 直推下游（弱端无需接收）
        try:
            comp_result = await self._push_to_compress(wav)
        except Exception as e:
            print(f"[VAD chain compress failed] flow={self.flowId} err={e}")
            comp_result = {"status": "error", "code": "CHAIN_COMPRESS_FAILED", "msg": str(e)}

        if not self.no_reply:
            # 回传统结果（便于调试或强端使用）
            try:
                self.write_message({"type": "result", "stage": "vad+compress", "flowId": self.flowId})
                self.write_message(comp_result)
                self.write_message({"type": "end", "stage": "vad", "flowId": self.flowId})
            except Exception:
                pass
        # no_reply 模式下：完全不回写，静默结束

    def on_message(self, message):
        # 任意消息到达都重置空闲计时
        self._schedule_idle_flush()

        if isinstance(message, str):
            try:
                evt = json.loads(message)
                t = str(evt.get("type", "")).lower()
            except Exception:
                t = message.strip().lower()
                evt = {"type": t}

            if t == "start":
                # 允许覆盖链路与 no_reply / deviceId
                self.no_reply = bool(evt.get("no_reply", self.no_reply))
                self.deviceId = evt.get("deviceId", self.deviceId)
                if evt.get("chain"): self.chain_cfg = evt["chain"]
                if not self.no_reply:
                    try:
                        self.write_message({"type": "ack", "stage": "vad", "flowId": self.flowId})
                    except Exception:
                        pass
                return

            if t == "flush":
                asyncio.ensure_future(self._flush_and_maybe_chain(reason="flush"))
                return

            # 其他控制帧忽略
            return

        # 二进制：PCM16
        try:
            self.sess.accept_f32(pcm16_bytes_to_float32(message))
        except Exception as e:
            if not self.no_reply:
                try:
                    self.write_message({"type": "error", "code": "VAD_RUNTIME", "msg": str(e)})
                except Exception:
                    pass

    def on_close(self):
        # 连接关闭也执行 flush（适配弱端直接断开）
        asyncio.ensure_future(self._flush_and_maybe_chain(reason="on_close"))

def make_app():
    return tornado.web.Application([
        (r"/health", Health),
        (r"/ws/vad", VADWebSocket),
    ])

if __name__ == "__main__":
    app = make_app()
    app.listen(VAD_PORT)
    print(f"[VAD] WS: ws://0.0.0.0:{VAD_PORT}/ws/vad  (supports no_reply + server-side push to Compress)")
    tornado.ioloop.IOLoop.current().start()

