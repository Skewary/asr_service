# ASR 服务编排 Demo

基于 WebSocket 和 gRPC 的流式语音识别示例。编排器从客户端接收 PCM16/16k 单声道音频，依次调用 VAD、降噪、LID，再在发送给 ASR 前编码为 Opus，最终聚合结果回推给客户端。

## 依赖

请先安装 Python 3.10+，然后执行：

```bash
pip install -r requirements.txt
```

## 目录结构

```text
.
├── models/                # 模型缓存（VAD、LID 等）
├── orchestrator/          # WebSocket 入口及编排逻辑
│   ├── modules/           # 各 gRPC 客户端
│   └── utils/             # Opus 编码等工具
├── services/
│   ├── vad/               # 语音活动检测 gRPC 服务
│   ├── denoise/           # 空壳降噪 gRPC 服务
│   ├── lid/               # 语言识别 gRPC 服务
│   └── compress/          # PCM→Opus 压缩 gRPC 服务
├── tests/                 # 测试脚本
└── requirements.txt
```

## 快速开始

1. 安装依赖：`pip install -r requirements.txt`
2. 启动所有 gRPC 服务与编排器：

   ```bash
   ./start.sh
   ```
   每个服务的标准输出和错误日志将分别写入 `vad.out`、`denoise.out`、`lid.out`、`compress.out` 和 `server.out`，便于排查问题。若需要更详细日志，可设置环境变量 `LOG_LEVEL=DEBUG` 后再运行。
3. 运行示例客户端，将本地 `16k PCM` 流发送到 VAD 服务：

   ```bash
   PYTHONPATH=. python tests/send_only.py
   ```
   首次启动 VAD 与 LID 服务会自动将模型下载到仓库的 `models/` 目录。

## 当前进度

- ✅ WebSocket 编排器，可接入 PCM 并汇聚 VAD/降噪/LID/压缩/ASR 结果
- ✅ VAD / LID / 空壳降噪 / 压缩 gRPC 服务及示例客户端

后续将继续完善监控、降噪以及更多编排能力。
