#!/usr/bin/env bash
# Staging template only. Review before execution on a fresh EC2 host.
set -euo pipefail

# Target: g4dn.xlarge (T4 16 GB). Raise the AWS G/VT vCPU quota before launch.
nvidia-smi || { echo "NVIDIA driver not ready; install the AWS-supported driver first."; exit 1; }
command -v tmux >/dev/null || { echo "Install tmux through the approved host provisioning path."; exit 1; }

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

mkdir -p "$HOME/ml-assets/campus"
uv venv --python 3.12 "$HOME/ml-assets/campus/.venv-ml"
export HF_HOME="$HOME/ml-assets/campus/hf"

# Install pinned ML dependencies
uv pip install --python "$HOME/ml-assets/campus/.venv-ml/bin/python" -r research_track/requirements-ml.txt

echo "Environment ready. Start durable download/evaluation jobs inside: tmux new -s campus-ml"
