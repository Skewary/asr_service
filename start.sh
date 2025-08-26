#!/bin/bash
# Batch start script for ASR service components
set -euo pipefail
cd "$(dirname "$0")"
nohup python -m services.vad.server > vad.out &
nohup python -m services.denoise.server > denoise.out &
nohup python -m services.lid.server > lid.out &
nohup python -m services.compress.server > compress.out &
nohup python -m orchestrator.server_ws > server.out &
