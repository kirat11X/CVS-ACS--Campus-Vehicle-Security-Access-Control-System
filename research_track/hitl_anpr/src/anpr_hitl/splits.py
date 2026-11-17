"""Split by video (or site group) BEFORE any frame is used, and check for near-duplicate leakage.

A group's split is a pure function of (seed, group id), so adding videos never moves an earlier video to
another split. Once recorded in videos.json an assignment is frozen.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from anpr_hitl.hashing import near_duplicate_pairs
from anpr_hitl.store import atomic_write_json, file_lock, read_json

SPLITS = ("pool", "val", "gold")


def split_for_group(group: str, seed: int, gold_fraction: float, val_fraction: float) -> str:
    """Stable, order-independent assignment from a hash of (seed, group)."""
    u = int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:12], 16) / 16**12
    if u < gold_fraction:
        return "gold"
    if u < gold_fraction + val_fraction:
        return "val"
    return "pool"


class VideoRegistry:
    """videos.json: video_id -> {split, group, source, sha256, ...}. Assignments are never changed."""

    def __init__(self, path: Path, seed: int, gold_fraction: float, val_fraction: float):
        self.path = Path(path)
        self.seed, self.gold_fraction, self.val_fraction = seed, gold_fraction, val_fraction

    def all(self) -> dict[str, dict]:
        return read_json(self.path, {})

    def register(self, video_id: str, group: str | None = None, split: str | None = None, **meta) -> dict:
        """Assign (or return the frozen) split for a video. `split` forces one only for a NEW video."""
        with file_lock(self.path):
            videos = read_json(self.path, {})
            if video_id in videos:
                return videos[video_id]
            group = group or video_id
            same_group = [v["split"] for v in videos.values() if v["group"] == group]
            if split is None:
                split = same_group[0] if same_group else split_for_group(group, self.seed, self.gold_fraction, self.val_fraction)
            elif same_group and split != same_group[0]:
                raise ValueError(f"group {group!r} is already in split {same_group[0]!r}")
            if split not in SPLITS:
                raise ValueError(f"unknown split {split!r}")
            videos[video_id] = {"split": split, "group": group, **meta}
            atomic_write_json(self.path, videos)
            return videos[video_id]

    def split_of(self, video_id: str) -> str:
        return self.all()[video_id]["split"]


@dataclass(frozen=True)
class LeakPair:
    a_split: str
    a_id: str
    b_split: str
    b_id: str
    distance: int


def leakage_check(hashes_by_split: dict[str, list[tuple[str, int | None]]], max_bits: int) -> list[LeakPair]:
    """Every pair of items in DIFFERENT splits whose perceptual hashes differ by <= max_bits."""
    names = sorted(hashes_by_split)
    leaks = []
    for i, a in enumerate(names):
        a_items = [(k, h) for k, h in hashes_by_split[a] if h is not None]
        for b in names[i + 1:]:
            b_items = [(k, h) for k, h in hashes_by_split[b] if h is not None]
            if not a_items or not b_items:
                continue
            for ia, ib, d in near_duplicate_pairs([h for _, h in a_items], [h for _, h in b_items], max_bits):
                leaks.append(LeakPair(a, a_items[ia][0], b, b_items[ib][0], d))
    return leaks
