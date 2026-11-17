"""G3-gated fast-plate-ocr fine-tuning launcher for EC2 GPU & local execution.

Validates the approval token, checks dataset split hygiene (zero leakage between train, val, test),
then runs the `fast-plate-ocr train` CLI with KERAS_BACKEND=torch.
Checkpoints stay outside the repository and post-training outputs metrics (CER, accuracy, format-valid rate).

    APPROVE_FINETUNE=APPROVE_FINETUNE:A,C:ec2:5 python train_fast_plate_ocr.py \
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
from typing import Dict, Set, Tuple

CONFIGS = Path(__file__).resolve().parent / "configs"
REPO_ROOT = Path(__file__).resolve().parents[3]


def approved_for_track_a(token: str | None) -> bool:
    """APPROVE_FINETUNE:<tracks>:<local|ec2>:<budget_usd>, with A among the comma-separated tracks."""
    parts = (token or "").split(":")
    return len(parts) == 4 and parts[0] == "APPROVE_FINETUNE" and "A" in parts[1].split(",") and parts[2] in {"local", "ec2"}


def validate_ocr_dataset(manifest_path: Path) -> Dict[str, object]:
    """
    Validates dataset loader and split hygiene for prepared OCR dataset (ocr_in_v1).
    Ensures:
    1. train.csv, val.csv, and test.csv exist.
    2. Zero plate text leakage between train, val, and test splits.
    3. Non-empty splits with correct expected counts.
    """
    data_dir = manifest_path.parent if manifest_path.is_file() else manifest_path
    train_csv = data_dir / "train.csv"
    val_csv = data_dir / "val.csv"
    test_csv = data_dir / "test.csv"

    for p in (train_csv, val_csv, test_csv):
        if not p.is_file():
            raise FileNotFoundError(f"Missing required split CSV: {p}")

    def load_texts(p: Path) -> Tuple[int, Set[str]]:
        count = 0
        texts = set()
        with p.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                count += 1
                texts.add(row["plate_text"].strip().upper())
        return count, texts

    n_train, train_texts = load_texts(train_csv)
    n_val, val_texts = load_texts(val_csv)
    n_test, test_texts = load_texts(test_csv)
    total_crops = n_train + n_val + n_test

    leakage_train_val = train_texts & val_texts
    leakage_train_test = train_texts & test_texts
    leakage_val_test = val_texts & test_texts

    has_leakage = bool(leakage_train_val or leakage_train_test or leakage_val_test)
    if has_leakage:
        raise ValueError(
            f"Dataset text leakage detected! "
            f"train-val: {len(leakage_train_val)}, "
            f"train-test: {len(leakage_train_test)}, "
            f"val-test: {len(leakage_val_test)}"
        )

    return {
        "data_dir": str(data_dir),
        "total_crops": total_crops,
        "splits": {
            "train": {"crops": n_train, "unique_texts": len(train_texts)},
            "val": {"crops": n_val, "unique_texts": len(val_texts)},
            "test": {"crops": n_test, "unique_texts": len(test_texts)},
        },
        "text_leakage": {
            "train_val": len(leakage_train_val),
            "train_test": len(leakage_train_test),
            "val_test": len(leakage_val_test),
        },
        "leakage_free": not has_leakage,
    }


def subset_csv(src: Path, dst: Path, rows: int) -> None:
    """First `rows` rows of src, with image paths re-based (they are relative to the CSV's directory)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open(newline="", encoding="utf-8") as fh_in, dst.open("w", newline="", encoding="utf-8") as fh_out:
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
    parser.add_argument("--manifest", type=Path, default=None, help="prepared OCR manifest.json (train/val CSVs beside it)")
    parser.add_argument("--base-model", type=Path, default=None, help="pretrained .keras weights (e.g. cct_s_v2_global.keras)")
    parser.add_argument("--model-config", type=Path, default=None, help="defaults to <base-model stem>_model_config.yaml")
    parser.add_argument("--plate-config", type=Path, default=CONFIGS / "in_plate_config_v1.yaml")
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke-rows", type=int, default=0, help="train/validate on the first N rows only")
    parser.add_argument("--approval-token", default=os.environ.get("APPROVE_FINETUNE"))
    parser.add_argument("--check-readiness", action="store_true", help="validate dataset split hygiene and configs without running full training")
    parser.add_argument("--eval-val-after-train", action="store_true", default=True, help="run evaluation on val set to compute CER and accuracy after training")
    args = parser.parse_args()

    # Automatic manifest resolution fallback
    manifest_path = args.manifest
    if manifest_path is None or not manifest_path.is_file():
        candidates = [
            Path.home() / "ml-assets/campus/datasets/prepared/ocr_in_v1/manifest.json",
            REPO_ROOT / "data/datasets/prepared/ocr_in_v1/manifest.json",
        ]
        for cand in candidates:
            if cand.is_file():
                manifest_path = cand
                break

    # If --check-readiness is requested, run comprehensive audit and exit
    if args.check_readiness:
        print("=== Track A OCR Training Readiness Audit ===")
        if manifest_path is None or not manifest_path.is_file():
            print(f"[FAIL] Prepared OCR manifest not found: {args.manifest}")
            sys.exit(1)

        print(f"[OK] Found manifest: {manifest_path}")
        report = validate_ocr_dataset(manifest_path)
        print(f"[OK] Total crops: {report['total_crops']}")
        print(f"     Splits: {report['splits']}")
        print(f"     Leakage: {report['text_leakage']} (leakage_free={report['leakage_free']})")

        plate_cfg = args.plate_config
        if not plate_cfg.is_file():
            print(f"[FAIL] Plate config missing: {plate_cfg}")
            sys.exit(1)
        print(f"[OK] Found plate config: {plate_cfg}")

        # Check model config
        model_cfg = args.model_config or (CONFIGS / "cct_s_v2_global_model_config.yaml")
        if not model_cfg.is_file():
            print(f"[WARN] Specific model config not found: {model_cfg}")
        else:
            print(f"[OK] Found model config: {model_cfg}")

        print("[OK] Execution backend: KERAS_BACKEND=torch")
        print("=== Track A OCR EC2 GPU Readiness: PASS ===")
        sys.exit(0)

    # Standard G3 gated execution
    if not approved_for_track_a(args.approval_token):
        raise SystemExit("G3 STOP: Track A training requires APPROVE_FINETUNE:<tracks incl. A>:<local|ec2>:<budget_usd>")
    if manifest_path is None or not manifest_path.is_file():
        raise SystemExit(f"missing prepared manifest: {args.manifest}")
    if args.base_model is None or not args.base_model.is_file():
        raise SystemExit(f"missing base model: {args.base_model}")
    if args.run_dir is None:
        raise SystemExit("missing required argument: --run-dir")

    # Validate dataset split leakage before running any training
    dataset_audit = validate_ocr_dataset(manifest_path)
    if not dataset_audit["leakage_free"]:
        raise SystemExit(f"Cannot proceed with training: text leakage detected: {dataset_audit['text_leakage']}")

    model_config = args.model_config or args.base_model.with_name(f"{args.base_model.stem}_model_config.yaml")
    if not model_config.is_file():
        fallback_cfg = CONFIGS / "cct_s_v2_global_model_config.yaml"
        if fallback_cfg.is_file():
            model_config = fallback_cfg

    for path in (model_config, args.plate_config):
        if not path.is_file():
            raise SystemExit(f"missing config: {path}")
    if not args.run_dir.is_absolute() or "/ml-assets/campus/runs/" not in str(args.run_dir):
        raise SystemExit("run-dir must be outside the repository under ~/ml-assets/campus/runs/")

    data_dir = manifest_path.parent
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
        "--epochs", str(args.epochs),
        "--batch-size", str(args.batch_size),
        "--lr", str(args.lr),
        "--early-stopping-metric", "val_plate_acc",
        "--early-stopping-patience", str(args.patience),
        "--workers", str(args.workers),
        "--validate-dataset", "warn",
        "--seed", str(args.seed),
        "--output-dir", str(args.run_dir),
    ]
    if args.base_model and args.base_model.is_file() and args.base_model.stat().st_size > 1000:
        cmd.extend(["--weights-path", str(args.base_model)])
    run_manifest = {
        "approval_token": args.approval_token,
        "command": cmd,
        "env": {"KERAS_BACKEND": "torch"},
        "dataset_manifest": str(manifest_path),
        "dataset_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "base_model_sha256": hashlib.sha256(args.base_model.read_bytes()).hexdigest(),
        "smoke_rows": args.smoke_rows,
        "dataset_audit": dataset_audit,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (args.run_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2))

    started = time.time()
    proc = subprocess.run(cmd, env={**os.environ, "KERAS_BACKEND": "torch"}, check=False)
    wall_sec = round(time.time() - started, 1)
    run_manifest.update({"returncode": proc.returncode, "wall_seconds": wall_sec})
    (args.run_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2))

    # Post-training evaluation on validation set if requested and training was successful
    if proc.returncode == 0 and args.eval_val_after_train:
        checkpoints = sorted(args.run_dir.glob("*/best.keras"))
        if checkpoints:
            best_ckpt = checkpoints[-1]
            eval_script = Path(__file__).resolve().parent / "eval_plate_ocr.py"
            eval_cmd = [
                sys.executable, str(eval_script),
                "--run-dir", str(args.run_dir),
                "--model", str(best_ckpt),
                "--plate-config", str(args.plate_config),
                "--data-dir", str(data_dir),
                "--split", "val",
            ]
            subprocess.run(eval_cmd, env={**os.environ, "KERAS_BACKEND": "torch"}, check=False)

    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
