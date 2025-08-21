"""Stub client performing language identification."""


class LidClient:
    def __init__(self, flow_id: str, target: str = "lid:50051") -> None:
        self.flow_id = flow_id
        self.target = target
        self.buffer = bytearray()

    def feed(self, pcm_bytes: bytes) -> None:
        """Collect PCM for language identification (stub)."""
        self.buffer.extend(pcm_bytes)
