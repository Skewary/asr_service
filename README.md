# 「Codex」实施任务书 —— 单入单出音频流式编排（仅 ASR 链路使用 Opus）

> 目标读者：Codex
> codex自行维护此文件
> 总体原则：**对外一个流式入口+一个事件出口**；**内部可编排**；**除发往 ASR 的链路外全程 PCM**；**ASR 独立机器/集群**。

---

## 1. 范围与目标

**必须实现**

1. 对外 **WebSocket** 流式入口：上行 **PCM16/16k/mono**，下行统一事件流（`ack/lid/asr_partial/asr_final/record_url/metrics/end/error`）。
2. Orchestrator（网关+编排+汇聚）：

   * 入口解码/重分片、抖动缓冲、会话管理、背压。
   * 内部调用 **VAD → Denoise →（旁路 Compress） → LID → ASR**。
   * **仅在发往 ASR 时将 PCM→Opus(20ms, 16–24kbps, VBR)**，ASR 端解回 PCM 再识别。
   * 事件聚合后单通道回下行。
3. **ASR 独立机器/集群**（gRPC 双向流），支持按语言/域路由。
4. Compress 旁路归档：落对象存储（或本地静态目录），返回绝对 URL。
5. 可观测性与可靠性：Prometheus 指标、OTel Trace、健康探针、熔断/降级、幂等、重试。

**不在本期**

* 前端 UI/SDK、跨地域多活、计费。

---

## 2. 性能 & SLA（验收口径）

* 端到端互动时延（首个 partial）：P50 ≤ **300ms**，P95 ≤ **600ms**（取决 ASR 模型/硬件）。
* ASR 平均 RTF ≤ **0.5**。
* Orchestrator 单实例承载 ≥ **500** 活跃会话（可水平扩展）。
* 可用性 ≥ **99.9%**（月）。
* 只有 **Orchestrator→ASR** 使用 Opus；其余链路 PCM（抓包/日志可核验）。

---

## 3. 顶层架构

```
Client(WS/PCM16) → Orchestrator/Gateway
   ├─ PCM16 → VAD (gRPC stream)
   ├─ PCM16 → Denoise (gRPC stream)
   ├─ PCM16 → LID (gRPC stream, 前N秒并行，回 lang)
   ├─ PCM16 → Compress (旁路归档，回 record_url)
   └─ PCM→Opus(20ms,VBR,16–24kbps) → ASR(独立机/集群,gRPC stream)
返回：事件流（ack/lid/asr_partial/asr_final/record_url/metrics/end）
```

---

## 4. 对外协议（WebSocket）

**URL**：`wss://gw.example.com/ws/stream`

### 4.1 上行

* `start` 控制帧（JSON）

```json
{
  "type": "start",
  "flowId": "string",
  "audio": {"codec":"pcm_s16le","sr":16000,"channels":1,"chunk_ms":20},
  "return": ["lid","asr","record_url"],
  "hints": {"domain":"default","user_lang_pref":"auto"},
  "auth": {"token":"<JWT>"}
}
```

* 二进制音频：PCM16，建议 20ms 分片（可变长，服务端重分片）
* 结束：`{"type":"flush"}` 或直接断开（服务端自动 flush）

### 4.2 下行事件（JSON 文本帧）

* `ack` / `lid` / `asr_partial` / `asr_final` / `record_url` / `metrics` / `end` / `error`
* 频控：`asr_partial` 至多每 **200–300ms** 一条

---

## 5. 内部接口（gRPC 统一）

### 5.1 公共消息（PCM 帧）

```proto
syntax = "proto3";
package common.v1;

message AudioFrame {
  string flow_id = 1;
  int64  seq     = 2;
  int32  sr      = 3;   // 16000
  int32  channels= 4;   // 1
  int32  ns      = 5;   // 本帧时长(纳秒)，例：20ms=20_000_000
  int64  pts     = 6;   // 会话内时间戳(纳秒)
  bytes  pcm     = 7;   // PCM16 原始字节
}
```

### 5.2 ASR（仅此链路用 Opus）

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
  string lang_hint = 8; // 可选：路由/模型热词
}

message OpusPacket { bytes data = 1; int64 seq = 2; }

message ClientFrame {
  oneof payload { Start start = 1; OpusPacket opus = 2; }
}

message AsrEvent {
  string type   = 1;  // "partial"|"final"|"end"|"error"
  string flow_id= 2;
  string text   = 3;
  repeated float ts = 4; // [start,end]
  string lang   = 5;
}

service Recognize {
  rpc Stream(stream ClientFrame) returns (stream AsrEvent);
}
```

### 5.3 VAD / Denoise / LID（PCM）

```proto
service Vad { rpc Stream(stream common.v1.AudioFrame) returns (stream common.v1.AudioFrame); }
service Denoise { rpc Stream(stream common.v1.AudioFrame) returns (stream common.v1.AudioFrame); }

message LidResult { string flow_id=1; string lang=2; float score=3; }
service Lid { rpc Detect(stream common.v1.AudioFrame) returns (LidResult); }
```

### 5.4 Compress（旁路）

* HTTP `POST /compress` (multipart) 或 gRPC 流；返回 `record_url`（绝对 URL）。

---

## 6. 关键实现要点

* **Orchestrator**

  * WS 会话管理，抖动缓冲，静音超时 `FLUSH_IDLE_SEC`（默认 3s）。
  * 背压：下行 partial 节流、上行帧滑窗、gRPC 背压配合。
  * **PCM→Opus**：`opuslib` 单包编码（20ms），参数可配；失败自动回退 PCM 直传。
  * 路由：LID 前 N 秒早返回（默认 2–3s）→ 选择 `asr.*` 池（zh/en/multi…）。
  * 事件聚合：按时间线合并 LID、ASR、Compress，统一回下行。
  * 幂等：`flowId` 贯穿；对象存储使用预签名 URL/可重复写策略。

* **ASR（独立机/集群）**

  * gRPC 双向流；收到 `Start(codec=opus)` 后逐包解码→PCM→前端/模型。
  * 并发上限、队列、冷启动预热；`/healthz` & Prom 指标。
  * 多模型池：按语言/域路由；热词/词典注入。

* **VAD / Denoise / LID**

  * 统一 gRPC 适配层（若短期沿用现有 HTTP/WS，可在 Orchestrator 边车转换）。
  * 参数化：`threshold/pad_*_ms/chunk_ms`，`NR` 算法可切换。

* **Compress**

  * 落对象存储（MinIO/S3），返回绝对 URL（跨机可访问）。
  * 可选实时转码输出（后续）。

---

## 7. 配置与开关

| 键                                  | 说明              | 默认          |
| ---------------------------------- | --------------- | ----------- |
| `ASR_LINK_CODEC`                   | `opus` \| `pcm` | `opus`      |
| `ASR_LINK_BITRATE`                 | Opus 比特率        | `20000`     |
| `ASR_LINK_FRAME_MS`                | Opus 帧长         | `20`        |
| `PARTIAL_INTERVAL_MS`              | partial 下行最小间隔  | `250`       |
| `FLUSH_IDLE_SEC`                   | 无帧自动 flush      | `3`         |
| `LID_FIRST_N_SECONDS`              | LID 使用的前置时长     | `3`         |
| `ENABLE_DENOISE`/`ENABLE_COMPRESS` | 模块开关            | `true/true` |
| `PUBLIC_BASE`                      | 压缩回绝对 URL 前缀    | 必配(生产)      |

---

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

## 9. 监控与日志

* **Metrics（Prometheus）**

  * `orchestrator_active_sessions`, `ingress_bytes_total`, `egress_events_total`
  * `asr_rtf`, `asr_latency_ms_bucket`, `asr_inflight_sessions`
  * `vad_latency_ms`, `dn_latency_ms`, `lid_latency_ms`, `compress_latency_ms`
  * `pcm_to_opus_fail_total`（回退触发）
* **Tracing（OTel）**：`flowId`/`traceId` 贯穿；关键 span：WS 接入、每阶段处理、ASR roundtrip。
* **日志字段**：`ts, flowId, stage, seq, sr, ns, bytes_in/out, lang, model, latency_ms, err_code`

---

## 10. 测试计划（DoD）

* **契约测试**：WS 消息/事件 schema 校验；gRPC proto 兼容性。
* **功能**：

  * LID 早返回；ASR partial/final 时序正确；record\_url 可访问。
  * 仅 ASR 链路用 Opus（抓包/日志字段 `asr_link_codec`）。
* **性能**：并发 200/500/1000；记录 RTF/延迟/CPU/内存。
* **稳定性**：2 小时稳态；1% 丢包/乱序；故障注入（ASR 池宕机/超时）。
* **安全**：TLS/mTLS，JWT 校验，速率限制。
* **回退**：Opus 编码失败→PCM 直传；ASR Busy→仅录音+稍后转写（返回 record\_url）。

---

## 11. 里程碑

* **M1（周1–2）**：

  * WS 入口最小可用；Orchestrator 直通 VAD→Compress；事件流骨架。
  * 交付：E2E 最小链路与健康检查、basic metrics。
* **M2（周3–4）**：

  * LID 并行并路由 ASR（先 PCM 直传）；监控与日志完善。
  * 交付：事件聚合完整、SLO 面板。
* **M3（周5–6）**：

  * 引入 Opus（仅 ASR 链路），回退机制；ASR 独立机部署/容量压测。
  * 交付：RTF/延迟达标报告。
* **M4（周7–8）**：

  * Compress 对象存储、灰度与告警、故障演练与最终验收。
  * 交付：Runbook、Helm Charts、性能与稳定性报告。

---

## 12. 风险与对策

* **HTTP/2/网络兼容**：外部统一走 WS；内部 gRPC 在内网。
* **Opus 编解码抖动**：仅 ASR 链路使用；失败回退 PCM；可调 `bitrate/frame_ms`。
* **ASR 瓶颈**：多池路由、并发上限、熔断/降级、自动扩缩与预热。
* **大文件中转**：旁路归档直写对象存储，避免 Orchestrator 中转。

---

## 13. 交付清单

* 源码（Orchestrator、各服务、proto）、Docker/Helm/K8s、CI（lint/test/build/push/deploy）。
* 文档（API/Schema、运维手册、监控面板、告警策略）。
* 测试（E2E/性能/稳定性/故障注入脚本与报告）。

---

## 14. 代码片段（关键最小实现）

### 14.1 Orchestrator：PCM → Opus（仅 ASR 链路）

```python
# pip install opuslib
import numpy as np
from opuslib import Encoder, APPLICATION_AUDIO

SR, CH, FRAME_MS, BITRATE = 16000, 1, 20, 20000
SAMPLES = SR * FRAME_MS // 1000

enc = Encoder(SR, CH, APPLICATION_AUDIO)
enc.bitrate = BITRATE  # 可配：16k~24k

def pcm_to_opus_packets(pcm_int16: np.ndarray):
    for i in range(0, len(pcm_int16), SAMPLES):
        frame = pcm_int16[i:i+SAMPLES]
        if len(frame) < SAMPLES: break
        yield enc.encode(frame.tobytes(), SAMPLES)  # bytes(单包)
```

### 14.2 ASR 端：Opus → PCM 解码

```python
from opuslib import Decoder
SR, CH, FRAME_MS = 16000, 1, 20
SAMPLES = SR * FRAME_MS // 1000
dec = Decoder(SR, CH)

def opus_packet_to_pcm(packet: bytes) -> bytes:
    return dec.decode(packet, SAMPLES)  # 320 samples * 2 bytes
```

---

