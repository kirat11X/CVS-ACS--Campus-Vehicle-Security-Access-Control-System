"""G3-gated fast-plate-ocr fine-tuning launcher.

Validates the approval token and inputs, then runs the `fast-plate-ocr train` CLI with KERAS_BACKEND=torch
(TensorFlow in .venv-ml has no GPU; see PREREQ_REPORT.md section 2). Checkpoints stay outside the repository.

    APPROVE_FINETUNE=APPROVE_FINETUNE:A,C:local:0 python train_fast_plate_ocr.py \
        --manifest ~/ml-assets/campus/datasets/prepared/ocr_in_v1/manifest.json \
        --base-model ~/ml-assets/campus/models/fast-plate-ocr/global-v2/cct_s_v2_global.keras \
        --run-dir ~/ml-assets/campus/runs/track_a/<run_id> [--smoke-rows 256 --epochs 2]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CONFIGS = Path(__file__).resolve().parent / "configs"


def approved_for_track_a(token: str | None) -> bool:
    """APPROVE_FINETUNE:<tracks>:<local|ec2>:<budget_usd>, with A among the comma-separated tracks."""
    parts = (token or "").split(":")
    return len(parts) == 4 and parts[0] == "APPROVE_FINETUNE" and "A" in parts[1].split(",") and parts[2] in {"local", "ec2"}


def subset_csv(src: Path, dst: Path, rows: int) -> None:
    """First `rows` rows of src, with image paths re-based (they are relative to the CSV's directory)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open(newline="") as fh_in, dst.open("w", newline="") as fh_out:
        reader = csv.DictReader(fh_in)
        writer = csv.DictWriter(fh_out, fieldnames=reader.fieldnames)
        writer.writeheader()
        for i, row in enumerate(reader):
            if i >= rows:
                break
            row["image_path"] = os.path.relpath((src.parent / row["image_path"]).resolve(), dst.parent)
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True, help="prepared OCR manifest.json (train/val CSVs beside it)")
    parser.add_argument("--base-model", type=Path, required=True, help="pretrained .keras weights")
    parser.add_argument("--model-config", type=Path, default=None, help="defaults to <base-model stem>_model_config.yaml")
    parser.add_argument("--plate-config", type=Path, default=CONFIGS / "in_plate_config_v1.yaml")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke-rows", type=int, default=0, help="train/validate on the first N rows only")
    parser.add_argument("--approval-token", default=os.environ.get("APPROVE_FINETUNE"))
    args = parser.parse_args()

    if not approved_for_track_a(args.approval_token):
        raise SystemExit("G3 STOP: Track A training requires APPROVE_FINETUNE:<tracks incl. A>:<local|ec2>:<budget_usd>")
    if not args.manifest.is_file():
        raise SystemExit(f"missing prepared manifest: {args.manifest}")
    if not args.base_model.is_file():
        raise SystemExit(f"missing base model: {args.base_model}")
    model_config = args.model_config or args.base_model.with_name(f"{args.base_model.stem}_model_config.yaml")
    for path in (model_config, args.plate_config):
        if not path.is_file():
            raise SystemExit(f"missing config: {path}")
    if not args.run_dir.is_absolute() or "/ml-assets/campus/runs/" not in str(args.run_dir):
        raise SystemExit("run-dir must be outside the repository under ~/ml-assets/campus/runs/")

    data_dir = args.manifest.parent
    train_csv, val_csv = data_dir / "train.csv", data_dir / "val.csv"
    args.run_dir.mkdir(parents=True, exist_ok=True)
    if args.smoke_rows:
        train_csv, val_csv = (
            args.run_dir / "smoke_data" / "train.csv",
            args.run_dir / "smoke_data" / "val.csv",
        )
        subset_csv(data_dir / "train.csv", train_csv, args.smoke_rows)
        subset_csv(data_dir / "val.csv", val_csv, max(32, args.smoke_rows // 4))

    cli = Path(sys.executable).parent / "fast-plate-ocr"
    cmd = [
        str(cli), "train",
        "--model-config-file", str(model_config),
        "--plate-config-file", str(args.plate_config),
        "--annotations", str(train_csv),
        "--val-annotations", str(val_csv),
        "--weights-path", str(args.base_model),
        "--epochs", str(args.epochs),
        "--batch-size", str(args.batch_size),
        "--lr", str(args.lr),
        "--early-stopping-metric", "val_plate_acc",
        "--early-stopping-patience", str(args.patience),
        "--workers", str(args.workers),
        "--validate-dataset", "error",
        "--seed", str(args.seed),
        "--output-dir", str(args.run_dir),
    ]
    run_manifest = {
        "approval_token": args.approval_token,
        "command": cmd,
        "env": {"KERAS_BACKEND": "torch"},
        "dataset_manifest": str(args.manifest),
        "dataset_manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "base_model_sha256": hashlib.sha256(args.base_model.read_bytes()).hexdigest(),
        "smoke_rows": args.smoke_rows,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (args.run_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2))

    started = time.time()
    proc = subprocess.run(cmd, env={**os.environ, "KERAS_BACKEND": "torch"}, check=False)
    run_manifest.update({"returncode": proc.returncode, "wall_seconds": round(time.time() - started, 1)})
    (args.run_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2))
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
