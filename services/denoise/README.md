# 降噪服务 (Denoise)

该目录提供一个最小化的 gRPC 降噪示例。服务端接收 PCM16/16k 单声道音频，当前实现仅回传原始音频，便于验证编排器的 gRPC 交互流程。

## 启动

```bash
python -m services.denoise.server
```

服务默认监听 `50053` 端口。

## 接口

```proto
rpc Clean(Audio) returns (Audio);
```

请求与响应均为原始 PCM 数据，字段：

- `pcm`：字节流形式的 PCM16 音频
- `sample_rate`：采样率，默认 16000

未来可在此基础上集成真实的降噪模型。
