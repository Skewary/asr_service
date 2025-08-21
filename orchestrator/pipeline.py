import asyncio
from typing import Any, Dict

from .modules import denoise_client, lid_client, asr_client, vad_client
from .utils.opus_codec import PcmToOpus


class Orchestrator:
    """Main pipeline coordinating audio processing services."""

    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}

    async def start_flow(self, flow_id: str, ws, params: dict) -> None:
        """Prepare session state for a new streaming flow."""
        self.sessions[flow_id] = {
            "ws": ws,
            "opus": PcmToOpus(),
            "asr": asr_client.AsrClient(flow_id),
            "lid": lid_client.LidClient(flow_id),
            "vad": vad_client.VadClient(),
        }
        print(f"[{flow_id}] start")

    async def feed_pcm(self, flow_id: str, pcm_bytes: bytes, ws) -> None:
        """Process raw PCM: VAD -> Denoise -> LID -> ASR."""
        if flow_id not in self.sessions:
            return
        sess = self.sessions[flow_id]
        # Dispatch to VAD and denoise services
        vad_out = await sess["vad"].send(pcm_bytes)
        if not vad_out:
            return
        pcm_clean = await denoise_client.send(vad_out)
        sess["lid"].feed(pcm_clean)
        # Encode to Opus for ASR
        for pkt in sess["opus"].encode(pcm_clean):
            await sess["asr"].send(pkt)

    async def flush(self, flow_id: str) -> None:
        """Signal end of stream and notify client."""
        sess = self.sessions.get(flow_id)
        if not sess:
            return
        vad_tail = await sess["vad"].flush()
        if vad_tail:
            pcm_clean = await denoise_client.send(vad_tail)
            sess["lid"].feed(pcm_clean)
            for pkt in sess["opus"].encode(pcm_clean):
                await sess["asr"].send(pkt)
        await sess["asr"].flush()
        await sess["ws"].write_message({"type": "end", "flowId": flow_id})

    def close_flow(self, flow_id: str) -> None:
        """Cleanup session state."""
        sess = self.sessions.pop(flow_id, None)
        if sess:
            sess["asr"].close()
        print(f"[{flow_id}] closed")