"""Fill MODEL_CARD_TEMPLATE.md for a registered model (version, data hash, config hash, git SHA, GOLD metrics)."""

from __future__ import annotations

from pathlib import Path
from string import Template

from anpr_hitl.chainlog import ChainLog
from anpr_hitl.config import PACKAGE_ROOT, Config
from anpr_hitl.registry import Registry
from anpr_hitl.store import Store, atomic_write_text

TEMPLATE = PACKAGE_ROOT / "MODEL_CARD_TEMPLATE.md"

LIMITATIONS = """* GOLD is provisional: public, licence-cleared Indian images and crops, not PEC footage and not split by
  video. Replace it with >= 500 plates from >= 10 PEC videos before trusting deployment numbers.
* Rounds answered by the simulated reviewer use the public datasets' own human labels (no plate text); they
  show that the loop works, not how PEC reviewers label.
* Trained at the training image size; Frigate runs the detector at the export size (see the export report for the
  accuracy at that size and the parity of the ONNX / OpenVINO files).
* Few night, rain and two-wheeler examples; see the slice table before relying on those conditions."""


def _pct(v) -> str:
    return "n/a" if v is None else f"{100 * v:.2f}"


def _ci(ci) -> str:
    return "" if not ci else f"{_pct(ci[0])}–{_pct(ci[1])}"


def render(record: dict, cfg: Config, status: str, gate: dict | None, registry_head: str, audit_head: str) -> str:
    m = record["metrics"]
    d, o = m["detection"], m["ocr"]
    metric_rows = [("precision @ conf %.2f, IoU 0.5" % m["op_conf"], _pct(d["precision"]), ""),
                   ("recall @ conf %.2f, IoU 0.5" % m["op_conf"], _pct(d["recall"]), ""),
                   ("mAP50", _pct(d["map50"]), _ci(d["ci95"].get("map50"))),
                   ("mAP50-95", _pct(d["map50_95"]), _ci(d["ci95"].get("map50_95"))),
                   (f"OCR exact match ({o['n']} crops)", _pct(o["exact"]), _ci(o["ci95"].get("exact"))),
                   ("OCR character error rate", _pct(o["cer"]), "")]
    slice_rows = [f"| {k} | {v['n']} | {_pct(v['value'])} |" for k, v in sorted(m["slices"].items())]
    gate_text = "n/a"
    if gate:
        gate_text = ("PROMOTED" if gate.get("promote") else "REJECTED") + ": " + "; ".join(gate.get("reasons", []))
        if gate.get("gains_pt"):
            gate_text += f" (gains in points: {gate['gains_pt']})"
    values = {
        "version": record["version"], "round": record["round"], "parent": record.get("parent") or "none",
        "status": status, "registered": record["ts"], "class_name": cfg.class_names[0],
        "weights_sha256": record["weights_sha256"], "git_sha": record["git_sha"],
        "train_args_sha256": record.get("train_args_sha256") or "not recorded",
        "git_sha_short": record["git_sha"][:12], "config_sha256": record["config_sha256"],
        "data_sha256": record["data_manifest_sha256"], "data_sha256_short": record["data_manifest_sha256"][:12],
        "gold_sha256": record.get("gold_manifest_sha256") or m.get("gold_manifest_sha256"),
        "registry_head": registry_head[:16], "audit_head": audit_head[:16],
        "base": cfg.train.base_model if record.get("parent") is None else f"champion {record['parent']}",
        "imgsz": m.get("imgsz", cfg.train.imgsz), "lr0": cfg.train.lr0, "optimizer": cfg.train.optimizer,
        "replay": f"{cfg.train.replay_fraction:.0%}", "seed": cfg.seed,
        "ocr_engine": f"{o.get('engine')} (config {o.get('ocr_config_sha256')})",
        "gold_note": (f"Detection GOLD: {d['images']} images, {d['n']} plates; OCR GOLD: {o['n']} crops. "
                      f"Evaluated at imgsz {m.get('imgsz')}; 95% CIs from {cfg.evaluate.bootstrap} bootstrap resamples."),
        "metrics_rows": "\n".join(f"| {a} | {b} | {c} |" for a, b, c in metric_rows),
        "slice_rows": "\n".join(slice_rows) or "| (none) | | |", "min_slice_n": cfg.promote.min_slice_n,
        "gate": gate_text, "limitations": LIMITATIONS,
    }
    return Template(TEMPLATE.read_text()).substitute(values)


def write_model_card(store: Store, cfg: Config, version: str | None = None) -> Path:
    registry = Registry(store)
    version = version or registry.champion_version()
    if version is None:
        raise SystemExit("no model registered")
    record = registry.models()[version]
    gate, status = None, "registered"
    for e in registry.log.entries():
        if e.get("version") == version and e["event"] in ("promote", "reject"):
            gate, status = e.get("gate"), {"promote": "promoted", "reject": "rejected"}[e["event"]]
    if registry.champion_version() == version:
        status = "champion"
    text = render(record, cfg, status, gate, registry.log.head(), ChainLog(store.audit_log).head())
    path = store.models_dir / version / "MODEL_CARD.md"
    atomic_write_text(path, text)
    return path
