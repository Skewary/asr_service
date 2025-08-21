# 编排器 (Orchestrator)

该目录提供一个最小可用的音频编排器示例，通过 WebSocket 接收 PCM16 音频数据，内部串联 VAD/降噪/LID/ASR，并将结果回推给客户端。

## 使用流程

1. **启动服务**
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

## 注意事项

- 当前示例中的降噪、LID 仅为占位实现，需接入实际 gRPC 服务方可生效。
- 仅在发送到 ASR 之前会将 PCM 编码为 Opus，其余链路全部保持 PCM。
- VAD 模块基于 sherpa‑onnx，本仓库默认加载 `models/ten-vad.onnx`，请确保模型文件存在。
- 本示例仅用于演示编排流程，未包含鉴权、错误处理、监控等生产级特性。

