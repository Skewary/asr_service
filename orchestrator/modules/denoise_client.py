"""Stub gRPC client for denoising service."""

import asyncio


async def send(pcm_bytes: bytes) -> bytes:
    """Pretend to send PCM to denoising service and return cleaned audio."""
    await asyncio.sleep(0)
    return pcm_bytes
