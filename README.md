# 「Codex」实施任务书 —— 单入单出音频流式编排（仅 ASR 链路使用 Opus）

> 目标读者：Codex
> codex自行维护此文件
> 总体原则：**对外一个流式入口+一个事件出口**；**内部可编排**；**除发往 ASR 的链路外全程 PCM**；**ASR 独立机器/集群**。

---
收到！我把两条硬性约束“**不用 WebRTC**、‘**压缩**’= **PCM→Opus**（仅在送 ASR 时发生）”落进整体方案，给 Codex 的落地说明如下。

---

# 0. 关键结论（先说人话）

* **对外入口**：只支持 **WebSocket**（WS），上行必须是 **PCM16/16k/mono**。
* **内部链路**：**全程 PCM** 到 ASR 边界；**仅在“编排器 → ASR”一跳把 PCM 编码成 Opus**（20 ms、16–24 kbps、VBR）。
* **不使用 WebRTC**；不再做 MP3/AAC 这类有损归档。若要留档，建议 **FLAC（无损）** 旁路写存储；与“压缩”一词彻底解耦。

---

# 1. 架构（更新版）

```
Client(WS/PCM16) → Orchestrator/Gateway
   ├─ PCM → VAD (gRPC stream)
   ├─ PCM → Denoise (gRPC stream)
   ├─ PCM → LID (gRPC stream, 前N秒并行 → lang)
   ├─ PCM → (可选) Archive=FLAC（无损留档，HTTP/gRPC，回 record_url）
   └─ PCM → [Opus 编码仅此处] → ASR(独立机器/集群, gRPC stream, 收Opus包)
返回：事件流（ack / lid / asr_partial / asr_final / record_url / metrics / end）
```

> **注意**：之前的 “Compress(mp3)” 服务不再适用；如需留档，改为 **Archive(FLAC)** 旁路服务，不影响 ASR 主链。

---

# 2. 外部协议（固定 PCM）

**WS URL**：`wss://gw.example.com/ws/stream`

* `start` 控制帧（示例）

  ```json
  {
    "type":"start",
    "flowId":"flow-001",
    "audio":{"codec":"pcm_s16le","sr":16000,"channels":1,"chunk_ms":20},
    "return":["lid","asr","record_url"]
  }
  ```
* 二进制：**PCM16** 分片（任意大小，服务端重分片为 20 ms）。
* 结束：`{"type":"flush"}` 或直接断开（编排器自动 flush）。

---

# 3. 内部接口（gRPC 统一；ASR 仅收 Opus）

## 3.1 公共帧（PCM）

```proto
syntax = "proto3";
package common.v1;

message AudioFrame {
  string flow_id = 1;
  int64  seq     = 2;
  int32  sr      = 3;   // 16000
  int32  channels= 4;   // 1
  int32  ns      = 5;   // 20ms → 20_000_000
  int64  pts     = 6;   // 纳秒
  bytes  pcm     = 7;   // PCM16 little-endian
}
```

## 3.2 VAD / Denoise / LID（保持 PCM）

```proto
service Vad     { rpc Stream(stream common.v1.AudioFrame) returns (stream common.v1.AudioFrame); }
service Denoise { rpc Stream(stream common.v1.AudioFrame) returns (stream common.v1.AudioFrame); }

message LidResult { string flow_id=1; string lang=2; float score=3; }
service Lid { rpc Detect(stream common.v1.AudioFrame) returns (LidResult); }  // 前N秒就返回
```

## 3.3 ASR（仅此链路用 Opus）

```proto
syntax = "proto3";
package asr.v1;

message Start {
  string flow_id = 1;
  string codec   = 2;   // 固定 "opus"
  int32  sr      = 3;   // 16000
  int32  channels= 4;   // 1
  int32  frame_ms= 5;   // 20
  int32  bitrate = 6;   // 16000~24000
  bool   vbr     = 7;   // true
  string lang_hint = 8; // LID 或客户 hint，用于路由/词典
}

message OpusPacket { bytes data = 1; int64 seq = 2; }

message ClientFrame {
  oneof payload { Start start = 1; OpusPacket opus = 2; }
}

message AsrEvent {
  string type    = 1;  // "partial" | "final" | "end" | "error"
  string flow_id = 2;
  string text    = 3;
  repeated float ts = 4; // [start, end]
  string lang    = 5;
}

service Recognize {
  rpc Stream(stream ClientFrame) returns (stream AsrEvent);
}
```

---

# 4. 编排器实现要点（只在 ASR 前编码）

### 4.1 PCM → Opus（编排器端）

```python
# pip install opuslib
import numpy as np
from opuslib import Encoder, APPLICATION_AUDIO

SR, CH, FRAME_MS, BITRATE = 16000, 1, 20, 20000
SAMPLES = SR * FRAME_MS // 1000  # 320

enc = Encoder(SR, CH, APPLICATION_AUDIO)
enc.bitrate = BITRATE  # 16k~24k 之间按网络选
# enc.set_option(..., VBR=True)  # 视版本

def pcm_to_opus_packets(pcm_int16: np.ndarray):
    for i in range(0, len(pcm_int16), SAMPLES):
        frame = pcm_int16[i:i+SAMPLES]
        if len(frame) < SAMPLES: break
        yield enc.encode(frame.tobytes(), SAMPLES)
```

### 4.2 Opus → PCM（ASR 端）

```python
from opuslib import Decoder
SR, CH, FRAME_MS = 16000, 1, 20
SAMPLES = SR * FRAME_MS // 1000
dec = Decoder(SR, CH)

def opus_packet_to_pcm(packet: bytes) -> bytes:
    return dec.decode(packet, SAMPLES)  # 320 samples * 2 bytes
```

### 4.3 Pipeline（伪代码）

```python
pcm = rechunk_to_20ms(incoming_pcm)

# 主链：VAD → Denoise → Opus → ASR
for f in pcm:
    f1 = vad.push(f)           # PCM
    f2 = denoise.push(f1)      # PCM
    for pkt in pcm_to_opus_packets(to_int16(f2)):
        asr.send(pkt)          # gRPC → ASR

# 并行：LID（前N秒）→ 决定 asr pool / lang_hint
lid.feed(pcm_first_n_seconds)

# 旁路：Archive(FLAC)
archive.feed(pcm)  # 可选，回 record_url
```

---

# 5. 参数与开关（务必固化）

* `ASR_LINK_CODEC=opus`（仅此值；提供 `pcm` 仅用于故障回退）
* `ASR_LINK_BITRATE=16000..24000`（默认 20000）
* `ASR_LINK_FRAME_MS=20`、`ASR_LINK_VBR=true`
* `PARTIAL_INTERVAL_MS=250`（partial 下行节流）
* `LID_FIRST_N_SECONDS=3`
* `FLUSH_IDLE_SEC=3`
* `ENABLE_ARCHIVE_FLAC=true|false`（如需留档且无损）

---

# 6. 验收与测试（聚焦“只此一跳有损”）

* **协议约束**：外部入口仅接受 `pcm_s16le`；拒绝 `opus/ogg`。
* **链路核验**：抓包/日志字段确认**只有 Orchestrator→ASR** 使用 `Opus`；其余 RPC/WS 皆为 PCM。
* **时延/RTF**：P50 ≤ 300 ms、P95 ≤ 600 ms；ASR 平均 RTF ≤ 0.5。
* **音质**：与“全 PCM 直传 ASR”对比，字准/RTF 无显著退化（≤ 可接受阈值）。
* **回退机制**：Opus 编码失败或 ASR 端解码异常 → 自动切回 `ASR_LINK_CODEC=pcm`（打点告警）。
* **稳定性**：2 小时稳态流；1% 丢包/乱序注入；无崩溃与严重退化。

---

# 7. 注意事项 / 坑点规避

* **只在一处编码**：不要在任何前处理环节（VAD/降噪/LID/留档）做有损编码。
* **帧对齐**：Opus 20 ms → 320 samples；确保 seq/pts 连续，避免 ASR 时间轴漂移。
* **通道**：强制单声道（必要时在入口做 downmix）。
* **音量归一**：若入口幅度异常，入口统一归一化到 \[-1,1] / int16。
* **FEC/NACK**：内部机房链路通常无需；若跨 IDC 且丢包明显，再评估。
* **归档需求**：若客户仍想要“压缩留档”，只能走 **FLAC**（无损）；不要再使用 MP3/AAC。


## 8. 目录结构（建议）

```
repo/
 ├─ orchestrator/
 │   ├─ ws_gateway/           # WS 入站/事件聚合
 │   ├─ pcm_opus/             # 编码器(opuslib) & 回退
 │   ├─ clients/              # gRPC 客户端(VAD/DN/LID/ASR) & HTTP(Compress)
 │   ├─ pipeline/             # 编排与路由
 │   ├─ metrics/              # Prom/OTel
 │   └─ config/
 ├─ services/
 │   ├─ vad/                  # gRPC 适配 (可包现有 sherpa-onnx)
 │   ├─ denoise/              # gRPC 适配
 │   ├─ lid/                  # gRPC
 │   ├─ asr/                  # gRPC 双向流，Opus 解码
 │   └─ compress/             # HTTP/gRPC + 对象存储
 ├─ proto/                    # *.proto（common/asr/vad/dn/lid）
 ├─ deploy/                   # Dockerfile/Helm/K8s
 ├─ tests/
 │   ├─ e2e/                  # 端到端脚本 & 回归集
 │   ├─ perf/                 # 并发/RTF 压测
 │   └─ chaos/                # 故障注入
 └─ docs/
```

---

