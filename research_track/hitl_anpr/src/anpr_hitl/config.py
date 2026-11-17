"""Typed configuration loaded from config.yaml (defaults here match the shipped file)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # research_track/hitl_anpr
DEFAULT_CONFIG = PACKAGE_ROOT / "config.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestConfig(_Section):
    fps: float = Field(2.0, gt=0)
    dedup_max_bits: int = Field(4, ge=0, le=64)
    blur_min_laplacian_var: float = Field(40.0, ge=0)
    jpeg_quality: int = Field(95, ge=50, le=100)


class SplitsConfig(_Section):
    gold_fraction: float = Field(0.20, ge=0, lt=1)
    val_fraction: float = Field(0.10, ge=0, lt=1)
    min_gold_videos: int = Field(10, ge=1)
    leakage_max_bits: int = Field(6, ge=0, le=64)


class PredictConfig(_Section):
    imgsz: int = 1280
    conf: float = Field(0.25, ge=0, le=1)
    iou: float = Field(0.7, gt=0, le=1)
    track_fps: float = Field(10.0, gt=0)
    tracker: str = "bytetrack.yaml"
    device: str | int = 0
    crop_pad: float = Field(0.08, ge=0, le=1)
    ocr_top_crops: int = Field(3, ge=1)


class OcrConfig(_Section):
    engine: Literal["rapidocr", "tesseract", "fast_plate_ocr"] = "rapidocr"
    rapidocr_version: str = "PP-OCRv6"
    rapidocr_rec_lang: str = "ch"
    rapidocr_rec_model_type: str = "small"
    rapidocr_det_limit_side: int = Field(160, ge=32)
    fallback: Literal["tesseract", "none"] = "tesseract"
    fallback_below_conf: float = Field(0.60, ge=0, le=1)
    low_char_conf: float = Field(0.50, ge=0, le=1)


class SelectWeights(_Section):
    low_confidence: float = 3.0
    track_disagreement: float = 2.5
    regex_failure: float = 2.0
    low_char_conf: float = 1.0
    rare_slice: float = 1.5


class SelectConfig(_Section):
    review_budget: int = Field(300, ge=1)
    audit_fraction: float = Field(0.10, ge=0, le=1)
    low_conf_band: tuple[float, float] = (0.25, 0.60)
    night_max_luma: float = 70
    max_group_fraction: float = Field(0.25, gt=0, le=1)
    weights: SelectWeights = SelectWeights()


class AutoAcceptConfig(_Section):
    enabled: bool = False
    min_audit_precision: float = Field(0.98, gt=0, le=1)
    min_audit_items: int = Field(150, ge=1)
    min_conf: float = Field(0.90, ge=0, le=1)


class ReviewConfig(_Section):
    reviewer_env: str = "ANPR_REVIEWER"
    auto_accept: AutoAcceptConfig = AutoAcceptConfig()


class TrainConfig(_Section):
    base_model: str = "yolo26s.pt"
    imgsz: int = 1280
    epochs: int = Field(40, ge=1)
    round_epochs: int = Field(20, ge=1)
    patience: int = Field(10, ge=0)
    batch: int = 4
    lr0: float = Field(0.001, gt=0)
    round_lr0: float = Field(0.0002, gt=0)
    round_warmup_epochs: float = Field(0.0, ge=0)
    optimizer: str = "AdamW"
    replay_fraction: float = Field(0.30, ge=0, lt=1)
    workers: int = 4
    fliplr: float = Field(0.0, ge=0, le=1)
    degrees: float = 3.0
    perspective: float = 0.0005
    hsv_v: float = 0.5
    close_mosaic: int = 5
    ocr_finetune_min_crops: int = 2000

    @field_validator("fliplr")
    @classmethod
    def _no_mirroring(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError("fliplr must be 0: a mirrored plate is not a valid plate")
        return value


class EvaluateConfig(_Section):
    imgsz: int = 1280
    iou: float = Field(0.5, gt=0, le=1)
    conf: float = Field(0.25, ge=0, le=1)
    bootstrap: int = Field(1000, ge=0)


class PromoteConfig(_Section):
    min_gain_map50_95: float = 1.0
    min_gain_exact: float = 2.0
    max_slice_regression: float = 2.0
    min_slice_n: int = 30
    require_significant: bool = False


class RunRoundConfig(_Section):
    stop_gain_pt: float = 0.5
    stop_patience_rounds: int = 2
    total_review_budget: int = 3000


class ExportConfig(_Section):
    imgsz: int = 640
    formats: list[Literal["onnx", "openvino"]] = ["onnx", "openvino"]
    parity_iou: float = 0.9
    parity_max_conf_drift: float = 0.02


class S3Config(_Section):
    enabled: bool = False
    bucket: str | None = None
    prefix: str = "campus-anpr-hitl"
    region: str = "ap-south-1"
    kms_key_id: str | None = None  # the stack's KmsKeyArn; the bucket policy refuses uploads under any other key


class Config(_Section):
    project: str = "campus-anpr-hitl"
    seed: int = 42
    data_root: Path = Path("~/ml-assets/campus/hitl")
    class_names: list[str] = ["license_plate"]
    ingest: IngestConfig = IngestConfig()
    splits: SplitsConfig = SplitsConfig()
    predict: PredictConfig = PredictConfig()
    ocr: OcrConfig = OcrConfig()
    select: SelectConfig = SelectConfig()
    review: ReviewConfig = ReviewConfig()
    train: TrainConfig = TrainConfig()
    evaluate: EvaluateConfig = EvaluateConfig()
    promote: PromoteConfig = PromoteConfig()
    run_round: RunRoundConfig = RunRoundConfig()
    export: ExportConfig = ExportConfig()
    s3: S3Config = S3Config()

    @field_validator("data_root")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return Path(value).expanduser()

    @field_validator("class_names")
    @classmethod
    def _single_class(cls, value: list[str]) -> list[str]:
        if len(value) != 1:
            raise ValueError("the pipeline detects exactly one class")
        return value

    def sha256(self) -> str:
        """Hash of the resolved configuration, recorded in every model card and registry entry."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def load_config(path: str | Path | None = None, **overrides) -> Config:
    """Load config.yaml (or `path`), then apply keyword overrides such as data_root=..."""
    path = Path(path) if path else DEFAULT_CONFIG
    raw = yaml.safe_load(path.read_text()) if path.is_file() else {}
    raw.update({k: v for k, v in overrides.items() if v is not None})
    return Config.model_validate(raw)
