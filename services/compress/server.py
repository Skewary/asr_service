#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =========================
# 新 压缩 服务端（HTTP）：支持设备/会话命名、返回绝对URL
# =========================
import os
import json
import time
import uuid
import tempfile

import numpy as np
import soundfile as sf
import librosa
from pydub import AudioSegment

import tornado.ioloop
import tornado.web

# -------- 配置 --------
COMPRESS_PORT = int(os.environ.get("COMPRESS_PORT", "5691"))
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATIC_DIR = os.path.abspath(os.environ.get("AUDIO_STATIC_DIR", os.path.join(BASE_DIR, "static_audio")))
os.makedirs(STATIC_DIR, exist_ok=True)

# 可选：强制使用此基地址构造绝对URL（跨设备时推荐设置）
# 例如：http://10.0.0.12:5691
PUBLIC_BASE = os.environ.get("HOST_PUBLIC_BASE", "").rstrip("/")

# -------- 工具 --------
def write_json(handler, data: dict, status=200):
    handler.set_status(status)
    handler.set_header("Content-Type", "application/json; charset=utf-8")
    handler.write(json.dumps(data, ensure_ascii=False))

def safe_filename(suffix: str) -> str:
    return f"{uuid.uuid4().hex}{suffix}"

def librosa_load_any(path: str, target_sr: int = None):
    y, sr = librosa.load(path, sr=target_sr, mono=True)
    maxv = np.max(np.abs(y)) if y.size else 0.0
    if maxv > 0:
        y = (y / maxv).astype(np.float32)
    else:
        y = y.astype(np.float32)
    return y, sr

def save_array_as_wav(y: np.ndarray, sr: int, out_path: str):
    sf.write(out_path, y, sr)

def pydub_load_any(path: str):
    return AudioSegment.from_file(path)

def abs_url(handler: tornado.web.RequestHandler, rel_path: str) -> str:
    if PUBLIC_BASE:
        return f"{PUBLIC_BASE}{rel_path}"
    # 从当前请求推断（协议+Host）
    return f"{handler.request.protocol}://{handler.request.host}{rel_path}"

# -------- 压缩核心 --------
def do_compress(in_file: str, bitrate: str = "16k", target_sr: int = 16000, codec: str = "mp3"):
    t0 = time.time()
    y, _ = librosa_load_any(in_file, target_sr=target_sr)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        tmp_wav_path = tmp_wav.name
    save_array_as_wav(y, target_sr, tmp_wav_path)

    original_size = os.path.getsize(in_file)
    seg = pydub_load_any(tmp_wav_path)

    suffix = ".mp3" if codec.lower() == "mp3" else ".m4a"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_out:
        tmp_out_path = tmp_out.name
    seg.export(tmp_out_path, format=codec, bitrate=bitrate)

    compressed_size = os.path.getsize(tmp_out_path)
    cost = time.time() - t0

    try:
        os.remove(tmp_wav_path)
    except Exception:
        pass

    return tmp_out_path, original_size, compressed_size, cost, target_sr, bitrate, codec

# -------- Handlers --------
class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        write_json(self, {"status": "ok", "stage": "compress"})

class CompressHandler(tornado.web.RequestHandler):
    """
    POST /compress (multipart/form-data)
      - file: 音频文件
      - codec: 默认 mp3
      - bitrate: 默认 16k
      - target_sr: 默认 16000
      - save: 默认 true（落盘并返回 URL）；false 时直接回二进制
      - flowId/deviceId: 可选，用于命名
    """
    async def post(self):
        try:
            files = self.request.files.get("file")
            if not files:
                return write_json(self, {"status": "error", "code": "COMPRESS_INPUT_INVALID", "msg": "缺少文件 file"}, 400)
            finfo = files[0]

            codec = self.get_argument("codec", "mp3")
            bitrate = self.get_argument("bitrate", "16k")
            target_sr = int(self.get_argument("target_sr", "16000"))
            save_flag = self.get_argument("save", "true").lower() != "false"
            flow_id = self.get_argument("flowId", None)
            device_id = self.get_argument("deviceId", None)

            # 写临时输入
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(finfo.filename)[1] or ".wav", delete=False) as tmp_in:
                tmp_in.write(finfo.body)
                in_path = tmp_in.name

            tmp_out_path, original_size, compressed_size, cost, used_sr, used_bitrate, used_codec = do_compress(
                in_path, bitrate=bitrate, target_sr=target_sr, codec=codec
            )
            ratio = (original_size / compressed_size) if compressed_size > 0 else None

            if save_flag:
                # 组织目标路径：可包含 deviceId 子目录 & flowId 文件名
                ext = ".mp3" if used_codec.lower() == "mp3" else ".m4a"
                subdir = STATIC_DIR
                if device_id:
                    subdir = os.path.join(STATIC_DIR, device_id)
                    os.makedirs(subdir, exist_ok=True)
                if flow_id:
                    out_name = f"{flow_id}{ext}"
                else:
                    out_name = safe_filename(ext)

                final_path = os.path.join(subdir, out_name)
                os.replace(tmp_out_path, final_path)

                rel = final_path.replace(STATIC_DIR, "").replace("\\", "/")
                if not rel.startswith("/"):
                    rel = "/" + rel
                url = abs_url(self, f"/static{rel}")

                return write_json(self, {
                    "status": "success",
                    "stage": "compress",
                    "flowId": flow_id,
                    "deviceId": device_id,
                    "codec": used_codec,
                    "bitrate": used_bitrate,
                    "target_sr": used_sr,
                    "original_size_bytes": original_size,
                    "compressed_size_bytes": compressed_size,
                    "compression_ratio": round(ratio, 4) if ratio else None,
                    "processing_time_sec": round(cost, 4),
                    "output_url": url
                })
            else:
                mime = "audio/mpeg" if used_codec.lower() == "mp3" else "audio/aac"
                self.set_header("Content-Type", mime)
                self.set_header("X-Stage", "compress")
                if flow_id: self.set_header("X-Flow-Id", flow_id)
                if device_id: self.set_header("X-Device-Id", device_id)
                with open(tmp_out_path, "rb") as f:
                    self.write(f.read())

        except Exception as e:
            write_json(self, {"status": "error", "code": "COMPRESS_RUNTIME", "msg": str(e)}, 500)

def make_app():
    return tornado.web.Application([
        (r"/health", HealthHandler),
        (r"/compress", CompressHandler),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": STATIC_DIR}),
    ])

if __name__ == "__main__":
    app = make_app()
    app.listen(COMPRESS_PORT)
    print(f"[COMPRESS] HTTP:  http://0.0.0.0:{COMPRESS_PORT}/compress")
    print(f"[COMPRESS] Static Dir: {STATIC_DIR} -> /static (PUBLIC_BASE={PUBLIC_BASE or 'auto'})")
    tornado.ioloop.IOLoop.current().start()

