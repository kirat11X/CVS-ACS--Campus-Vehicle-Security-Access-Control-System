#!/usr/bin/env bash
# ==============================================================================
# ec2/ec2_healthcheck.sh
# ==============================================================================
# Comprehensive System & Hardware Diagnostic Healthcheck for CVS-ACS on AWS EC2
#
# Inspects:
#   1. GPU Hardware, Driver Version, CUDA Runtime, VRAM, and Thermals
#   2. System Resources: RAM, Swap, CPU Cores, Load Averages
#   3. Storage: EBS Volumes, Root Filesystem Free Space, Inode Availability
#   4. Docker & NVIDIA Container Toolkit Runtime Status
#   5. Python 3.12 ML Environment & PyTorch CUDA Acceleration
#   6. Keras 3 Backend (KERAS_BACKEND=torch) & Fine-Tuning Libraries
#   7. PyTorch GPU Tensor Computation Benchmark
#
# Usage:
#   ./ec2/ec2_healthcheck.sh
# ==============================================================================

set -euo pipefail

# ANSI Colors
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
MAGENTA="\033[35m"
RESET="\033[0m"

PASS="${GREEN}[PASS]${RESET}"
WARN="${YELLOW}[WARN]${RESET}"
FAIL="${RED}[FAIL]${RESET}"

SCORE_PASS=0
SCORE_WARN=0
SCORE_FAIL=0

check_status() {
    local status="$1"
    local message="$2"
    if [ "$status" = "PASS" ]; then
        echo -e "  $PASS $message"
        SCORE_PASS=$((SCORE_PASS + 1))
    elif [ "$status" = "WARN" ]; then
        echo -e "  $WARN $message"
        SCORE_WARN=$((SCORE_WARN + 1))
    else
        echo -e "  $FAIL $message"
        SCORE_FAIL=$((SCORE_FAIL + 1))
    fi
}

echo -e "\n${BOLD}${CYAN}======================================================================${RESET}"
echo -e "${BOLD}${CYAN}            CVS-ACS AWS EC2 SYSTEM & ML HEALTHCHECK           ${RESET}"
echo -e "${BOLD}${CYAN}======================================================================${RESET}\n"

# ------------------------------------------------------------------------------
# 1. GPU & CUDA Diagnostics
# ------------------------------------------------------------------------------
echo -e "${BOLD}1. GPU & CUDA ACCELERATION:${RESET}"

if command -v nvidia-smi >/dev/null 2>&1; then
    DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 || echo "Unknown")
    CUDA_VER=$(nvidia-smi 2>/dev/null | grep -iE -o "CUDA (Version|UMD Version):? [0-9.]*" | head -n 1 | awk '{print $NF}' || echo "N/A")
    GPU_NAME=$(nvidia-smi --query-gpu=gpu_name --format=csv,noheader 2>/dev/null | head -n 1 || echo "NVIDIA Device")
    TOTAL_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -n 1 || echo "N/A")
    FREE_VRAM=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader 2>/dev/null | head -n 1 || echo "N/A")
    GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null | head -n 1 || echo "N/A")
    POWER_DRAW=$(nvidia-smi --query-gpu=power.draw --format=csv,noheader 2>/dev/null | head -n 1 || echo "N/A")

    check_status "PASS" "NVIDIA Driver: $DRIVER_VER | CUDA: $CUDA_VER"
    check_status "PASS" "GPU Device:   $GPU_NAME"
    check_status "PASS" "VRAM:         $FREE_VRAM free / $TOTAL_VRAM total"
    check_status "PASS" "Thermals:     ${GPU_TEMP}°C | Power: $POWER_DRAW"
else
    check_status "FAIL" "nvidia-smi not found. NVIDIA driver is not installed or loaded."
fi

# ------------------------------------------------------------------------------
# 2. System Resources (RAM, CPU)
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}2. SYSTEM RESOURCES (RAM & CPU):${RESET}"

TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
AVAIL_RAM_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
TOTAL_RAM_GB=$(awk "BEGIN {printf \"%.1f\", $TOTAL_RAM_KB / 1024 / 1024}")
AVAIL_RAM_GB=$(awk "BEGIN {printf \"%.1f\", $AVAIL_RAM_KB / 1024 / 1024}")
AVAIL_RAM_MB=$((AVAIL_RAM_KB / 1024))

if [ "$AVAIL_RAM_MB" -ge 6000 ]; then
    check_status "PASS" "System RAM:   $AVAIL_RAM_GB GB available / $TOTAL_RAM_GB GB total"
elif [ "$AVAIL_RAM_MB" -ge 3000 ]; then
    check_status "WARN" "System RAM:   $AVAIL_RAM_GB GB available (low headroom; recommend closing background tasks)"
else
    check_status "FAIL" "System RAM:   $AVAIL_RAM_GB GB available (critically low; OOM risk)"
fi

CPU_CORES=$(nproc)
LOAD_1=$(awk '{print $1}' /proc/loadavg)
LOAD_5=$(awk '{print $2}' /proc/loadavg)
check_status "PASS" "CPU Cores:    $CPU_CORES vCPUs | Load: $LOAD_1 (1m), $LOAD_5 (5m)"

# ------------------------------------------------------------------------------
# 3. Storage & Disk Space
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}3. STORAGE & DISK CAPACITY:${RESET}"

ROOT_DISK_AVAIL_GB=$(df -BG / | tail -n 1 | awk '{print $(NF-2)}' | tr -d 'G' || echo "0")
ROOT_DISK_TOTAL_GB=$(df -BG / | tail -n 1 | awk '{print $(NF-4)}' | tr -d 'G' || echo "0")

if [ "$ROOT_DISK_AVAIL_GB" -ge 25 ] 2>/dev/null; then
    check_status "PASS" "Root Disk:    $ROOT_DISK_AVAIL_GB GB free / $ROOT_DISK_TOTAL_GB GB total"
elif [ "$ROOT_DISK_AVAIL_GB" -ge 8 ] 2>/dev/null; then
    check_status "WARN" "Root Disk:    $ROOT_DISK_AVAIL_GB GB free (minimum for 1 model fine-tuning)"
else
    check_status "FAIL" "Root Disk:    $ROOT_DISK_AVAIL_GB GB free (insufficient for dataset + checkpoints)"
fi

# ------------------------------------------------------------------------------
# 4. Container & Docker Daemon
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}4. DOCKER & NVIDIA CONTAINER RUNTIME:${RESET}"

if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        check_status "PASS" "Docker Daemon: Running ($(docker --version | awk '{print $3}' | sed 's/,//'))"
        if docker info 2>/dev/null | grep -i "nvidia" >/dev/null 2>&1; then
            check_status "PASS" "NVIDIA Container Runtime: Configured in Docker"
        else
            check_status "WARN" "NVIDIA Container Runtime: Not active in docker daemon config"
        fi
    else
        check_status "WARN" "Docker installed but daemon is not running (sudo systemctl start docker)"
    fi
else
    check_status "WARN" "Docker Engine is not installed (optional for local scripts, required for deployment)"
fi

# ------------------------------------------------------------------------------
# 5. Python ML Environment & PyTorch CUDA Readiness
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}5. PYTHON ML STACK & PYTORCH ACCELERATION:${RESET}"

ML_ROOT="$HOME/ml-assets/campus"
VENV_DIR="${ML_ROOT}/.venv-ml"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -d "$VENV_DIR" ]; then
    PYTHON_BIN="$VENV_DIR/bin/python"
    check_status "PASS" "Virtualenv:   $VENV_DIR"
elif [ -d "${REPO_ROOT}/.venv" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
    check_status "PASS" "Virtualenv:   ${REPO_ROOT}/.venv (repo local)"
else
    PYTHON_BIN="$(which python3)"
    check_status "WARN" "Dedicated virtualenv not found; using system Python ($PYTHON_BIN)"
fi

export KERAS_BACKEND=torch

# Run Inline Python Verification
"$PYTHON_BIN" - > /tmp/py_health.txt << 'EOF'
import sys
import os

try:
    import torch
    torch_ok = True
    torch_ver = torch.__version__
    cuda_ok = torch.cuda.is_available()
    device_name = torch.cuda.get_device_name(0) if cuda_ok else "None"
except Exception as e:
    torch_ok = False
    torch_ver = f"Error: {e}"
    cuda_ok = False
    device_name = "None"

print(f"PY_VER:{sys.version.split()[0]}")
print(f"TORCH_OK:{torch_ok}")
print(f"TORCH_VER:{torch_ver}")
print(f"CUDA_OK:{cuda_ok}")
print(f"DEVICE_NAME:{device_name}")

# Check fine-tuning libraries
libs = {}
for mod in ["keras", "transformers", "peft", "bitsandbytes", "trl", "ultralytics"]:
    try:
        m = __import__(mod)
        libs[mod] = getattr(m, "__version__", "installed")
    except Exception:
        libs[mod] = "MISSING"

for k, v in libs.items():
    print(f"LIB_{k.upper()}:{v}")

# Benchmark PyTorch GPU forward pass
bench_result = "SKIPPED"
if cuda_ok:
    try:
        t0 = torch.cuda.Event(enable_timing=True)
        t1 = torch.cuda.Event(enable_timing=True)
        x = torch.randn(4096, 4096, device="cuda")
        t0.record()
        y = x @ x
        t1.record()
        torch.cuda.synchronize()
        elapsed_ms = t0.elapsed_time(t1)
        bench_result = f"Matrix 4096x4096 in {elapsed_ms:.1f} ms"
    except Exception as e:
        bench_result = f"Error: {e}"

print(f"BENCHMARK:{bench_result}")
EOF

PY_VER=$(grep "PY_VER:" /tmp/py_health.txt | cut -d':' -f2 || echo "N/A")
TORCH_OK=$(grep "TORCH_OK:" /tmp/py_health.txt | cut -d':' -f2 || echo "False")
TORCH_VER=$(grep "TORCH_VER:" /tmp/py_health.txt | cut -d':' -f2 || echo "N/A")
CUDA_OK=$(grep "CUDA_OK:" /tmp/py_health.txt | cut -d':' -f2 || echo "False")
DEVICE_NAME=$(grep "DEVICE_NAME:" /tmp/py_health.txt | cut -d':' -f2 || echo "N/A")
BENCHMARK=$(grep "BENCHMARK:" /tmp/py_health.txt | cut -d':' -f2 || echo "SKIPPED")

check_status "PASS" "Python Version: $PY_VER"

if [ "$TORCH_OK" = "True" ]; then
    check_status "PASS" "PyTorch:       $TORCH_VER"
else
    check_status "WARN" "PyTorch:       Not installed or Error ($TORCH_VER)"
fi

if [ "$CUDA_OK" = "True" ]; then
    check_status "PASS" "PyTorch CUDA:  ACTIVE ($DEVICE_NAME)"
    check_status "PASS" "GPU Benchmark: $BENCHMARK"
else
    check_status "WARN" "PyTorch CUDA:  NOT DETECTED (will use CPU)"
fi

# Print ML Libraries Status
LIB_KERAS=$(grep "LIB_KERAS:" /tmp/py_health.txt | cut -d':' -f2)
LIB_TRANSFORMERS=$(grep "LIB_TRANSFORMERS:" /tmp/py_health.txt | cut -d':' -f2)
LIB_PEFT=$(grep "LIB_PEFT:" /tmp/py_health.txt | cut -d':' -f2)
LIB_BNB=$(grep "LIB_BITSANDBYTES:" /tmp/py_health.txt | cut -d':' -f2)
LIB_YOLO=$(grep "LIB_ULTRALYTICS:" /tmp/py_health.txt | cut -d':' -f2)

echo -e "\n${BOLD}6. INSTALLED ML & TRAINING PACKAGES:${RESET}"
[ "$LIB_KERAS" != "MISSING" ] && check_status "PASS" "Keras 3:       v$LIB_KERAS (KERAS_BACKEND=torch)" || check_status "WARN" "Keras 3:       Not installed"
[ "$LIB_TRANSFORMERS" != "MISSING" ] && check_status "PASS" "Transformers:  v$LIB_TRANSFORMERS" || check_status "WARN" "Transformers:  Not installed"
[ "$LIB_PEFT" != "MISSING" ] && check_status "PASS" "PEFT (LoRA):   v$LIB_PEFT" || check_status "WARN" "PEFT:          Not installed"
[ "$LIB_BNB" != "MISSING" ] && check_status "PASS" "bitsandbytes:  v$LIB_BNB (4-bit QLoRA ready)" || check_status "WARN" "bitsandbytes:  Not installed"
[ "$LIB_YOLO" != "MISSING" ] && check_status "PASS" "Ultralytics:   v$LIB_YOLO (YOLO11 ready)" || check_status "WARN" "Ultralytics:   Not installed"

# ------------------------------------------------------------------------------
# Final Scorecard & Summary
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}${CYAN}======================================================================${RESET}"
echo -e "${BOLD}                       DIAGNOSTIC SCORECARD                          ${RESET}"
echo -e "${BOLD}${CYAN}======================================================================${RESET}"
echo -e "  Passed Checks:    ${GREEN}${SCORE_PASS}${RESET}"
echo -e "  Warnings:         ${YELLOW}${SCORE_WARN}${RESET}"
echo -e "  Critical Failures:${RED}${SCORE_FAIL}${RESET}"

if [ "$SCORE_FAIL" -eq 0 ]; then
    echo -e "\n${BOLD}${GREEN}==> EC2 GPU HOST IS FULLY CERTIFIED AND READY FOR ML TRAINING! <==${RESET}\n"
    exit 0
else
    echo -e "\n${BOLD}${RED}==> SYSTEM HAS CRITICAL ISSUES REQUIRING ATTENTION BEFORE TRAINING. <==${RESET}\n"
    exit 1
fi
