"""Central configuration for ports and logging."""
import logging
import os

VAD_PORT = int(os.environ.get("VAD_PORT", "9001"))
DENOISE_PORT = int(os.environ.get("DENOISE_PORT", "50053"))
LID_PORT = int(os.environ.get("LID_PORT", "50052"))
COMPRESS_PORT = int(os.environ.get("COMPRESS_PORT", "50054"))
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))
ASR_PORT = int(os.environ.get("ASR_PORT", "50051"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = os.environ.get(
    "LOG_FORMAT", "%(asctime)s %(levelname)s [%(name)s] %(message)s"
)


def configure_logging() -> None:
    """Configure root logger according to environment variables."""
    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
