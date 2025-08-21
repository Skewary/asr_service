"""Miscellaneous audio utilities."""

from __future__ import annotations

from typing import Iterable


def iter_chunks(pcm: bytes, chunk_samples: int) -> Iterable[bytes]:
    """Yield fixed-size PCM chunks."""
    for i in range(0, len(pcm), chunk_samples * 2):
        chunk = pcm[i : i + chunk_samples * 2]
        if len(chunk) < chunk_samples * 2:
            break
        yield chunk
