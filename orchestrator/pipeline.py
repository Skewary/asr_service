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
            logger.warning("[%s] feed on unknown session", flow_id)
            return
        sess = self.sessions[flow_id]
        logger.debug("[%s] recv %d bytes", flow_id, len(pcm_bytes))
        vad_out = await sess["vad"].send(pcm_bytes)
        logger.debug("[%s] vad -> %d bytes", flow_id, len(vad_out))
        if not vad_out:
            return
        pcm_clean = await sess["denoise"].send(vad_out)
        logger.debug("[%s] denoise -> %d bytes", flow_id, len(pcm_clean))
        sess["lid"].feed(pcm_clean)
        sess["buffer"].extend(pcm_clean)
        logger.debug("[%s] buffer %d bytes", flow_id, len(sess["buffer"]))

    async def flush(self, flow_id: str) -> None:
        """Flush remaining audio, detect language, and stream to ASR."""
        sess = self.sessions.get(flow_id)
        if not sess:
            return
        logger.info("[%s] flush with %d buffered bytes", flow_id, len(sess["buffer"]))
        vad_tail = await sess["vad"].flush()
        logger.debug("[%s] vad tail %d bytes", flow_id, len(vad_tail))
        if vad_tail:
            pcm_clean = await sess["denoise"].send(vad_tail)
            logger.debug("[%s] denoise tail -> %d bytes", flow_id, len(pcm_clean))
            sess["lid"].feed(pcm_clean)
            sess["buffer"].extend(pcm_clean)
        language = await sess["lid"].flush()
        logger.info("[%s] language %s", flow_id, language)
        buffer = bytes(sess["buffer"])
        packets = await sess["compress"].encode(buffer)
        logger.debug("[%s] compress -> %d packets", flow_id, len(packets))
        first = True
        for pkt in packets:
            logger.debug("[%s] send packet %d bytes", flow_id, len(pkt))
            await sess["asr"].send(pkt, language if first else None)
            first = False
        await sess["asr"].flush()
        if language:
            await sess["ws"].write_message({"type": "lid", "flowId": flow_id, "language": language})
        await sess["ws"].write_message({"type": "end", "flowId": flow_id})
        sess["buffer"].clear()
        logger.info("[%s] flush done", flow_id)

    def close_flow(self, flow_id: str) -> None:
        """Cleanup session state."""
        sess = self.sessions.pop(flow_id, None)
        if sess:
            sess["asr"].close()
            sess["lid"].close()
            sess["denoise"].close()
            sess["compress"].close()
        logger.info("[%s] closed", flow_id)
