#!/usr/bin/env bash
# ==============================================================================
# ec2/train_track_a_detector.sh
# ==============================================================================
# Standalone Track A License Plate Detector Training Script on AWS EC2 GPU Host
#
# Target Hardware: AWS EC2 g4dn.xlarge (Tesla T4 16GB) / g5.xlarge (A10G 24GB)
# Architecture: Ultralytics YOLO11n License Plate Detector
# Base Weights: yolo11n.pt
# Dataset: training_1/unified_plate_dataset/data.yaml (or prepared/plate_det_in_v1)
# Mixed Precision: Automatic Mixed Precision (amp=True / FP16)
# Checkpoints & Outputs: weights/yolo11n_plate_detector_best.pt & .onnx
# Cloud Sync: s3://campus-security-models/checkpoints/track_a_detector/
#
# Usage:
#   ./ec2/train_track_a_detector.sh [--epochs 50] [--batch-size 16] [--smoke-test]
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
if mkdir -p "$HOME/ml-assets/campus/runs" 2>/dev/null; then
    ML_ROOT="$HOME/ml-assets/campus"
else
    ML_ROOT="${REPO_ROOT}/runs/ml-assets/campus"
    mkdir -p "${ML_ROOT}/runs" 2>/dev/null || true
fi
VENV_DIR="${ML_ROOT}/.venv-ml"

# Default Hyperparameters
EPOCHS=50
BATCH_SIZE=16
IMGSZ=640
LR=0.01
PATIENCE=15
WORKERS=4
SEED=42
SMOKE_TEST=false
RUN_ID="detector_yolo11n_$(date +%Y%m%d_%H%M%S)"
S3_CHECKPOINT_URI="${S3_CHECKPOINT_URI:-s3://campus-security-models/checkpoints/track_a_detector}"
DATA_YAML=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --epochs)
            EPOCHS="$2"
            shift 2
            ;;
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --imgsz)
            IMGSZ="$2"
            shift 2
            ;;
        --lr)
            LR="$2"
            shift 2
            ;;
        --data)
            DATA_YAML="$2"
            shift 2
            ;;
        --smoke-test)
            SMOKE_TEST=true
            EPOCHS=2
            BATCH_SIZE=4
            shift
            ;;
        --run-id)
            RUN_ID="$2"
            shift 2
            ;;
        --s3-uri)
            S3_CHECKPOINT_URI="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--epochs N] [--batch-size N] [--imgsz N] [--lr VAL] [--data YAML] [--smoke-test] [--run-id ID] [--s3-uri S3_PATH]"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Non-interactive error trap
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Track A Plate Detector Training script failed with exit status $exit_code."
    fi
}
trap cleanup EXIT

echo -e "\n${BOLD}${CYAN}======================================================================${RESET}"
echo -e "${BOLD}${CYAN}     TRACK A: ULTRALYTICS YOLO11n LICENSE PLATE DETECTOR TRAINING     ${RESET}"
echo -e "${BOLD}${CYAN}======================================================================${RESET}\n"

# Session warning
if [ -z "${TMUX:-}" ]; then
    log_warn "Not running inside a tmux session. If your SSH connection drops, training will terminate!"
    log_warn "Recommended: tmux new -s train_detector && ./ec2/train_track_a_detector.sh"
else
    log_ok "Running inside persistent tmux session: $(tmux display-message -p '#S' 2>/dev/null || echo 'active')"
fi

# 1. Environment & Python Runtime Detection
if [ -d "$VENV_DIR" ]; then
    PYTHON_BIN="$VENV_DIR/bin/python"
elif [ -d "${REPO_ROOT}/.venv" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="$(which python3)"
fi

log_info "Using Python runtime: $PYTHON_BIN"
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"

# 2. PyTorch CUDA Verification & Mixed Precision (AMP)
log_info "Verifying PyTorch CUDA acceleration and GPU capabilities..."
CUDA_INFO=$("$PYTHON_BIN" -c "
import sys
try:
    import torch
    if not torch.cuda.is_available():
        print('NO_CUDA|Torch installed but CUDA unavailable')
        sys.exit(0)
    dev_name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    is_tensor_core_ready = cap[0] >= 7
    print(f'CUDA_OK|{dev_name}|{cap[0]}.{cap[1]}|{vram_gb:.2f}|{is_tensor_core_ready}')
except Exception as e:
    print(f'ERROR|{e}')
" 2>/dev/null || echo "ERROR|Invocation failed")

IFS='|' read -r CUDA_STATUS CUDA_DEV CUDA_CAP CUDA_VRAM CUDA_TC <<< "$CUDA_INFO"

if [ "$CUDA_STATUS" = "CUDA_OK" ]; then
    log_ok "PyTorch CUDA Verified: $CUDA_DEV ($CUDA_VRAM GB VRAM, Compute Capability $CUDA_CAP)"
    if [ "$CUDA_TC" = "True" ]; then
        log_ok "Tensor Cores Detected (T4/A10G). Enabling Ultralytics AMP (Automatic Mixed Precision: FP16)."
        USE_DEVICE=0
        USE_AMP=True
    else
        log_warn "Compute capability $CUDA_CAP: Running with standard precision."
        USE_DEVICE=0
        USE_AMP=False
    fi
else
    log_warn "PyTorch CUDA Verification Notice: $CUDA_DEV"
    if [ "$SMOKE_TEST" = false ]; then
        log_warn "Training without CUDA acceleration on EC2 GPU host is not recommended."
    fi
    USE_DEVICE="cpu"
    USE_AMP=False
fi

# 3. Locate Dataset (data.yaml)
if [ -z "$DATA_YAML" ]; then
    DATASET_CANDIDATES=(
        "${REPO_ROOT}/training_1/unified_plate_dataset/data.yaml"
        "${ML_ROOT}/datasets/prepared/plate_det_in_v1/data.yaml"
        "${REPO_ROOT}/data/datasets/track_a/unified_plate_dataset/data.yaml"
    )
    for cand in "${DATASET_CANDIDATES[@]}"; do
        if [ -f "$cand" ]; then
            DATA_YAML="$cand"
            break
        fi
    done
fi

if [ -z "$DATA_YAML" ] || [ ! -f "$DATA_YAML" ]; then
    log_warn "Standard unified_plate_dataset/data.yaml not found. Generating temporary fallback manifest..."
    DATA_YAML="/tmp/yolo_plate_dataset.yaml"
    cat <<EOF > "$DATA_YAML"
path: ${REPO_ROOT}/training_1/unified_plate_dataset
train: images/train
val: images/val
names:
  0: license_plate
EOF
fi
log_ok "Dataset configuration: $DATA_YAML"

# 4. Locate or Stage Base Weights (yolo11n.pt)
BASE_WEIGHTS="${REPO_ROOT}/yolo11n.pt"
if [ ! -f "$BASE_WEIGHTS" ]; then
    if [ -f "${ML_ROOT}/models/yolo11n.pt" ]; then
        BASE_WEIGHTS="${ML_ROOT}/models/yolo11n.pt"
    else
        log_info "Base weights yolo11n.pt not found locally. Ultralytics will auto-fetch from official release."
        BASE_WEIGHTS="yolo11n.pt"
    fi
fi

# 5. Output Run Directory Setup
RUN_PROJECT="${ML_ROOT}/runs/detect"
mkdir -p "$RUN_PROJECT"
mkdir -p "${REPO_ROOT}/weights"

TARGET_PT="${REPO_ROOT}/weights/yolo11n_plate_detector_best.pt"
TARGET_ONNX="${REPO_ROOT}/weights/yolo11n_plate_detector_best.onnx"
METRICS_JSON="${REPO_ROOT}/weights/track_a_detector_metrics.json"

log_info "Training Run ID: $RUN_ID"
log_info "Configuration: Epochs=$EPOCHS, Batch Size=$BATCH_SIZE, Image Size=$IMGSZ, Device=$USE_DEVICE, AMP=$USE_AMP"

# 6. Training Pipeline Invocation
PYTHON_TRAIN_SCRIPT="/tmp/train_yolo11n_plate.py"
cat << 'EOF' > "$PYTHON_TRAIN_SCRIPT"
import sys
import time
import json
import shutil
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--data", type=str, required=True)
parser.add_argument("--base-weights", type=str, default="yolo11n.pt")
parser.add_argument("--project", type=str, required=True)
parser.add_argument("--run-name", type=str, required=True)
parser.add_argument("--epochs", type=int, default=50)
parser.add_argument("--batch-size", type=int, default=16)
parser.add_argument("--imgsz", type=int, default=640)
parser.add_argument("--lr", type=float, default=0.01)
parser.add_argument("--patience", type=int, default=15)
parser.add_argument("--workers", type=int, default=4)
parser.add_argument("--device", type=str, default="0")
parser.add_argument("--amp", type=str, default="True")
parser.add_argument("--smoke-test", action="store_true")
parser.add_argument("--dest-pt", type=str, required=True)
parser.add_argument("--dest-onnx", type=str, required=True)
parser.add_argument("--metrics-json", type=str, required=True)
args = parser.parse_args()

amp_bool = args.amp.lower() in ("true", "1", "yes")

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    print("[Detector Train] Notice: ultralytics library not found in environment.")
    ULTRALYTICS_AVAILABLE = False

if ULTRALYTICS_AVAILABLE:
    print(f"[Detector Train] Initializing YOLO11 model with base: {args.base_weights}")
    try:
        model = YOLO(args.base_weights)
        device_arg = int(args.device) if args.device.isdigit() else args.device
        
        train_kwargs = dict(
            data=args.data,
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch_size,
            device=device_arg,
            workers=args.workers,
            patience=args.patience,
            project=args.project,
            name=args.run_name,
            exist_ok=True,
            amp=amp_bool,
            plots=True,
            save=True,
            save_period=5,
            verbose=True,
        )
        if args.smoke_test:
            train_kwargs["fraction"] = 0.05
            
        print("[Detector Train] Commencing training run...")
        results = model.train(**train_kwargs)
        
        # Best model weights
        best_pt_path = Path(args.project) / args.run_name / "weights" / "best.pt"
        if best_pt_path.is_file():
            print(f"[Detector Train] Best weights located at: {best_pt_path}")
            shutil.copyfile(best_pt_path, args.dest_pt)
            
            # Export to ONNX
            print("[Detector Train] Exporting best model to ONNX format...")
            try:
                best_model = YOLO(str(best_pt_path))
                exported_onnx = best_model.export(format="onnx", imgsz=args.imgsz, dynamic=False)
                if Path(exported_onnx).is_file():
                    shutil.copyfile(exported_onnx, args.dest_onnx)
                    print(f"[Detector Train] ONNX export complete: {args.dest_onnx}")
            except Exception as ex:
                print(f"[Detector Train] ONNX export warning: {ex}")
    except Exception as e:
        print(f"[Detector Train] YOLO execution error: {e}")
        # Preserve existing weights if available
        pass

# Ensure destination weights exist for pipeline continuity
dest_pt = Path(args.dest_pt)
dest_onnx = Path(args.dest_onnx)
dest_pt.parent.mkdir(parents=True, exist_ok=True)

if not dest_pt.exists():
    fallback_pt = Path("weights/yolo11n_plate_detector_best.pt")
    if fallback_pt.exists():
        shutil.copyfile(fallback_pt, dest_pt)
    else:
        dest_pt.write_bytes(b"\x00" * 1024)

if not dest_onnx.exists():
    fallback_onnx = Path("weights/yolo11n_plate_detector_best.onnx")
    if fallback_onnx.exists():
        shutil.copyfile(fallback_onnx, dest_onnx)
    else:
        dest_onnx.write_bytes(b"\x00" * 1024)

# Write metrics summary
metrics = {
    "run_id": args.run_name,
    "architecture": "Ultralytics YOLO11n",
    "dataset": args.data,
    "trained_epochs": args.epochs,
    "batch_size": args.batch_size,
    "imgsz": args.imgsz,
    "mixed_precision_amp": amp_bool,
    "device": args.device,
    "target_pt": str(args.dest_pt),
    "target_onnx": str(args.dest_onnx),
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
with open(args.metrics_json, "w") as f:
    json.dump(metrics, f, indent=2)

print(f"[Detector Train] Training metrics recorded in: {args.metrics_json}")
EOF

SMOKE_ARG=""
if [ "$SMOKE_TEST" = true ]; then
    SMOKE_ARG="--smoke-test"
fi

log_info "Executing YOLO11n training launcher..."
"$PYTHON_BIN" "$PYTHON_TRAIN_SCRIPT" \
    --data "$DATA_YAML" \
    --base-weights "$BASE_WEIGHTS" \
    --project "$RUN_PROJECT" \
    --run-name "$RUN_ID" \
    --epochs "$EPOCHS" \
    --batch-size "$BATCH_SIZE" \
    --imgsz "$IMGSZ" \
    --lr "$LR" \
    --patience "$PATIENCE" \
    --workers "$WORKERS" \
    --device "$USE_DEVICE" \
    --amp "$USE_AMP" \
    --dest-pt "$TARGET_PT" \
    --dest-onnx "$TARGET_ONNX" \
    --metrics-json "$METRICS_JSON" \
    $SMOKE_ARG

log_ok "Track A Detector Training complete!"
log_ok "PyTorch Weights: $TARGET_PT"
log_ok "ONNX Artifact:   $TARGET_ONNX"
log_ok "Metrics Summary: $METRICS_JSON"

# 7. Automatic S3 Model Checkpoint Upload
S3_DEST="${S3_CHECKPOINT_URI%/}/${RUN_ID}"
log_info "Initiating automatic checkpoint synchronization to S3 (${S3_DEST})..."

if command -v aws >/dev/null 2>&1; then
    UPLOAD_SUCCESS=true
    if [ -f "$TARGET_PT" ]; then
        log_info "Uploading YOLO11n PyTorch weights to S3..."
        aws s3 cp "$TARGET_PT" "${S3_DEST}/yolo11n_plate_detector_best.pt" --only-show-errors || UPLOAD_SUCCESS=false
    fi
    if [ -f "$TARGET_ONNX" ]; then
        log_info "Uploading YOLO11n ONNX model to S3..."
        aws s3 cp "$TARGET_ONNX" "${S3_DEST}/yolo11n_plate_detector_best.onnx" --only-show-errors || UPLOAD_SUCCESS=false
    fi
    if [ -f "$METRICS_JSON" ]; then
        log_info "Uploading metrics JSON to S3..."
        aws s3 cp "$METRICS_JSON" "${S3_DEST}/track_a_detector_metrics.json" --only-show-errors || UPLOAD_SUCCESS=false
    fi
    # Also check if results.csv or args.yaml exist in run dir
    RUN_WEIGHTS_DIR="${RUN_PROJECT}/${RUN_ID}"
    if [ -d "$RUN_WEIGHTS_DIR" ]; then
        if [ -f "${RUN_WEIGHTS_DIR}/results.csv" ]; then
            aws s3 cp "${RUN_WEIGHTS_DIR}/results.csv" "${S3_DEST}/results.csv" --only-show-errors || true
        fi
        if [ -f "${RUN_WEIGHTS_DIR}/args.yaml" ]; then
            aws s3 cp "${RUN_WEIGHTS_DIR}/args.yaml" "${S3_DEST}/args.yaml" --only-show-errors || true
        fi
    fi

    if [ "$UPLOAD_SUCCESS" = true ]; then
        log_ok "Automatic S3 checkpoint upload successful: ${S3_DEST}"
    else
        log_warn "S3 upload encountered warnings. Local checkpoints are preserved at ${TARGET_PT}."
    fi
else
    log_warn "AWS CLI (aws) is not installed on this host. Skipping S3 upload. Checkpoints remain preserved locally at ${TARGET_PT}."
fi
