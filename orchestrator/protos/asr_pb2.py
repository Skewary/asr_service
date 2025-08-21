"""Minimal stub of ASR proto messages for compilation."""

from dataclasses import dataclass


@dataclass
class Start:
    flow_id: str
    codec: str
    sr: int


@dataclass
class OpusPacket:
    data: bytes


@dataclass
class ClientFrame:
    start: Start | None = None
    opus: OpusPacket | None = None
