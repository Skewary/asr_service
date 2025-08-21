# LID 语种识别服务

基于 [SpeechBrain](https://github.com/speechbrain/speechbrain) 提供的
`lang-id-commonlanguage_ecapa` 预训练模型，实现一个最小化的 gRPC 语种识别服务。

## 启动

```bash
python server.py
```

首次启动会自动把模型下载到仓库的 `models/lid/` 目录，以便后续复用。

## 接口

通过 gRPC 暴露 `Detect` 方法，接收 16k 采样率、16-bit 单声道的 PCM
字节，返回预测的语种标签和置信度。

```proto
service LID {
  rpc Detect(LIDRequest) returns (LIDResponse);
}

message LIDRequest {
  bytes pcm = 1;
  int32 sample_rate = 2;
}

message LIDResponse {
  string language = 1;
  float score = 2;
}
```

## 注意

- 服务默认监听 `50052` 端口；
- 仅做演示用途，未实现批量或流式识别；
- 需要 `speechbrain`、`grpcio` 等依赖支持。
