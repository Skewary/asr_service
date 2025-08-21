"""Stub gRPC client for voice activity detection."""

import asyncio


async def send(pcm_bytes: bytes) -> bytes:
    """Pretend to send PCM to VAD service and return trimmed audio."""
    await asyncio.sleep(0)
    return pcm_bytes
