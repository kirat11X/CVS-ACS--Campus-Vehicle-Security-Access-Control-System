"""Train or fine-tune the YOLO plate detector with resume-safe checkpoints.

After every epoch last.pt is load-tested and atomically copied to checkpoints/last.verified.pt (and to S3
when enabled). Re-running the same run directory resumes; a torn last.pt (power loss, spot reclaim
mid-write) is replaced by the verified copy first. A STOP file or a hot GPU ends training cleanly.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from anpr_hitl.config import Config
from anpr_hitl.store import atomic_write_json, read_json

MAX_GPU_TEMP_C = 87
MIN_MEM_AVAILABLE_GIB = 4.0


def indian_road_augmentations() -> list:
    """Photometric augmentations for Indian roads; geometry stays with Ultralytics (degrees, perspective)."""
    import albumentations as A

    return [
        A.MotionBlur(blur_limit=(3, 9), p=0.15),                                    # moving vehicles
        A.RandomBrightnessContrast(brightness_limit=(-0.35, 0.25), contrast_limit=(-0.3, 0.3), p=0.3),
        A.RandomGamma(gamma_limit=(60, 160), p=0.25),                                # night / overexposure
        A.RandomRain(slant_range=(-10, 10), drop_width=1, blur_value=3, brightness_coefficient=0.85, p=0.05),
        A.RandomFog(fog_coef_range=(0.05, 0.25), p=0.05),
        A.RandomSunFlare(src_radius=120, num_flare_circles_range=(2, 5), p=0.03),     # headlight glare
        A.ImageCompression(quality_range=(25, 90), p=0.3),                           # CCTV JPEG artefacts
        A.GaussNoise(std_range=(0.02, 0.06), p=0.1),                                 # low-light sensor noise
        A.CLAHE(p=0.05),
        A.ToGray(p=0.02),
    ]


def preflight() -> list[str]:
    """Reasons not to start GPU training now (laptop habits from the research track)."""
    problems = []
    ac = Path("/sys/class/power_supply/AC/online")
    if ac.is_file() and ac.read_text().strip() != "1":
        problems.append("not on AC power")
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:") and int(line.split()[1]) / 2**20 < MIN_MEM_AVAILABLE_GIB:
            problems.append(f"MemAvailable below {MIN_MEM_AVAILABLE_GIB} GiB")
    return problems


def gpu_temperature() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10)
        return int(out.stdout.split()[0])
    except Exception:  # noqa: BLE001 - no GPU tool: no temperature guard
        return None


def checkpoint_kind(path: Path) -> str | None:
    """'resumable' (mid-training: epoch >= 0, optimizer state), 'final' (stripped), or None (unreadable).

    Ultralytics 8.4 writes per-epoch checkpoints with model=None and the weights in 'ema'; the stripped final
    checkpoint has epoch -1 and no optimizer, so it cannot be resumed from.
    """
    try:
        import torch

        ckpt = torch.load(path, map_location="cpu", weights_only=False)
    except Exception:  # noqa: BLE001 - any failure means "not a usable checkpoint"
        return None
    if not isinstance(ckpt, dict) or (ckpt.get("model") is None and ckpt.get("ema") is None):
        return None
    return "resumable" if ckpt.get("epoch", -1) >= 0 and ckpt.get("optimizer") is not None else "final"


@dataclass
class TrainResult:
    run_dir: Path
    best: Path
    last: Path
    resumed: bool
    seconds: float
    stopped_reason: str | None = None
    final_metrics: dict = field(default_factory=dict)


class _Guard:
    """Ultralytics callbacks: verify + mirror the checkpoint every epoch, stop on STOP file or heat."""

    def __init__(self, run_dir: Path, cfg: Config):
        self.run_dir, self.cfg = run_dir, cfg
        self.verified = run_dir / "checkpoints" / "last.verified.pt"
        self.stopped_reason: str | None = None

    def on_fit_epoch_end(self, trainer) -> None:
        last = Path(trainer.wdir) / "last.pt"
        # Only a resumable checkpoint replaces the verified copy (Ultralytics also fires this callback once more
        # after stripping the final checkpoint).
        if last.is_file() and checkpoint_kind(last) == "resumable":
            self.verified.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.verified.with_suffix(".tmp")
            shutil.copyfile(last, tmp)
            tmp.replace(self.verified)
            if self.cfg.s3.enabled:
                from anpr_hitl.cloud import upload_checkpoint

                upload_checkpoint(self.cfg, self.verified, self.run_dir.name)
        metrics = {k: round(float(v), 5) for k, v in (trainer.metrics or {}).items()}
        atomic_write_json(self.run_dir / "progress.json", {"epoch": trainer.epoch + 1, "epochs": trainer.epochs,
                                                           "metrics": metrics, "ts": time.time()})
        reason = None
        if (self.run_dir / "STOP").exists():
            reason = "STOP file"
        temp = gpu_temperature()
        if temp is not None and temp >= MAX_GPU_TEMP_C:
            reason = f"GPU at {temp} C"
        if reason:
            self.stopped_reason = reason
            trainer.stop = True


def train_detector(data_yaml: Path, base_weights: Path, run_dir: Path, cfg: Config, epochs: int | None = None,
                   batch: int | None = None, imgsz: int | None = None, device=None, fraction: float = 1.0,
                   extra_callbacks: dict | None = None, finetune: bool = False) -> TrainResult:
    from anpr_hitl.yolo import YOLO

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    weights_dir = run_dir / "train" / "weights"
    last, verified = weights_dir / "last.pt", run_dir / "checkpoints" / "last.verified.pt"
    stopped_marker = run_dir / "STOPPED.json"
    guard = _Guard(run_dir, cfg)
    started = time.time()
    (run_dir / "STOP").unlink(missing_ok=True)  # a STOP request applies to the run that saw it, not the resume
    if not last.is_file() and not (run_dir / "DONE.json").is_file() and checkpoint_kind(verified) == "resumable":
        # A new machine after a spot reclaim gets only the verified copy (last.pt may have been mid-write).
        last.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(verified, last)
    resumed = last.is_file() and not (run_dir / "DONE.json").is_file()
    if resumed and stopped_marker.is_file():
        # A guarded stop ends Ultralytics' loop, which then strips the optimizer from last.pt: resume from the
        # verified copy taken at the last completed epoch instead.
        if checkpoint_kind(verified) != "resumable":
            raise RuntimeError(f"run was stopped but {verified} is not resumable")
        shutil.copyfile(verified, last)
        stopped_marker.unlink()
    if resumed and checkpoint_kind(last) == "final":
        # Training finished (the final checkpoint was stripped) but the run died before DONE.json was written.
        best = weights_dir / "best.pt"
        atomic_write_json(run_dir / "DONE.json", {"best": str(best), "seconds": 0, "metrics": {}, "recovered": True})
        return TrainResult(run_dir=run_dir, best=best, last=last, resumed=False, seconds=0.0)
    if resumed:
        if checkpoint_kind(last) != "resumable":
            if checkpoint_kind(verified) != "resumable":
                raise RuntimeError(f"{last} is unusable and there is no verified checkpoint to resume from")
            shutil.copyfile(verified, last)
        model = YOLO(str(last))
        model.add_callback("on_fit_epoch_end", guard.on_fit_epoch_end)
        for event, fn in (extra_callbacks or {}).items():
            model.add_callback(event, fn)
        model.train(resume=True)
    else:
        t = cfg.train
        # Fine-tuning the champion: a smaller learning rate and no warmup (Ultralytics' warmup starts the bias
        # learning rate at 0.1, which knocks a converged detector off its optimum in the first epoch).
        lr = {"lr0": t.round_lr0, "warmup_epochs": t.round_warmup_epochs} if finetune else {"lr0": t.lr0}
        model = YOLO(str(base_weights))
        model.add_callback("on_fit_epoch_end", guard.on_fit_epoch_end)
        for event, fn in (extra_callbacks or {}).items():
            model.add_callback(event, fn)
        model.train(
            data=str(data_yaml), epochs=epochs or t.epochs, imgsz=imgsz or t.imgsz, batch=batch or t.batch,
            **lr, optimizer=t.optimizer, patience=t.patience, fliplr=t.fliplr, flipud=0.0, degrees=t.degrees,
            perspective=t.perspective, hsv_v=t.hsv_v, close_mosaic=t.close_mosaic, seed=cfg.seed, deterministic=True,
            workers=t.workers, device=cfg.predict.device if device is None else device, project=str(run_dir),
            name="train", exist_ok=True, augmentations=indian_road_augmentations(), amp=True, plots=True,
            fraction=fraction, verbose=False,
        )
    trainer = model.trainer
    result = TrainResult(
        run_dir=run_dir, best=Path(trainer.best), last=Path(trainer.last), resumed=resumed,
        seconds=round(time.time() - started, 1), stopped_reason=guard.stopped_reason,
        final_metrics={k: round(float(v), 5) for k, v in (trainer.metrics or {}).items()},
    )
    if guard.stopped_reason is None:
        atomic_write_json(run_dir / "DONE.json", {"best": str(result.best), "seconds": result.seconds,
                                                  "metrics": result.final_metrics})
    else:
        atomic_write_json(stopped_marker, {"reason": guard.stopped_reason, "ts": time.time()})
    return result


def run_status(run_dir: Path) -> dict:
    return {"done": read_json(Path(run_dir) / "DONE.json"), "progress": read_json(Path(run_dir) / "progress.json")}
