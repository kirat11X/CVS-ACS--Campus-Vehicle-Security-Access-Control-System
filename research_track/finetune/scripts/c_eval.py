"""Track C classifier evaluation: CLASSIFIER METRICS ONLY (never policy outcomes).

Compares on one split:
  lexical   - track_c LexicalMappingClassifier with a keyword map built from the TRAIN split only
              (the shipped map covers every taxonomy row, which would leak test items) + its built-in heuristics
  minilm_knn- MiniLM cosine kNN over train items; k and an UNKNOWN similarity threshold are tuned on VAL only
  qwen_zs   - Qwen3-1.7B 4-bit zero-shot, same prompt, adapter disabled
  qwen_lora - Qwen3-1.7B 4-bit + trained LoRA adapter
Metrics: accuracy, per-class P/R/F1, macro-F1, confusion matrix, UNKNOWN rate, invalid-output rate,
gold-UNKNOWN->NORMAL count; 95% percentile bootstrap CIs and paired bootstrap deltas vs lexical / zero-shot.

The test split may be evaluated exactly once per --eval-id: a lock file is written and re-runs refuse.

Usage:
  c_eval.py --split val  --adapter <run_dir>/adapter --eval-id val_v1
  c_eval.py --split test --adapter <run_dir>/adapter --eval-id test_final
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from c_common import (
    CODES,
    MINILM_PATH,
    QWEN_PATH,
    RESEARCH_ROOT,
    RUNS_C,
    load_split,
    seed_everything,
    sha256_file,
    write_run_manifest,
)

PROVENANCE = "synthetic LLM-authored items; measures fit to that distribution, not real invoice accuracy"


def lexical_predict(train_df, texts):
    sys.path.insert(0, str(RESEARCH_ROOT))
    from track_c.src.classifier_interface import LexicalMappingClassifier
    from track_c.src.types import ClassificationInput, ItemCategoryCode

    kmap = {t.strip().lower(): ItemCategoryCode(c) for t, c in zip(train_df["item_text"], train_df["category"])}
    clf = LexicalMappingClassifier(keyword_map=kmap)
    return [clf.classify(ClassificationInput(line_item_id=str(i), raw_item_description=t)).predicted_category.value
            for i, t in enumerate(texts)]


def knn_fit_predict(train_df, val_df, eval_texts):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(MINILM_PATH), device="cpu")
    enc = lambda xs: model.encode(list(xs), normalize_embeddings=True, batch_size=64)  # noqa: E731
    tr, va, ev = enc(train_df["item_text"]), enc(val_df["item_text"]), enc(eval_texts)
    tr_lab = np.array(train_df["category"])

    def predict(emb, k, tau):
        sims = emb @ tr.T
        out = []
        for row in sims:
            idx = np.argsort(-row)[:k]
            if row[idx[0]] < tau:
                out.append("UNKNOWN")
                continue
            score = {}
            for j in idx:
                score[tr_lab[j]] = score.get(tr_lab[j], 0.0) + float(row[j])
            out.append(max(score, key=score.get))
        return out

    from sklearn.metrics import f1_score

    best = None
    for k in (1, 3, 5, 7):
        for tau in (0.0, 0.3, 0.4, 0.5, 0.6):
            f1 = f1_score(val_df["category"], predict(va, k, tau), labels=CODES, average="macro", zero_division=0)
            if best is None or f1 > best[0] + 1e-12:
                best = (f1, k, tau)
    return predict(ev, best[1], best[2]), {"k": best[1], "tau": best[2], "val_macro_f1": round(best[0], 4)}


def metrics(gold, pred, valid=None):
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support

    p, r, f, s = precision_recall_fscore_support(gold, pred, labels=CODES, zero_division=0)
    m = {
        "n": len(gold),
        "accuracy": float(accuracy_score(gold, pred)),
        "macro_f1": float(f1_score(gold, pred, labels=CODES, average="macro", zero_division=0)),
        "unknown_rate": float(np.mean([x == "UNKNOWN" for x in pred])),
        "gold_unknown_pred_normal": int(sum(g == "UNKNOWN" and q == "NORMAL" for g, q in zip(gold, pred))),
        "per_class": {c: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
                      for i, c in enumerate(CODES)},
        "confusion_matrix": {"labels": CODES, "rows_gold_cols_pred": confusion_matrix(gold, pred, labels=CODES).tolist()},
    }
    if valid is not None:
        m["invalid_output_rate"] = float(1 - np.mean(valid))
    return m


def bootstrap(gold, preds: dict, ref_names, n=2000, seed=0):
    from sklearn.metrics import f1_score

    rng = np.random.default_rng(seed)
    g = np.array(gold)
    P = {k: np.array(v) for k, v in preds.items()}
    samples = {k: {"accuracy": [], "macro_f1": []} for k in P}
    for _ in range(n):
        idx = rng.integers(0, len(g), len(g))
        for k, v in P.items():
            samples[k]["accuracy"].append(float(np.mean(v[idx] == g[idx])))
            samples[k]["macro_f1"].append(f1_score(g[idx], v[idx], labels=CODES, average="macro", zero_division=0))
    ci = lambda a: [round(float(np.percentile(a, 2.5)), 4), round(float(np.percentile(a, 97.5)), 4)]  # noqa: E731
    out = {k: {m: ci(s) for m, s in d.items()} for k, d in samples.items()}
    deltas = {}
    for a in P:
        for b in ref_names:
            if a == b or b not in P:
                continue
            for m in ("accuracy", "macro_f1"):
                d = np.array(samples[a][m]) - np.array(samples[b][m])
                deltas[f"{a}-minus-{b}:{m}"] = {"ci95": ci(d), "p_le_0": round(float(np.mean(d <= 0)), 4)}
    return out, deltas


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("val", "test"), required=True)
    ap.add_argument("--split-dir", type=Path, default=RUNS_C / "split_v1")
    ap.add_argument("--adapter", type=Path, default=None)
    ap.add_argument("--eval-id", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args()

    seed_everything(args.seed)
    out_dir = RUNS_C / "eval" / args.eval_id
    lock = RUNS_C / "eval" / "TEST_EVALUATED.lock"
    if args.split == "test":
        if lock.exists():
            raise SystemExit(f"REFUSED: test split already evaluated once ({lock.read_text().strip()})")
        if args.max_samples:
            raise SystemExit("REFUSED: test evaluation must use the full test split")
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    sp = load_split(args.split_dir)
    ev = sp[args.split]
    if args.max_samples:
        ev = ev.sample(n=min(args.max_samples, len(ev)), random_state=args.seed)
    texts, gold = ev["item_text"].tolist(), ev["category"].tolist()
    if args.split == "test":
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(f"{args.eval_id} {time.strftime('%Y-%m-%dT%H:%M:%S')} adapter={args.adapter}\n")

    preds, valid, raws, extra = {}, {}, {}, {}
    preds["lexical"] = lexical_predict(sp["train"], texts)
    preds["minilm_knn"], extra["minilm_knn_tuned_on_val"] = knn_fit_predict(sp["train"], sp["val"], texts)

    peak = None
    if not args.skip_llm:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        from c_infer import predict_codes

        tok = AutoTokenizer.from_pretrained(QWEN_PATH)
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                 bnb_4bit_compute_dtype=torch.bfloat16)
        torch.cuda.reset_peak_memory_stats()
        model = AutoModelForCausalLM.from_pretrained(QWEN_PATH, quantization_config=bnb, dtype=torch.bfloat16,
                                                     device_map={"": 0})
        model.eval()
        if args.adapter:
            model = PeftModel.from_pretrained(model, str(args.adapter))
            model.eval()
            with model.disable_adapter():
                preds["qwen_zs"], raws["qwen_zs"], valid["qwen_zs"] = predict_codes(model, tok, texts)
            preds["qwen_lora"], raws["qwen_lora"], valid["qwen_lora"] = predict_codes(model, tok, texts)
        else:
            preds["qwen_zs"], raws["qwen_zs"], valid["qwen_zs"] = predict_codes(model, tok, texts)
        peak = round(torch.cuda.max_memory_reserved() / 2**30, 3)

    results = {k: metrics(gold, v, valid.get(k)) for k, v in preds.items()}
    cis, deltas = bootstrap(gold, preds, ref_names=("lexical", "qwen_zs"), n=args.n_boot, seed=args.seed)
    for k in results:
        results[k]["ci95"] = cis[k]

    errors = []
    best_name = "qwen_lora" if "qwen_lora" in preds else ("qwen_zs" if "qwen_zs" in preds else "minilm_knn")
    for i, (t, g) in enumerate(zip(texts, gold)):
        if preds[best_name][i] != g:
            errors.append({"item_text": t, "gold": g, "pred": preds[best_name][i],
                           "raw": raws.get(best_name, [None] * len(texts))[i],
                           "style": ev["style"].iloc[i], "all_models": {k: v[i] for k, v in preds.items()}})

    report = {
        "eval_id": args.eval_id, "split": args.split, "n": len(gold),
        "provenance_label": PROVENANCE,
        "scope": "classifier metrics only; no ALLOW/REVIEW/ALERT policy outcomes are computed or reported",
        "adapter": str(args.adapter) if args.adapter else None,
        "split_sha256": sha256_file(args.split_dir / f"{args.split}.csv"),
        "bootstrap": {"n": args.n_boot, "method": "percentile, item-level resampling, paired across models"},
        "results": results, "paired_deltas": deltas, "extra": extra,
        "errors_of": best_name, "errors": errors, "peak_vram_reserved_gib": peak,
        "wall_time_s": round(time.time() - t0, 1),
    }
    (out_dir / "eval_report.json").write_text(json.dumps(report, indent=1))
    (out_dir / "predictions.json").write_text(json.dumps(
        [{"item_text": t, "gold": g, **{k: v[i] for k, v in preds.items()},
          **{f"{k}_raw": v[i] for k, v in raws.items()}} for i, (t, g) in enumerate(zip(texts, gold))], indent=1))
    write_run_manifest(out_dir, run_id=args.eval_id, kind="eval", split=args.split, seed=args.seed,
                       data_sha256=report["split_sha256"], config_sha256=None, adapter=report["adapter"],
                       test_evaluated_once=(args.split == "test"))
    print(f"{'model':12s} {'acc':>6s} {'acc95':>15s} {'mF1':>6s} {'mF1_95':>15s} {'unk%':>5s} {'inv%':>5s} unk->norm")
    for k, m in results.items():
        print(f"{k:12s} {m['accuracy']:6.3f} {str(m['ci95']['accuracy']):>15s} {m['macro_f1']:6.3f} "
              f"{str(m['ci95']['macro_f1']):>15s} {100 * m['unknown_rate']:5.1f} "
              f"{100 * m.get('invalid_output_rate', 0):5.1f} {m['gold_unknown_pred_normal']}")
    print(json.dumps(deltas, indent=1))
    print("peak_vram_reserved_gib", peak, "wall_s", report["wall_time_s"], "->", out_dir)


if __name__ == "__main__":
    main()
