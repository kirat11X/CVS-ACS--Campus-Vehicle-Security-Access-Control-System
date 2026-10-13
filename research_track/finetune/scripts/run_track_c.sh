#!/usr/bin/env bash
# Track C launcher (tmux/nohup friendly). Usage:
#   run_track_c.sh <run_id> [c_train_lora.py args...]
# e.g. nohup ./run_track_c.sh full_v1 --lr 2e-4 --epochs 8 > /dev/null 2>&1 &
# Watchdog: writes <run_dir>/STOP (trainer checkpoints and exits) if GPU temp >= 85 C for 2 min,
# total GPU memory used > 5.8 GB, or MemAvailable < 1.5 GB. If the trainer has not exited
# 180 s after STOP, the watchdog sends SIGTERM to the trainer it started (and only to it).
set -euo pipefail
RUN_ID="${1:?run_id required}"; shift
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/ml-assets/campus/.venv-ml/bin/python"
RUN_DIR="$HOME/ml-assets/campus/runs/C/$RUN_ID"
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/train.log"; WLOG="$RUN_DIR/watchdog.log"

if [ "$(cat /sys/class/power_supply/AC/online 2>/dev/null || echo 0)" != "1" ]; then
  echo "ABORT: not on AC power" | tee -a "$WLOG"; exit 3
fi

export CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export HF_HOME="$HOME/ml-assets/campus/hf" PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

INHIBIT=()
if command -v systemd-inhibit >/dev/null && systemd-inhibit --what=sleep --why=probe --mode=block true 2>/dev/null; then
  INHIBIT=(systemd-inhibit --what=sleep --who="track_c_$RUN_ID" --why="Track C QLoRA training" --mode=block)
fi

cd "$HERE"
"${INHIBIT[@]}" nice -n 10 "$PY" -u c_train_lora.py --run-id "$RUN_ID" "$@" >>"$LOG" 2>&1 &
TPID=$!
echo "$(date -Is) started pid=$TPID args=$*" >>"$WLOG"

hot=0; stop_at=0
while kill -0 "$TPID" 2>/dev/null; do
  read -r temp mem < <(nvidia-smi --query-gpu=temperature.gpu,memory.used --format=csv,noheader,nounits | tr -d ',')
  avail_kb=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  ac=$(cat /sys/class/power_supply/AC/online 2>/dev/null || echo 1)
  reason=""
  if [ "$temp" -ge 85 ]; then hot=$((hot+10)); else hot=0; fi
  [ "$hot" -ge 120 ] && reason="gpu temp ${temp}C >= 85C for 2 min"
  [ "$mem" -gt 5939 ] && reason="gpu mem ${mem}MiB > 5.8GB"
  [ "$avail_kb" -lt 1572864 ] && reason="MemAvailable ${avail_kb}kB < 1.5GB"
  [ "$ac" != "1" ] && echo "$(date -Is) WARN on battery" >>"$WLOG"
  if [ -n "$reason" ] && [ ! -f "$RUN_DIR/STOP" ]; then
    echo "$reason" >"$RUN_DIR/STOP"; stop_at=$(date +%s)
    echo "$(date -Is) STOP requested: $reason" >>"$WLOG"
  fi
  if [ "$stop_at" -gt 0 ] && [ $(( $(date +%s) - stop_at )) -gt 180 ]; then
    echo "$(date -Is) trainer did not exit within 180s of STOP; SIGTERM $TPID" >>"$WLOG"; kill -TERM "$TPID" || true
  fi
  echo "$(date -Is) temp=${temp} gpu_mem_mib=${mem} mem_avail_kb=${avail_kb}" >>"$WLOG"
  sleep 10
done
set +e; wait "$TPID"; rc=$?; set -e
echo "$(date -Is) trainer exited rc=$rc" >>"$WLOG"
exit $rc
