# 压缩服务（Compress）

将输入的 PCM 裸音频编码为 Opus 帧，供编排器发送至 ASR 服务。

## 启动

```bash
python -m services.compress.server
```

服务默认监听在 `50054` 端口，可通过 `COMPRESS_PORT` 环境变量调整。
使用仓库根目录的 `./start.sh` 时，本服务会自动启动并将日志写入 `compress.out`。

## 接口

- **Encode**: 单次请求编码一个 20ms 的 PCM 帧，返回对应的 Opus 数据。

请求与响应均使用 gRPC 二进制消息，字段如下：

| 消息类型 | 字段 | 说明 |
| --- | --- | --- |
| `PCM` | `data` | 16kHz 单声道 `int16` PCM 数据 |
| `Opus` | `data` | 编码后的 Opus 帧 |

## 注意事项

- 当前实现仅支持 20ms 帧长，调用方需自行切片。
- 编码器默认比特率为 20kbps，可在服务端修改参数。
