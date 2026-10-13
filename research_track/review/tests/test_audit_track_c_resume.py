"""Audit 2026-10-13: Track C must not resume from a half-written checkpoint after an interruption.

c_train_lora.py resumed from transformers.trainer_utils.get_last_checkpoint(), which returns the
highest-numbered checkpoint-N directory by name. transformers 5.17 writes a checkpoint in place (no temp
dir + rename) and writes trainer_state.json last, so a spot interruption mid-save leaves a newer,
incomplete directory that the resume then loads.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "finetune" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import c_common  # noqa: E402


def make_checkpoints(root: Path) -> None:
    complete = root / "checkpoint-10"
    complete.mkdir(parents=True)
    (complete / "adapter_model.safetensors").write_bytes(b"\0" * 16)
    (complete / "trainer_state.json").write_text(json.dumps({"global_step": 10}))
    partial = root / "checkpoint-20"  # interrupted after the adapter, before trainer_state.json
    partial.mkdir()
    (partial / "adapter_model.safetensors").write_bytes(b"\0" * 8)
    torn = root / "checkpoint-30"  # interrupted while writing trainer_state.json
    torn.mkdir()
    (torn / "trainer_state.json").write_text('{"global_st')


def test_resume_picks_the_newest_complete_checkpoint(tmp_path):
    make_checkpoints(tmp_path)
    assert c_common.last_complete_checkpoint(tmp_path) == str(tmp_path / "checkpoint-10")
    assert c_common.last_complete_checkpoint(tmp_path / "missing") is None


def test_trainer_resumes_through_the_completeness_check():
    source = (SCRIPTS / "c_train_lora.py").read_text()
    assert "last_complete_checkpoint(" in source and "get_last_checkpoint(" not in source


def test_upstream_helper_would_pick_the_partial_one(tmp_path):
    trainer_utils = pytest.importorskip("transformers.trainer_utils")
    make_checkpoints(tmp_path)
    assert trainer_utils.get_last_checkpoint(str(tmp_path)).endswith("checkpoint-30")
