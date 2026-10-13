"""Shared helpers for the Track C fine-tune scripts (research-only; no production wiring).

Invariant: the model proposes one of the 8 taxonomy codes only. It never emits ALLOW/REVIEW/ALERT.
Any output that is not exactly one of the codes is mapped to UNKNOWN, never NORMAL.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import os
import platform
import random
import subprocess
import time
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[2]  # .../research_track
ASSETS = Path.home() / "ml-assets" / "campus"
RUNS_C = ASSETS / "runs" / "C"
DATA_CSV = RESEARCH_ROOT / "track_c" / "fixtures" / "item_taxonomy_seed.csv"
QWEN_PATH = ASSETS / "models" / "Qwen3-1.7B"
MINILM_PATH = ASSETS / "models" / "paraphrase-multilingual-MiniLM-L12-v2"

CODES = [
    "TOBACCO_NICOTINE",
    "ALCOHOL",
    "RX_SCHEDULED_DRUG",
    "OTC_MEDICINE",
    "HAZARDOUS_CHEMICAL",
    "SHARP_OBJECT",
    "NORMAL",
    "UNKNOWN",
]
FORBIDDEN_OUTPUTS = {"ALLOW", "REVIEW", "ALERT"}

SYSTEM_PROMPT = (
    "You label one invoice line item with exactly one category code. "
    "Reply with the code only.\n"
    "TOBACCO_NICOTINE: cigarettes, bidi, gutka, pan masala, vapes, hookah, nicotine gum.\n"
    "ALCOHOL: beer, wine, spirits.\n"
    "RX_SCHEDULED_DRUG: prescription or scheduled medicines (sedatives, opioids, steroids, stimulants).\n"
    "OTC_MEDICINE: over-the-counter remedies, balms, bandages.\n"
    "HAZARDOUS_CHEMICAL: acids, solvents, bleach, kerosene, pesticides, poisons.\n"
    "SHARP_OBJECT: knives, blades, cutters, razors, scissors.\n"
    "NORMAL: ordinary groceries, food, toiletries, stationery, household goods.\n"
    "UNKNOWN: unreadable, garbled, generic or unidentifiable items."
)


def build_messages(item_text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Item: {item_text}"},
    ]


def render_prompt(tokenizer, item_text: str) -> str:
    """Chat-template prompt string, thinking disabled; identical at train and inference time."""
    return tokenizer.apply_chat_template(
        build_messages(item_text), tokenize=False, add_generation_prompt=True, enable_thinking=False
    )


def parse_output(text: str) -> tuple[str, bool]:
    """Map raw generation to a taxonomy code. Returns (code, was_valid). Invalid -> UNKNOWN, never NORMAL."""
    cleaned = (text or "").strip().split("<|im_end|>")[0].strip().strip(".").strip().upper()
    if cleaned in CODES:
        return cleaned, True
    return "UNKNOWN", False


def seed_everything(seed: int) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def scripts_sha() -> str:
    """Content hash of the scripts directory (the research_track tree has no git commits)."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*")):
        if p.is_file() and p.suffix in {".py", ".sh"}:
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(RESEARCH_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        if out.returncode != 0:  # rev-parse echoes "HEAD" on stdout when there are no commits
            return f"no-commit ({out.stderr.strip()[:80]}); see scripts_sha256"
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({exc})"


def lib_versions() -> dict:
    out = {"python": platform.python_version()}
    for p in ["torch", "transformers", "peft", "trl", "accelerate", "bitsandbytes", "sentence-transformers",
              "scikit-learn", "numpy", "pandas", "datasets"]:
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            out[p] = None
    try:
        import torch

        out["cuda_build"] = torch.version.cuda
        out["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        pass
    return out


def write_run_manifest(run_dir: Path, **fields) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    manifest.update(
        {
            "track": "C",
            "approval_token": "APPROVE_FINETUNE:A,C:local:0",
            "compute": "local RTX 4050 6GB",
            "git_sha": git_sha(),
            "scripts_sha256": scripts_sha(),
            "library_versions": lib_versions(),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "provenance": "synthetic LLM-authored items; measures fit to that distribution, not real invoice accuracy",
        }
    )
    manifest.update(fields)
    path.write_text(json.dumps(manifest, indent=2, default=str))
    return path


def load_split(split_dir: Path):
    import pandas as pd

    return {s: pd.read_csv(split_dir / f"{s}.csv", dtype=str, keep_default_na=False) for s in ("train", "val", "test")}
