# 编排器 (Orchestrator)

该目录提供一个最小可用的音频编排器示例，通过 WebSocket 接收 PCM16 音频数据，内部串联 VAD/降噪/LID/压缩/ASR，并将结果回推给客户端。

## 启动依赖服务
可以通过仓库根目录的 `start.sh` 一键启动 VAD、降噪、LID、压缩及编排器，并把日志分别写入对应的 `*.out` 文件。

## 使用流程

1. **启动编排器**
   ```bash
   python -m orchestrator.server_ws
   ```
   默认监听 `8000` 端口，可根据需要自行修改。

2. **客户端接入**
   - 建立到 `ws://<host>:8000/ws/stream` 的 WebSocket 连接。
   - 首帧发送 `start` 控制消息：
     ```json
     {"type":"start", "flowId":"demo"}
     ```
   - 随后连续发送二进制 PCM16/16k/mono 数据帧（建议 20ms 一帧）。
   - 发送 `{"type":"flush"}` 或直接断开以结束会话。

3. **事件返回**
   服务端会通过文本帧返回 `ack` / `lid` / `asr_partial` / `asr_final` / `end` 等事件。

   仓库提供了 `tests/send_to_orchestrator.py` 作为示例客户端，可用于快速验证：

   ```bash
   PYTHONPATH=. python tests/send_to_orchestrator.py --ws ws://127.0.0.1:9000/ws/stream --input tests/test.wav
   ```

## 注意事项

- 当前降噪服务仅回传原始音频，作为 gRPC 交互示例。
- `lid` 事件在 `flush` 后返回整体语种结果，同时该标签也会附加在发送到 ASR 的起始帧中。
- 仅在发送到 ASR 之前会将 PCM 编码为 Opus，其余链路全部保持 PCM。
- Opus 编码由 `services.compress` 服务负责，默认监听 `50054` 端口。
- VAD 模块基于 sherpa‑onnx，本仓库默认加载 `models/ten-vad.onnx`，请确保模型文件存在。
- 本示例仅用于演示编排流程，未包含鉴权、错误处理、监控等生产级特性。
