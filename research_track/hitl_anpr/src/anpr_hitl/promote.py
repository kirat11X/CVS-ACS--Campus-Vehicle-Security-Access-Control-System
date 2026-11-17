"""Promotion gate: a candidate replaces the champion only if it is better on the same GOLD set.

Promote when (mAP50-95 gain >= min_gain_map50_95 pt OR exact-match gain >= min_gain_exact pt) AND no slice
with n >= min_slice_n drops by more than max_slice_regression pt. Gains are in percentage points of the
metrics in [0, 1]. Comparisons on different GOLD manifests, or with missing / non-finite metrics, are rejected.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from anpr_hitl.config import PromoteConfig

EPS = 1e-9  # a gain of exactly the threshold passes despite float rounding


@dataclass
class GateDecision:
    promote: bool
    reasons: list[str] = field(default_factory=list)
    gains_pt: dict = field(default_factory=dict)
    slice_changes_pt: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _metric(metrics: dict, section: str, name: str) -> float | None:
    value = (metrics.get(section) or {}).get(name)
    return float(value) if isinstance(value, (int, float)) else None


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def promotion_gate(candidate: dict, champion: dict | None, cfg: PromoteConfig) -> GateDecision:
    if champion is None:
        return GateDecision(True, ["no champion yet: the first evaluated model becomes champion"])
    reasons: list[str] = []
    if candidate.get("gold_manifest_sha256") != champion.get("gold_manifest_sha256"):
        return GateDecision(False, ["evaluated on a different GOLD set than the champion"])

    cand_map, champ_map = _metric(candidate, "detection", "map50_95"), _metric(champion, "detection", "map50_95")
    if not (_finite(cand_map) and _finite(champ_map)):
        return GateDecision(False, ["mAP50-95 missing or not finite"])
    gains = {"map50_95": round((cand_map - champ_map) * 100, 4)}
    cand_exact, champ_exact = _metric(candidate, "ocr", "exact"), _metric(champion, "ocr", "exact")
    if cand_exact is not None or champ_exact is not None:
        if not (_finite(cand_exact) and _finite(champ_exact)):
            return GateDecision(False, ["exact-match missing or not finite on one side"])
        gains["exact"] = round((cand_exact - champ_exact) * 100, 4)

    passed = []
    if gains["map50_95"] >= cfg.min_gain_map50_95 - EPS:
        passed.append("map50_95")
    if "exact" in gains and gains["exact"] >= cfg.min_gain_exact - EPS:
        passed.append("exact")
    if not passed:
        reasons.append(f"gain too small: mAP50-95 {gains['map50_95']:+.2f} pt (need {cfg.min_gain_map50_95:+.2f})"
                       + (f", exact {gains['exact']:+.2f} pt (need {cfg.min_gain_exact:+.2f})" if "exact" in gains else ""))
    elif cfg.require_significant:
        ci = candidate.get("paired_gain_ci_pt") or {}
        if not any(isinstance(ci.get(m), (list, tuple)) and ci[m][0] > 0 for m in passed):
            reasons.append(f"gain on {', '.join(passed)} is not significant (95% CI includes 0)")

    changes = {}
    champ_slices, cand_slices = champion.get("slices") or {}, candidate.get("slices") or {}
    for name, ch in sorted(champ_slices.items()):
        if ch.get("n", 0) < cfg.min_slice_n:
            continue
        cs = cand_slices.get(name)
        if cs is None or not _finite(cs.get("value")) or not _finite(ch.get("value")):
            reasons.append(f"slice {name}: missing or not finite for the candidate")
            continue
        delta = round((cs["value"] - ch["value"]) * 100, 4)
        changes[name] = delta
        if -delta > cfg.max_slice_regression + EPS:
            reasons.append(f"slice {name} regressed {delta:+.2f} pt (limit -{cfg.max_slice_regression:.2f})")
    return GateDecision(not reasons, reasons or [f"improved on {', '.join(passed)}"], gains, changes)
