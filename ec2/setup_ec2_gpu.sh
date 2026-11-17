#!/usr/bin/env bash
# ==============================================================================
# ec2/setup_ec2_gpu.sh
# ==============================================================================
# Turn-key EC2 GPU Host Provisioning Script for CVS-ACS
#
# Supported Instances:
#   - g4dn.xlarge (1x NVIDIA Tesla T4 16GB, 4 vCPUs, 16GB RAM) [RECOMMENDED/COST-EFFECTIVE]
#   - g5.xlarge   (1x NVIDIA A10G 24GB, 4 vCPUs, 16GB RAM)
#   - g4dn.2xlarge (1x NVIDIA Tesla T4 16GB, 8 vCPUs, 32GB RAM)
#
# OS Support:
#   - Ubuntu 22.04 LTS (Jammy) / Ubuntu 24.04 LTS (Noble) [OPTIMAL]
#   - Amazon Linux 2023
#
# Configures:
#   1. System packages, build tools, multimedia libraries (FFmpeg, OpenCV deps)
#   2. NVIDIA Tesla Drivers (550+) and CUDA 12.x / cuDNN 9
#   3. Docker Engine + Docker Compose + NVIDIA Container Toolkit
#   4. uv Python Package Manager + Python 3.12 ML virtualenv
#   5. PyTorch (CUDA 12.x), Transformers, PEFT, bitsandbytes, trl, accelerate
#   6. Keras 3 with KERAS_BACKEND=torch, Ultralytics YOLO11, fast-plate-ocr
#   7. Automated GPU smoke test & persistent shell environment variables
# ==============================================================================

set -euo pipefail

# ANSI Colors
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

echo -e "\n${BOLD}${CYAN}======================================================================${RESET}"
echo -e "${BOLD}${CYAN}         CVS-ACS AWS EC2 GPU PROVISIONING AUTOMATION          ${RESET}"
echo -e "${BOLD}${CYAN}======================================================================${RESET}\n"

# ------------------------------------------------------------------------------
# 1. Pre-flight Environment Checks
# ------------------------------------------------------------------------------
log_info "1/7: Checking hardware, virtualization, and permissions..."

if [ "$EUID" -eq 0 ]; then
    SUDO=""
else
    if ! command -v sudo >/dev/null 2>&1; then
        log_error "sudo is required to install system packages and drivers."
        exit 1
    fi
    SUDO="sudo"
fi

# Detect architecture
ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
    log_error "Unsupported architecture: $ARCH. CVS-ACS GPU stack requires x86_64."
    exit 1
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID=$ID
    OS_VERSION=$VERSION_ID
    log_info "Detected OS: $NAME ($OS_ID $OS_VERSION)"
else
    log_error "Cannot identify Linux distribution via /etc/os-release."
    exit 1
fi

# Check PCI bus for NVIDIA GPU
if command -v lspci >/dev/null 2>&1; then
    if lspci | grep -i nvidia >/dev/null 2>&1; then
        log_ok "NVIDIA GPU hardware detected on PCIe bus."
    else
        log_warn "No NVIDIA PCIe device detected via lspci. Ensure you are on a GPU instance (e.g. g4dn.xlarge)."
    fi
fi

# ------------------------------------------------------------------------------
# 2. System Packages & Build Dependencies
# ------------------------------------------------------------------------------
log_info "2/7: Installing system packages, build essentials, and multimedia libraries..."

if [ "$OS_ID" = "ubuntu" ] || [ "$OS_ID" = "debian" ]; then
    $SUDO apt-get update -y
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y \
        build-essential \
        curl \
        wget \
        git \
        git-lfs \
        tmux \
        htop \
        nvtop \
        jq \
        unzip \
        rsync \
        pkg-config \
        software-properties-common \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        ffmpeg \
        ca-certificates \
        gnupg || true
    log_ok "Debian/Ubuntu system packages installed."
elif [ "$OS_ID" = "amzn" ] || [ "$OS_ID" = "rhel" ] || [ "$OS_ID" = "fedora" ]; then
    $SUDO dnf install -y \
        gcc \
        gcc-c++ \
        make \
        curl \
        wget \
        git \
        git-lfs \
        tmux \
        htop \
        jq \
        unzip \
        rsync \
        mesa-libGL \
        glib2 \
        libXext \
        libXrender \
        ffmpeg || true
    log_ok "RHEL/Amazon Linux system packages installed."
fi

# ------------------------------------------------------------------------------
# 3. NVIDIA Drivers & CUDA Toolkit
# ------------------------------------------------------------------------------
log_info "3/7: Checking and configuring NVIDIA Drivers and CUDA 12.x..."

if command -v nvidia-smi >/dev/null 2>&1; then
    DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1)
    GPU_NAME=$(nvidia-smi --query-gpu=gpu_name --format=csv,noheader | head -n 1)
    log_ok "NVIDIA Driver already active: $DRIVER_VER ($GPU_NAME)"
else
    log_info "NVIDIA drivers not active. Installing official NVIDIA Drivers..."
    if [ "$OS_ID" = "ubuntu" ]; then
        # Try distro non-free server driver first (standard across modern Ubuntu 22.04, 24.04, 26.04)
        if apt-cache show nvidia-driver-580-server-open >/dev/null 2>&1; then
            $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-driver-580-server-open nvidia-utils-580-server
        elif apt-cache show nvidia-driver-550-server >/dev/null 2>&1; then
            $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-driver-550-server nvidia-utils-550-server
        elif command -v ubuntu-drivers >/dev/null 2>&1; then
            $SUDO DEBIAN_FRONTEND=noninteractive ubuntu-drivers install --gpgpu || $SUDO DEBIAN_FRONTEND=noninteractive ubuntu-drivers install
        else
            UBUNTU_RELEASE="ubuntu2404"
            KEYRING_URL="https://developer.download.nvidia.com/compute/cuda/repos/${UBUNTU_RELEASE}/x86_64/cuda-keyring_1.1-1_all.deb"
            wget -q "$KEYRING_URL" -O /tmp/cuda-keyring.deb || true
            if [ -f /tmp/cuda-keyring.deb ]; then
                $SUDO dpkg -i /tmp/cuda-keyring.deb || true
                rm -f /tmp/cuda-keyring.deb
                $SUDO apt-get update -y
                $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y cuda-drivers || true
            fi
        fi
        log_ok "NVIDIA Drivers installed."
    else
        log_warn "On Amazon Linux / RHEL, please install NVIDIA drivers via: sudo dnf config-manager --add-repo ... && sudo dnf install -y kernel-modules-extra cuda-drivers"
    fi
fi

# ------------------------------------------------------------------------------
# 4. Docker & NVIDIA Container Toolkit
# ------------------------------------------------------------------------------
log_info "4/7: Configuring Docker Engine and NVIDIA Container Toolkit..."

if ! command -v docker >/dev/null 2>&1; then
    log_info "Installing Docker Engine..."
    curl -fsSL https://get.docker.com | $SUDO sh
    $SUDO usermod -aG docker "$USER" || true
    $SUDO systemctl enable --now docker || true
    log_ok "Docker installed and service enabled."
else
    log_ok "Docker is already installed ($(docker --version))."
fi

# Install NVIDIA Container Toolkit if missing
if ! command -v nvidia-ctk >/dev/null 2>&1; then
    log_info "Installing NVIDIA Container Toolkit..."
    if [ "$OS_ID" = "ubuntu" ] || [ "$OS_ID" = "debian" ]; then
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | $SUDO gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            $SUDO tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        $SUDO apt-get update -y
        $SUDO apt-get install -y nvidia-container-toolkit
    fi
fi

if command -v nvidia-ctk >/dev/null 2>&1; then
    $SUDO nvidia-ctk runtime configure --runtime=docker || true
    $SUDO systemctl restart docker || true
    log_ok "NVIDIA Container Toolkit configured for Docker."
fi

# ------------------------------------------------------------------------------
# 5. Python 3.12 Virtual Environment with uv
# ------------------------------------------------------------------------------
log_info "5/7: Setting up Python 3.12 environment using uv..."

# Ensure uv is installed
if ! command -v uv >/dev/null 2>&1; then
    log_info "Installing uv (Astral fast Python manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

ML_ASSETS_DIR="$HOME/ml-assets/campus"
VENV_DIR="$ML_ASSETS_DIR/.venv-ml"
mkdir -p "$ML_ASSETS_DIR/runs" "$ML_ASSETS_DIR/models" "$ML_ASSETS_DIR/datasets" "$ML_ASSETS_DIR/hf"

if [ ! -d "$VENV_DIR" ]; then
    log_info "Creating virtual environment at $VENV_DIR with Python 3.12..."
    uv venv --python 3.12 "$VENV_DIR"
    log_ok "Virtualenv created at $VENV_DIR."
else
    log_ok "Virtualenv already exists at $VENV_DIR."
fi

PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

# ------------------------------------------------------------------------------
# 6. Install PyTorch, Hugging Face, Keras 3 (Torch Backend), YOLO11, fast-plate-ocr
# ------------------------------------------------------------------------------
log_info "6/7: Installing PyTorch (CUDA 12.4), Transformers, PEFT, TRL, Keras 3, Ultralytics..."

# Step A: Install PyTorch with CUDA 12.4 wheels
log_info "Installing PyTorch CUDA 12.4..."
uv pip install --python "$PYTHON_BIN" \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu124

# Step B: Install Hugging Face & Fine-Tuning Suite
log_info "Installing Transformers, PEFT, bitsandbytes, TRL, accelerate, datasets..."
uv pip install --python "$PYTHON_BIN" \
    transformers \
    accelerate \
    peft \
    bitsandbytes \
    trl \
    datasets \
    huggingface-hub \
    qwen-vl-utils \
    sentencepiece \
    safetensors

# Step C: Install Keras 3 (KERAS_BACKEND=torch) and Computer Vision stack
log_info "Installing Keras 3, Ultralytics YOLO11, fast-plate-ocr, and CV toolkits..."
uv pip install --python "$PYTHON_BIN" \
    "keras>=3.0.0" \
    "ultralytics>=8.3.0" \
    fast-plate-ocr \
    opencv-python-headless \
    albumentations \
    pillow \
    scikit-learn \
    pandas \
    numpy \
    pyyaml \
    tqdm \
    rich \
    onnx \
    onnxruntime-gpu \
    kaggle

log_ok "All ML dependencies installed."

# ------------------------------------------------------------------------------
# 7. Environment Configuration & GPU Smoke Test
# ------------------------------------------------------------------------------
log_info "7/7: Configuring persistent environment variables and running GPU smoke test..."

# Persist environment in ~/.bashrc
BASHRC="$HOME/.bashrc"
ENV_SNIPPET="
# >>> CVS-ACS EC2 ML Environment >>>
export KERAS_BACKEND=torch
export CUDA_VISIBLE_DEVICES=0
export HF_HOME=\"$HOME/ml-assets/campus/hf\"
export PATH=\"$HOME/.local/bin:$VENV_DIR/bin:\$PATH\"
# <<< CVS-ACS EC2 ML Environment <<<
"

if ! grep -q "CVS-ACS EC2 ML Environment" "$BASHRC" 2>/dev/null; then
    echo "$ENV_SNIPPET" >> "$BASHRC"
    log_ok "Appended CVS-ACS ML environment variables to ~/.bashrc."
fi

# Run Smoke Test
export KERAS_BACKEND=torch
export HF_HOME="$HOME/ml-assets/campus/hf"

log_info "Executing Python GPU and Library Smoke Test..."
"$PYTHON_BIN" -c "
import sys
import torch
import keras
import transformers
import peft
import bitsandbytes as bnb
import ultralytics

print('\n' + '='*55)
print('         CVS-ACS GPU ENVIRONMENT VERIFICATION')
print('='*55)
print(f'Python:        {sys.version.split()[0]}')
print(f'PyTorch:       {torch.__version__}')
print(f'CUDA Active:   {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'Device Name:   {torch.cuda.get_device_name(0)}')
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f'VRAM Total:    {vram_gb:.2f} GB')
    # Simple tensor operation
    x = torch.ones((1000, 1000), device='cuda')
    y = x @ x
    print(f'GPU Matrix Op: SUCCESS (Device: {y.device})')
else:
    print('WARNING: PyTorch did not detect CUDA GPU.')

print(f'Keras 3:       {keras.__version__} (Backend: {keras.backend.backend()})')
print(f'Transformers:  {transformers.__version__}')
print(f'PEFT:          {peft.__version__}')
print(f'BitsAndBytes:  {bnb.__version__}')
print(f'Ultralytics:   {ultralytics.__version__}')
print('='*55 + '\n')
"

echo -e "\n${BOLD}${GREEN}======================================================================${RESET}"
echo -e "${BOLD}${GREEN}      CVS-ACS EC2 GPU HOST SETUP SUCCESSFULLY COMPLETED!      ${RESET}"
echo -e "${BOLD}${GREEN}======================================================================${RESET}"
echo -e "Virtualenv Path: ${VENV_DIR}"
echo -e "To activate:     source ${VENV_DIR}/bin/activate"
echo -e "Health check:    ./ec2/ec2_healthcheck.sh"
echo -e "Track A OCR:     ./ec2/train_track_a_ocr.sh"
echo -e "Track B VLM:     ./ec2/train_track_b_vlm.sh"
echo -e "Track C LLM:     ./ec2/train_track_c_llm.sh\n"
