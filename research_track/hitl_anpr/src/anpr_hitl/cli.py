"""`anpr` command line: one subcommand per pipeline stage, plus run-round, registry and export commands.

Console output never contains plate text (plates are personal data); per-plate detail stays in the private data
root.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from anpr_hitl.config import load_config
from anpr_hitl.store import Store


def _table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "(no rows)"
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    line = " | ".join(c.ljust(widths[c]) for c in columns)
    sep = "-|-".join("-" * widths[c] for c in columns)
    body = "\n".join(" | ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns) for r in rows)
    return f"{line}\n{sep}\n{body}"


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def _pct(v) -> str:
    return "" if v is None else f"{100 * v:.2f}"


# ---------------------------------------------------------------- data

def cmd_ingest(args, cfg, store) -> int:
    from anpr_hitl.ingest import find_videos, ingest_video

    videos = find_videos(args.paths)
    if not videos:
        print("no videos found", file=sys.stderr)
        return 1
    rows = []
    for video in videos:
        res = ingest_video(video, store, cfg, group=args.group, split=args.split, source=args.source,
                           licence=args.licence, force=args.force)
        rows.append({"video_id": res.video_id, "split": res.split, "fps": round(res.native_fps, 2),
                     "frames": res.frame_count, "size": f"{res.width}x{res.height}", "sampled": res.sampled,
                     "blurry": res.dropped_blur, "near_dup": res.dropped_duplicate, "kept": res.kept,
                     "note": "already ingested" if res.skipped_existing else ""})
    print(_table(rows, ["video_id", "split", "fps", "frames", "size", "sampled", "blurry", "near_dup", "kept", "note"]))
    return 0


def cmd_bootstrap_data(args, cfg, store) -> int:
    from anpr_hitl.bootstrap import build_detector_sets, build_ocr_dev, build_ocr_gold

    if args.ocr_dev:
        _print(build_ocr_dev(store, cfg))
        return 0
    det = build_detector_sets(store, cfg)
    print(_table([{"split": s, "images": det["images"].get(s, 0), "plates": det["plates"][s]}
                  for s in ("seed", "pool", "val", "gold")], ["split", "images", "plates"]))
    print(f"groups={det['groups']} cross_split_near_duplicates={det['cross_split_near_duplicates']}")
    ocr = build_ocr_gold(store, cfg)
    print(f"OCR GOLD: {ocr['crops']} crops, {ocr['unique_texts']} plates, {ocr['format_invalid_labels']} format-invalid labels")
    _print(build_ocr_dev(store, cfg))
    return 0


# ---------------------------------------------------------------- training / registry

def cmd_train_bootstrap(args, cfg, store) -> int:
    from anpr_hitl.train import preflight, train_detector

    problems = preflight()
    if problems and not args.ignore_preflight:
        print("not starting: " + "; ".join(problems), file=sys.stderr)
        return 2
    data_yaml = store.bootstrap_dir / "detector" / "seed_data.yaml"
    base = store.models_dir / "base" / cfg.train.base_model
    base.parent.mkdir(parents=True, exist_ok=True)
    res = train_detector(data_yaml, base, store.runs_dir(args.run), cfg, epochs=args.epochs, fraction=args.fraction)
    _print({"best": str(res.best), "seconds": res.seconds, "resumed": res.resumed, "stopped": res.stopped_reason,
            "metrics": res.final_metrics})
    return 0


def _metrics_rows(m: dict) -> list[dict]:
    d, o = m["detection"], m["ocr"]
    return [{"metric": "precision@op", "value": _pct(d["precision"]), "ci95": ""},
            {"metric": "recall@op", "value": _pct(d["recall"]), "ci95": ""},
            {"metric": "mAP50", "value": _pct(d["map50"]), "ci95": "–".join(_pct(v) for v in d["ci95"].get("map50", []))},
            {"metric": "mAP50-95", "value": _pct(d["map50_95"]),
             "ci95": "–".join(_pct(v) for v in d["ci95"].get("map50_95", []))},
            {"metric": "OCR exact", "value": _pct(o["exact"]), "ci95": "–".join(_pct(v) for v in o["ci95"].get("exact", []))},
            {"metric": "OCR CER", "value": _pct(o["cer"]), "ci95": ""}]


def _print_metrics(m: dict) -> None:
    print(f"GOLD {m['gold_manifest_sha256'][:12]}  det images={m['detection']['images']} plates={m['detection']['n']}  "
          f"OCR crops={m['ocr']['n']} ({m['ocr']['engine']})  imgsz={m['imgsz']} op_conf={m['op_conf']}")
    print(_table(_metrics_rows(m), ["metric", "value", "ci95"]))
    print(_table([{"slice": k, "n": v["n"], "value": _pct(v["value"])} for k, v in m["slices"].items()],
                 ["slice", "n", "value"]))


def cmd_register_bootstrap(args, cfg, store) -> int:
    from anpr_hitl.promote import promotion_gate
    from anpr_hitl.registry import Registry
    from anpr_hitl.rounds import evaluate_weights
    from anpr_hitl.store import read_json

    registry = Registry(store)
    if registry.models():
        print("registry already has models; bootstrap registration is a one-off", file=sys.stderr)
        return 1
    run = store.runs_dir(args.run)
    done = read_json(run / "DONE.json")
    if not done:
        print(f"{run} has not finished training", file=sys.stderr)
        return 1
    weights = Path(done["best"])
    metrics = evaluate_weights(store, cfg, weights, f"bootstrap_{args.run}")
    metrics["eval_name"] = f"bootstrap_{args.run}"
    summary = read_json(store.bootstrap_dir / "detector" / "summary.json")
    record = registry.register(weights, cfg, summary["data_manifest_sha256"], "r00", metrics,
                               gold_sha256=metrics["gold_manifest_sha256"], notes=f"bootstrap run {args.run}",
                               train_args=run / "train" / "args.yaml")
    gate = promotion_gate(metrics, None, cfg.promote)
    registry.promote(record["version"], gate.to_dict(), registry_actor(args))
    print(f"registered and promoted {record['version']} (git {record['git_sha'][:12]})")
    _print_metrics(metrics)
    return 0


def registry_actor(args) -> str:
    return getattr(args, "reviewer", None) or os.environ.get("ANPR_REVIEWER") or os.environ.get("USER", "unknown")


def cmd_registry(args, cfg, store) -> int:
    from anpr_hitl.registry import Registry

    registry = Registry(store)
    if args.action == "verify":
        problems = registry.verify()
        print("registry intact" if not problems else "\n".join(problems))
        return 0 if not problems else 1
    if args.action == "rollback":
        if not args.to or not args.reason:
            print("rollback needs --to VERSION and --reason", file=sys.stderr)
            return 2
        entry = registry.rollback(args.to, args.reason, registry_actor(args))
        print(f"champion is now {entry['version']} (was {entry['from']})")
        return 0
    champion = registry.champion_version()
    status = {}
    for e in registry.log.entries():
        if e["event"] in ("promote", "reject"):
            status[e["version"]] = e["event"]
    rows = [{"version": v, "round": r["round"], "parent": r["parent"] or "", "git": r["git_sha"][:12],
             "data": r["data_manifest_sha256"][:12], "mAP50-95": _pct(r["metrics"]["detection"]["map50_95"]),
             "mAP50": _pct(r["metrics"]["detection"]["map50"]), "exact": _pct(r["metrics"]["ocr"]["exact"]),
             "status": ("CHAMPION" if v == champion else status.get(v, "registered"))}
            for v, r in registry.models().items()]
    print(_table(rows, ["version", "round", "parent", "git", "data", "mAP50-95", "mAP50", "exact", "status"]))
    return 0


def cmd_evaluate(args, cfg, store) -> int:
    from anpr_hitl.rounds import evaluate_weights

    m = evaluate_weights(store, cfg, Path(args.weights), args.name or f"adhoc_{Path(args.weights).stem}")
    _print_metrics(m)
    return 0


def cmd_ocr_benchmark(args, cfg, store) -> int:
    from anpr_hitl.evaluate import OCR_VARIANTS, benchmark_ocr

    res = benchmark_ocr(store, cfg, args.variants or list(OCR_VARIANTS))
    print(_table([{**r, "exact": _pct(r["exact"]), "cer": _pct(r["cer"]),
                   "exact_standard_format": _pct(r["exact_standard_format"]),
                   "exact_two_line": _pct(r["exact_two_line"]),
                   "ci95": "–".join(_pct(v) for v in r["ci95"])} for r in res],
                 ["variant", "n", "exact", "ci95", "cer", "exact_standard_format", "exact_two_line", "two_line_n",
                  "ms_per_crop"]))
    return 0


# ---------------------------------------------------------------- the loop

def _weights(args, store) -> tuple[Path, str | None]:
    from anpr_hitl.registry import Registry

    if getattr(args, "weights", None):
        return Path(args.weights), None
    champ = Registry(store).champion()
    if champ is None:
        raise SystemExit("no champion yet: run `anpr register-bootstrap` or pass --weights")
    return Path(champ["weights_path"]), champ["version"]


def cmd_predict(args, cfg, store) -> int:
    from anpr_hitl.rounds import predict_round

    weights, version = _weights(args, store)
    res = predict_round(store, cfg, args.round, weights, version, set(args.source), args.videos)
    _print(res)
    return 0


def cmd_select(args, cfg, store) -> int:
    from anpr_hitl.review.service import ReviewService
    from anpr_hitl.rounds import select_round

    _print(select_round(store, cfg, args.round, ReviewService(store, cfg), args.budget))
    return 0


def cmd_oracle(args, cfg, store) -> int:
    from anpr_hitl.oracle import oracle_review
    from anpr_hitl.review.service import ReviewService

    svc = ReviewService(store, cfg)
    _print({**oracle_review(svc, args.round), "status": svc.summary(args.round), "audit": svc.audit_stats()})
    return 0


def cmd_review_status(args, cfg, store) -> int:
    from anpr_hitl.review.service import ReviewService

    svc = ReviewService(store, cfg)
    allowed, why = svc.auto_accept_allowed()
    _print({"status": svc.summary(args.round), "audit": svc.audit_stats(),
            "auto_accept": {"allowed": allowed, "why": why}, "audit_log_intact": not svc.log.verify()})
    return 0


def cmd_review_app(args, cfg, store) -> int:
    app = Path(__file__).parent / "review" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app), "--server.address", "127.0.0.1",
           "--server.port", str(args.port), "--server.headless", "true", "--browser.gatherUsageStats", "false",
           "--", "--round", args.round]
    if args.config:
        cmd += ["--config", str(args.config)]
    if args.data_root:
        cmd += ["--data-root", args.data_root]
    print(f"review app on http://127.0.0.1:{args.port} (local only); Ctrl+C to stop")
    return subprocess.call(cmd)


def cmd_assemble(args, cfg, store) -> int:
    from anpr_hitl.dataset import assemble
    from anpr_hitl.rounds import mark

    res = assemble(store, cfg, args.round, earlier_rounds=args.earlier, force=args.force)
    mark(store, args.round, "assemble", res)
    _print(res)
    return 0


def cmd_run_round(args, cfg, store) -> int:
    """Run (or continue) a round up to the first stage that needs a person."""
    from anpr_hitl.dataset import assemble
    from anpr_hitl.oracle import oracle_review
    from anpr_hitl.registry import Registry
    from anpr_hitl.review.service import ReviewService
    from anpr_hitl.rounds import (gate_and_register, mark, predict_round, reviewed_total, round_state, select_round,
                                  should_stop)
    from anpr_hitl.store import read_json
    from anpr_hitl.train import preflight, train_detector

    svc, registry = ReviewService(store, cfg), Registry(store)
    stop, why = should_stop(read_json(store.root / "rounds" / "history.json", []), cfg, reviewed_total(svc))
    stages = round_state(store, args.round)["stages"]
    if stop and "predict" not in stages:
        print(f"stopping rule met: {why}")
        return 0
    if "predict" not in stages:
        weights, version = _weights(args, store)
        print("predict:", json.dumps(predict_round(store, cfg, args.round, weights, version, set(args.source),
                                                   args.videos)))
    if "select" not in stages:
        print("select:", json.dumps(select_round(store, cfg, args.round, svc, args.budget)))
    if "review" not in round_state(store, args.round)["stages"]:
        if args.oracle:
            print("oracle:", json.dumps(oracle_review(svc, args.round)))
        status = svc.summary(args.round)
        if status["pending"]:
            print(f"waiting for review: {status['pending']} of {status['queued']} items pending. "
                  f"Start the app with `anpr review-app --round {args.round}`, then re-run this command.")
            return 0
        mark(store, args.round, "review", {**status, "audit": svc.audit_stats()})
    if "assemble" not in round_state(store, args.round)["stages"]:
        earlier = [h["round"] for h in read_json(store.root / "rounds" / "history.json", []) if h["round"] != args.round]
        res = assemble(store, cfg, args.round, svc, earlier_rounds=earlier)
        mark(store, args.round, "assemble", res)
        print("assemble:", json.dumps(res))
    if "train" not in round_state(store, args.round)["stages"]:
        problems = preflight()
        if problems and not args.ignore_preflight:
            print("not training: " + "; ".join(problems), file=sys.stderr)
            return 2
        champ = registry.champion()
        data = round_state(store, args.round)["stages"]["assemble"]
        res = train_detector(Path(data["data_yaml"]), Path(champ["weights_path"]), store.runs_dir(args.round), cfg,
                             epochs=args.epochs or cfg.train.round_epochs, finetune=True)
        if res.stopped_reason:
            print(f"training stopped ({res.stopped_reason}); re-run to resume", file=sys.stderr)
            return 3
        mark(store, args.round, "train", {"best": str(res.best), "seconds": res.seconds, "from": champ["version"]})
        print("train:", json.dumps({"best": str(res.best), "seconds": res.seconds}))
    if "gate" not in round_state(store, args.round)["stages"]:
        st = round_state(store, args.round)["stages"]
        res = gate_and_register(store, cfg, registry, Path(st["train"]["best"]), args.round,
                                st["assemble"]["data_manifest_sha256"], registry_actor(args))
        _print(res)
    stop, why = should_stop(read_json(store.root / "rounds" / "history.json", []), cfg, reviewed_total(svc))
    print(f"next: {'STOP - ' + why if stop else 'start another round'}")
    return 0


# ---------------------------------------------------------------- deployment

def cmd_export(args, cfg, store) -> int:
    from anpr_hitl.export import export_and_check

    weights, version = _weights(args, store)
    _print(export_and_check(weights, version, store, cfg, max_images=args.max_images))
    return 0


def cmd_propose(args, cfg, store) -> int:
    from anpr_hitl.propose import propose

    _print(propose(store, cfg, args.round, args.gate_id, send=args.send, api_url=args.api_url))
    return 0


def cmd_model_card(args, cfg, store) -> int:
    from anpr_hitl.modelcard import write_model_card

    print(write_model_card(store, cfg, args.version))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anpr", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="config.yaml (default: the shipped one)")
    parser.add_argument("--data-root", default=None, help="override data_root")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="sample frames from videos into the private data root")
    p.add_argument("paths", nargs="+", type=Path, help="video files or folders")
    p.add_argument("--group", default=None, help="site/scene group (videos of one site share a split)")
    p.add_argument("--split", choices=["pool", "val", "gold"], default=None, help="force the split of NEW videos")
    p.add_argument("--source", default=None, help="provenance, e.g. a URL or 'PEC gate 1 camera'")
    p.add_argument("--licence", default=None)
    p.add_argument("--force", action="store_true", help="re-extract frames of an already ingested video")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("bootstrap-data", help="seed/pool/val + provisional GOLD from licence-cleared public data")
    p.add_argument("--ocr-dev", action="store_true", help="only (re)build the OCR dev set")
    p.set_defaults(func=cmd_bootstrap_data)

    p = sub.add_parser("train-bootstrap", help="train the round-0 model on the seed split (resumes if interrupted)")
    p.add_argument("--run", default="r00_bootstrap", help="run id under runs/")
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--fraction", type=float, default=1.0, help="fraction of the seed split (smoke runs)")
    p.add_argument("--ignore-preflight", action="store_true")
    p.set_defaults(func=cmd_train_bootstrap)

    p = sub.add_parser("register-bootstrap", help="evaluate the bootstrap run on GOLD and make it the first champion")
    p.add_argument("--run", default="r00_bootstrap")
    p.set_defaults(func=cmd_register_bootstrap)

    p = sub.add_parser("registry", help="list models, verify the registry, or roll back the champion")
    p.add_argument("action", nargs="?", choices=["list", "verify", "rollback"], default="list")
    p.add_argument("--to", default=None, help="rollback target version, e.g. v0001")
    p.add_argument("--reason", default=None)
    p.set_defaults(func=cmd_registry)

    p = sub.add_parser("evaluate", help="GOLD metrics for any weights file (does not register)")
    p.add_argument("--weights", required=True)
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("ocr-benchmark", help="compare OCR engines on the OCR dev set (never GOLD)")
    p.add_argument("--variants", nargs="*", default=None)
    p.set_defaults(func=cmd_ocr_benchmark)

    def round_args(q, weights=True):
        q.add_argument("--round", required=True, help="round id, e.g. r01")
        if weights:
            q.add_argument("--weights", default=None, help="default: the registry champion")
            q.add_argument("--source", nargs="+", choices=["public", "video"], default=["public"])
            q.add_argument("--videos", nargs="*", type=Path, default=[], help="video files/folders (for --source video)")

    p = sub.add_parser("predict", help="proposals for pool frames: boxes, tracks, OCR reads, checks")
    round_args(p)
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("select", help="build the round's review queue (audit sample + uncertainty)")
    round_args(p, weights=False)
    p.add_argument("--budget", type=int, default=None)
    p.set_defaults(func=cmd_select)

    p = sub.add_parser("oracle", help="simulated review of queued public-pool frames from their human labels")
    round_args(p, weights=False)
    p.set_defaults(func=cmd_oracle)

    p = sub.add_parser("review-status", help="queue progress, audit precision and the auto-accept gate")
    round_args(p, weights=False)
    p.set_defaults(func=cmd_review_status)

    p = sub.add_parser("review-app", help="start the Streamlit review app on 127.0.0.1")
    round_args(p, weights=False)
    p.add_argument("--port", type=int, default=8501)
    p.set_defaults(func=cmd_review_app)

    p = sub.add_parser("assemble", help="build the round's training set from reviewed frames + replay")
    round_args(p, weights=False)
    p.add_argument("--earlier", nargs="*", default=[], help="earlier rounds whose reviewed frames join the replay pool")
    p.add_argument("--force", action="store_true", help="rebuild an assembled round from the audit log")
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser("run-round", help="predict -> select -> review -> assemble -> train -> evaluate -> gate")
    round_args(p)
    p.add_argument("--budget", type=int, default=None)
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--oracle", action="store_true", help="let the simulated reviewer answer public-pool frames")
    p.add_argument("--ignore-preflight", action="store_true")
    p.set_defaults(func=cmd_run_round)

    p = sub.add_parser("export", help="ONNX + OpenVINO at the deployment size, with parity against the .pt on GOLD")
    p.add_argument("--weights", default=None, help="default: the registry champion")
    p.add_argument("--max-images", type=int, default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("propose", help="backend observation payloads (proposals only); dry run unless --send")
    round_args(p, weights=False)
    p.add_argument("--gate-id", required=True)
    p.add_argument("--send", action="store_true")
    p.add_argument("--api-url", default=None, help="e.g. http://127.0.0.1:8000 (token from $ANPR_BACKEND_TOKEN)")
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser("model-card", help="write the model card for a registered version")
    p.add_argument("--version", default=None, help="default: the champion")
    p.set_defaults(func=cmd_model_card)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config, data_root=args.data_root)
    return args.func(args, cfg, Store(cfg.data_root))


if __name__ == "__main__":
    sys.exit(main())
