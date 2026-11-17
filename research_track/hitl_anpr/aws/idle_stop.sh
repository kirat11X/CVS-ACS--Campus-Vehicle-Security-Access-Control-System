#!/bin/bash
# Shuts the instance down after IDLE_MINUTES with GPU utilisation under 5% and no training container running.
# Launched with InstanceInitiatedShutdownBehavior=terminate, so an idle instance stops costing money; the data
# root lives in the encrypted bucket. Leaves a log line for every decision.
set -uo pipefail
source /opt/anpr/env
idle=0
while true; do
  util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | sort -nr | head -1)
  running=$(docker ps -q | wc -l)
  if [ "${util:-0}" -lt 5 ] && [ "$running" -eq 0 ]; then
    idle=$((idle + 1))
  else
    idle=0
  fi
  if [ "$idle" -ge "$IDLE_MINUTES" ]; then
    echo "$(date -Is) idle for $IDLE_MINUTES min (GPU ${util:-?}%, $running containers): shutting down"
    shutdown -h now
    exit 0
  fi
  sleep 60
done
