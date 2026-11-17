"""Resume safety: checkpoint classification (fast) and a real stop + torn-write + resume run (GPU)."""

from pathlib import Path

import pytest
import torch

from anpr_hitl.train import checkpoint_kind


def test_checkpoint_kind_matches_ultralytics_8_4_layouts(tmp_path):
    cases = {
        "per_epoch.pt": ({"epoch": 3, "model": None, "ema": {"w": 1}, "optimizer": {"state": {}}}, "resumable"),
        "stripped.pt": ({"epoch": -1, "model": {"w": 1}, "ema": None, "optimizer": None}, "final"),
        "weights_only.pt": ({"epoch": 7, "model": {"w": 1}}, "final"),
        "empty.pt": ({"epoch": 3, "model": None, "ema": None}, None),
    }
    for name, (obj, expected) in cases.items():
        torch.save(obj, tmp_path / name)
        assert checkpoint_kind(tmp_path / name) == expected, name
    torn = tmp_path / "torn.pt"
    torn.write_bytes((tmp_path / "per_epoch.pt").read_bytes()[:40])
    assert checkpoint_kind(torn) is None
    assert checkpoint_kind(tmp_path / "missing.pt") is None



class _FakeYOLO:
    calls: list = []

    def __init__(self, weights):
        self.trainer = None

    def add_callback(self, event, fn):
        pass

    def train(self, **kwargs):
        _FakeYOLO.calls.append(kwargs)
        out = Path(kwargs["project"]) / "train" / "weights"
        self.trainer = type("T", (), {"best": out / "best.pt", "last": out / "last.pt", "metrics": {}})()


@pytest.mark.parametrize("finetune", [False, True])
def test_rounds_fine_tune_with_small_lr_and_no_warmup(tmp_path, cfg, monkeypatch, finetune):
    import anpr_hitl.yolo
    from anpr_hitl.train import train_detector

    _FakeYOLO.calls = []
    monkeypatch.setattr(anpr_hitl.yolo, "YOLO", _FakeYOLO)
    train_detector(tmp_path / "data.yaml", tmp_path / "base.pt", tmp_path / "run", cfg, finetune=finetune)
    (kwargs,) = _FakeYOLO.calls
    if finetune:
        assert kwargs["lr0"] == cfg.train.round_lr0 < cfg.train.lr0
        assert kwargs["warmup_epochs"] == cfg.train.round_warmup_epochs == 0
    else:
        assert kwargs["lr0"] == cfg.train.lr0 and "warmup_epochs" not in kwargs
    assert kwargs["fliplr"] == 0.0

@pytest.mark.gpu
@pytest.mark.slow
@pytest.mark.parametrize("damage", ["torn", "missing"])
def test_stop_then_damaged_checkpoint_then_resume_completes(tmp_path, damage):
    if not torch.cuda.is_available():
        pytest.skip("needs CUDA")
    from anpr_hitl.config import load_config
    from anpr_hitl.store import Store
    from anpr_hitl.train import train_detector

    cfg = load_config()
    store = Store(cfg.data_root)
    data = store.bootstrap_dir / "detector" / "seed_data.yaml"
    base = store.models_dir / "base" / cfg.train.base_model
    if not data.is_file() or not base.is_file():
        pytest.skip("bootstrap data and base weights are required (anpr bootstrap-data)")
    run = tmp_path / "run"

    def request_stop(trainer):
        if trainer.epoch == 0:
            (run / "STOP").touch()

    first = train_detector(data, base, run, cfg, epochs=3, fraction=0.02, imgsz=320, batch=4,
                           extra_callbacks={"on_fit_epoch_end": request_stop})
    assert first.stopped_reason == "STOP file" and (run / "STOPPED.json").is_file()
    verified = run / "checkpoints" / "last.verified.pt"
    assert checkpoint_kind(verified) == "resumable"
    stopped_epoch = torch.load(verified, map_location="cpu", weights_only=False)["epoch"]
    assert stopped_epoch < 2

    last = run / "train" / "weights" / "last.pt"
    if damage == "torn":
        last.write_bytes(last.read_bytes()[: last.stat().st_size // 3])   # torn write, as after power loss
    else:
        last.unlink()   # a new spot instance receives only the verified copy from the bucket
    second = train_detector(data, base, run, cfg)
    assert second.resumed and second.stopped_reason is None and (run / "DONE.json").is_file()
    results = (run / "train" / "results.csv").read_text().splitlines()
    epochs_logged = [int(float(line.split(",")[0])) for line in results[1:]]
    assert max(epochs_logged) == 3, f"resume did not reach the planned 3 epochs: {epochs_logged}"
    assert Path(second.best).is_file()
