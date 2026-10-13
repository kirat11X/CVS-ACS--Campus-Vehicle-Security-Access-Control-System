"""Track C grouped split: by brand/template family, never random per item.

Family linking (union-find), all deterministic:
  1. shared rare content token (document frequency <= RARE_DF, length >= 3, not generic/unit);
  2. same consonant skeleton of the leading brand token (catches truncations: "Srf Excl" ~ "Surf Excel");
  3. character similarity >= SIM of the unit/number-stripped text (near-duplicates such as
     "Amul Butter 500g" ~ "Amul Buttr 500").
Families are then assigned with StratifiedGroupKFold (5 folds): fold 0 = test, fold 1 = val, rest = train.

Usage: c_split.py [--seed 42] [--out ~/ml-assets/campus/runs/C/split_v1]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from c_common import CODES, DATA_CSV, RUNS_C, sha256_file, write_run_manifest

RARE_DF = 4
SIM = 0.82
GENERIC = {
    "pack", "packet", "bottle", "box", "pcs", "pc", "tablet", "tablets", "tab", "strip", "spray", "cream", "gel",
    "oil", "liquid", "powder", "pdr", "drink", "the", "and", "for", "with", "ka", "ki", "ke", "wala", "wali",
    "wale", "big", "small", "chota", "bada", "new", "classic", "premium", "pure", "plus", "pls", "pro", "max",
    "mini", "super", "extra", "strong", "mango", "masala", "cheese", "chicken", "white", "red", "blue", "black",
    "gold", "green", "item", "pouch", "text", "pack", "kings", "standard", "heavy", "duty", "utility", "steel",
    "goli", "sa", "ke", "mein", "lal", "energy", "noodles", "bread", "water", "soap", "mixture", "relief", "pain",
}
UNIT_RE = re.compile(r"^\d+([.,]\d+)?(g|kg|ml|l|ltr|mg|s|x|pc|pcs|m|tb)?$|^\d+x\d+.*$|^x$")


def tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if not UNIT_RE.match(t)]


def skeleton(tok: str) -> str:
    return tok[0] + re.sub(r"[aeiou]", "", tok[1:]) if tok else ""


class UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int, why: str, log: list) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)
            log.append((a, b, why))


def assign_families(df: pd.DataFrame) -> tuple[list[int], list]:
    texts = df["item_text"].tolist()
    toks = [tokens(t) for t in texts]
    df_count = Counter(t for ts in toks for t in set(ts))
    uf, log = UF(len(texts)), []
    by_tok: dict[str, list[int]] = {}
    for i, ts in enumerate(toks):
        for t in set(ts):
            if len(t) >= 3 and t not in GENERIC and df_count[t] <= RARE_DF:
                by_tok.setdefault(t, []).append(i)
    for t, idx in by_tok.items():
        for j in idx[1:]:
            uf.union(idx[0], j, f"token:{t}", log)
    lead = [next((t for t in ts if len(t) >= 3 and t not in GENERIC), "") for ts in toks]
    norm = [" ".join(ts) for ts in toks]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if lead[i] and len(skeleton(lead[i])) >= 3 and skeleton(lead[i]) == skeleton(lead[j]):
                uf.union(i, j, f"skeleton:{skeleton(lead[i])}", log)
            elif norm[i] and norm[j] and difflib.SequenceMatcher(None, norm[i], norm[j]).ratio() >= SIM:
                uf.union(i, j, "near_dup", log)
    roots = [uf.find(i) for i in range(len(texts))]
    remap = {r: k for k, r in enumerate(dict.fromkeys(roots))}
    return [remap[r] for r in roots], log


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=RUNS_C / "split_v1")
    args = ap.parse_args()

    df = pd.read_csv(DATA_CSV, dtype=str, keep_default_na=False)
    assert set(df["category"]) <= set(CODES), set(df["category"]) - set(CODES)
    fam, log = assign_families(df)
    df["family"] = fam

    sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=args.seed)
    folds = list(sgkf.split(df, df["category"], groups=df["family"]))
    split = pd.Series("train", index=df.index)
    split.iloc[folds[0][1]] = "test"
    split.iloc[folds[1][1]] = "val"
    df["split"] = split

    # Leakage checks: no family and no normalized text spans two splits.
    fam_splits = df.groupby("family")["split"].nunique()
    assert (fam_splits == 1).all(), "family leakage"
    norm = df["item_text"].map(lambda t: " ".join(tokens(t)))
    assert (df.assign(n=norm).groupby("n")["split"].nunique() == 1).all(), "normalized-text leakage"

    args.out.mkdir(parents=True, exist_ok=True)
    for s in ("train", "val", "test"):
        df[df["split"] == s][["item_text", "category", "style", "family"]].to_csv(args.out / f"{s}.csv", index=False)
    fam_sizes = Counter(fam)
    big = sorted(fam_sizes.items(), key=lambda kv: -kv[1])[:8]
    summary = {
        "seed": args.seed,
        "source_csv": str(DATA_CSV),
        "source_sha256": sha256_file(DATA_CSV),
        "n_items": len(df),
        "n_families": len(fam_sizes),
        "largest_families": [
            {"family": f, "size": n, "examples": df[df.family == f]["item_text"].head(6).tolist()} for f, n in big
        ],
        "counts": {s: df[df.split == s]["category"].value_counts().reindex(CODES, fill_value=0).to_dict()
                   for s in ("train", "val", "test")},
        "split_sha256": {s: sha256_file(args.out / f"{s}.csv") for s in ("train", "val", "test")},
        "link_reasons": Counter(w.split(":")[0] for _, _, w in log),
    }
    (args.out / "split_summary.json").write_text(json.dumps(summary, indent=2))
    (args.out / "family_links.tsv").write_text(
        "\n".join(f"{df.item_text[a]}\t{df.item_text[b]}\t{w}" for a, b, w in log)
    )
    write_run_manifest(args.out, run_id=args.out.name, kind="split", seed=args.seed,
                       data_sha256=summary["source_sha256"], split_sha256=summary["split_sha256"],
                       config_sha256=None)
    print(json.dumps({k: summary[k] for k in ("n_items", "n_families", "counts", "link_reasons")}, indent=1))
    for f in summary["largest_families"]:
        print(f["size"], f["examples"])


if __name__ == "__main__":
    main()
