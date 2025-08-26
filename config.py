"""Central port configuration for services and clients."""
import os

VAD_PORT = int(os.environ.get("VAD_PORT", "9001"))
DENOISE_PORT = int(os.environ.get("DENOISE_PORT", "50053"))
LID_PORT = int(os.environ.get("LID_PORT", "50052"))
COMPRESS_PORT = int(os.environ.get("COMPRESS_PORT", "50054"))
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))
ASR_PORT = int(os.environ.get("ASR_PORT", "50051"))
