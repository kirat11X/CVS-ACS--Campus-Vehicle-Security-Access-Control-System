"""G3-approved local YOLO plate-detector smoke/full launcher."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--patience", type=int, default=100)
    parser.add_argument("--name", default="plate_detector_smoke")
    parser.add_argument("--approval-token", default=os.environ.get("APPROVE_FINETUNE"))
    args = parser.parse_args()

    if args.approval_token != "APPROVE_FINETUNE:A,C:local:0":
        raise SystemExit("G3 STOP: expected approved token for local Track A/C run")
    if not (args.data / "data.yaml").is_file():
        raise SystemExit(f"missing detector data.yaml under {args.data}")
    if not args.run_dir.is_absolute() or "/ml-assets/campus/runs/" not in str(args.run_dir):
        raise SystemExit("run-dir must be outside the repository under ~/ml-assets/campus/runs/")

    from ultralytics import YOLO

    args.run_dir.mkdir(parents=True, exist_ok=True)
    model = YOLO(args.model)
    model.train(
        data=str(args.data / "data.yaml"),
        epochs=args.epochs,
        imgsz=640,
        batch=args.batch,
        device=0,
        workers=args.workers,
        patience=args.patience,
        project=str(args.run_dir),
        name=args.name,
        exist_ok=True,
        pretrained=True,
        seed=42,
        amp=True,
        verbose=True,
    )


if __name__ == "__main__":
    main()
