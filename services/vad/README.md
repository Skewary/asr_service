# VAD 服务

使用 gRPC 对外提供语音活动检测。

## 启动

```bash
python -m services.vad.server
```

首次运行会自动把 `ten-vad.onnx` 模型下载到仓库根目录的 `models/` 目录，后续可复用。服务默认监听 `9001` 端口，可通过环境变量 `VAD_PORT` 覆盖。
在仓库根目录执行 `./start.sh` 时，本服务会自动启动并将日志写入 `vad.out`。

## 交互流程

- 客户端建立 gRPC 双向流 `VoiceActivity/Stream`。
- 首帧发送 `Start`，指定 `flow_id`和采样率（16k）。
- 后续帧发送 16bit PCM 数据 `Pcm`。
- 服务端根据 VAD 算法返回检测出的语音段，同样为 PCM。
- 发送 `Flush` 后关闭写入，服务端会回传最后一段语音并结束流。

该服务与 `orchestrator` 协同使用，由后者负责把输出再串联到降噪、识别等模块。
