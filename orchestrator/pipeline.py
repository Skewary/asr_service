import asyncio
import logging
from typing import Any, Dict

from .modules import denoise_client, lid_client, asr_client, vad_client, compress_client

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main pipeline coordinating audio processing services."""

    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}

    async def start_flow(self, flow_id: str, ws, params: dict) -> None:
        """Prepare session state for a new streaming flow."""
        self.sessions[flow_id] = {
            "ws": ws,
            "compress": compress_client.CompressClient(),
            "asr": asr_client.AsrClient(flow_id),
            "lid": lid_client.LidClient(flow_id),
            "vad": vad_client.VadClient(flow_id=flow_id),
            "denoise": denoise_client.DenoiseClient(),
            "buffer": bytearray(),
        }
        logger.info("[%s] start", flow_id)

    async def feed_pcm(self, flow_id: str, pcm_bytes: bytes, ws) -> None:
        """Process raw PCM: VAD -> Denoise -> LID (buffer only)."""
        if flow_id not in self.sessions:
            return
        sess = self.sessions[flow_id]
        vad_out = await sess["vad"].send(pcm_bytes)
        if not vad_out:
            return
        pcm_clean = await sess["denoise"].send(vad_out)
        sess["lid"].feed(pcm_clean)
        sess["buffer"].extend(pcm_clean)

    async def flush(self, flow_id: str) -> None:
        """Flush remaining audio, detect language, and stream to ASR."""
        sess = self.sessions.get(flow_id)
        if not sess:
            return
        vad_tail = await sess["vad"].flush()
        if vad_tail:
            pcm_clean = await sess["denoise"].send(vad_tail)
            sess["lid"].feed(pcm_clean)
            sess["buffer"].extend(pcm_clean)
        language = await sess["lid"].flush()
        buffer = bytes(sess["buffer"])
        packets = await sess["compress"].encode(buffer)
        first = True
        for pkt in packets:
            await sess["asr"].send(pkt, language if first else None)
            first = False
        await sess["asr"].flush()
        if language:
            await sess["ws"].write_message({"type": "lid", "flowId": flow_id, "language": language})
        await sess["ws"].write_message({"type": "end", "flowId": flow_id})
        sess["buffer"].clear()

    def close_flow(self, flow_id: str) -> None:
        """Cleanup session state."""
        sess = self.sessions.pop(flow_id, None)
        if sess:
            sess["asr"].close()
            sess["lid"].close()
            sess["denoise"].close()
            sess["compress"].close()
        logger.info("[%s] closed", flow_id)
