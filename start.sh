#!/bin/bash
# Batch start script for ASR service components
set -euo pipefail
cd "$(dirname "$0")"
nohup python -m services.vad.server > vad.out 2>&1 &
nohup python -m services.denoise.server > denoise.out 2>&1 &
nohup python -m services.lid.server > lid.out 2>&1 &
nohup python -m services.compress.server > compress.out 2>&1 &
nohup python -m orchestrator.server_ws > server.out 2>&1 &
