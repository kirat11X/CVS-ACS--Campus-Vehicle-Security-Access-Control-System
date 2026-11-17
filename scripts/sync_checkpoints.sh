#!/usr/bin/env bash
# ==============================================================================
# scripts/sync_checkpoints.sh
# ==============================================================================
# Automated Checkpoint & LoRA Adapter Synchronization between AWS EC2 & Local Host
#
# Usage:
#   # Pull all trained weights from EC2 to local campus workstation:
#   ./scripts/sync_checkpoints.sh pull --host ec2-user@<EC2_IP> --key ~/.ssh/cvs-key.pem
#
#   # Push local weights/assets to EC2 instance:
#   ./scripts/sync_checkpoints.sh push --host ec2-user@<EC2_IP> --key ~/.ssh/cvs-key.pem
# ==============================================================================

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

log_info()  { echo -e "${CYAN}[INFO]${RESET} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${RESET} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${RESET} $1"; }
log_error() { echo -e "${RED}[ERROR]${RESET} $1"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION=""
EC2_HOST=""
SSH_KEY=""
REMOTE_PATH="~/coding/honours"

while [[ $# -gt 0 ]]; do
    case "$1" in
        pull|push)
            ACTION="$1"
            shift
            ;;
        --host)
            EC2_HOST="$2"
            shift 2
            ;;
        --key)
            SSH_KEY="$2"
            shift 2
            ;;
        --remote-path)
            REMOTE_PATH="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

if [ -z "$ACTION" ] || [ -z "$EC2_HOST" ]; then
    echo "Usage: $0 {pull|push} --host <user@ec2_ip> [--key <path_to_pem>] [--remote-path <path>]"
    exit 1
fi

SSH_CMD="ssh"
if [ -n "$SSH_KEY" ]; then
    SSH_CMD="ssh -i $SSH_KEY"
fi

RSYNC_OPTS=(
    -avhP
    --partial
    --append-verify
    --update
    --exclude="*.tmp"
    --exclude="*__pycache__*"
    --exclude=".git*"
    -e "$SSH_CMD"
)

if [ "$ACTION" = "pull" ]; then
    log_info "Synchronizing trained weights and adapters from EC2 (${EC2_HOST}) to local repo..."
    mkdir -p "${REPO_ROOT}/weights"

    # Sync primary weights directory
    rsync "${RSYNC_OPTS[@]}" \
        "${EC2_HOST}:${REMOTE_PATH}/weights/" \
        "${REPO_ROOT}/weights/"

    # Mirror LoRA adapters into research_track/finetune if present
    if [ -d "${REPO_ROOT}/weights/track_b_qwen3_vl_lora" ]; then
        mkdir -p "${REPO_ROOT}/research_track/finetune/track_b"
        rsync -a "${REPO_ROOT}/weights/track_b_qwen3_vl_lora/" "${REPO_ROOT}/research_track/finetune/track_b/adapter/" || true
    fi

    if [ -d "${REPO_ROOT}/weights/track_c_qwen3_1.7b_lora" ]; then
        mkdir -p "${REPO_ROOT}/research_track/finetune/track_c"
        rsync -a "${REPO_ROOT}/weights/track_c_qwen3_1.7b_lora/" "${REPO_ROOT}/research_track/finetune/track_c/adapter/" || true
    fi

    log_ok "Checkpoint pull complete! Verified local files:"
    ls -lh "${REPO_ROOT}/weights"

elif [ "$ACTION" = "push" ]; then
    log_info "Synchronizing local weights and assets to EC2 (${EC2_HOST})..."
    rsync "${RSYNC_OPTS[@]}" \
        "${REPO_ROOT}/weights/" \
        "${EC2_HOST}:${REMOTE_PATH}/weights/"

    log_ok "Checkpoint push complete!"
fi
