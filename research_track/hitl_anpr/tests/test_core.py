"""Hashing, splits and leakage, hash-chained logs, manifests and config."""

import io
import json
import random
import threading

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from anpr_hitl.chainlog import ChainError, ChainLog
from anpr_hitl.config import Config, load_config
from anpr_hitl.hashing import dhash, hamming, near_duplicate_pairs, phash
from anpr_hitl.manifest import manifest_hash, read_manifest, write_manifest
from anpr_hitl.splits import VideoRegistry, leakage_check, split_for_group


def scene(seed: int, size=(640, 360)) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", size, tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(img)
    for _ in range(12):
        x, y = rng.randrange(size[0] - 40), rng.randrange(size[1] - 40)
        draw.rectangle([x, y, x + rng.randrange(40, 300), y + rng.randrange(30, 200)], fill=tuple(rng.randrange(256) for _ in range(3)))
    return img


def reencode(img, quality=70) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


# ---------------------------------------------------------------- hashing

@pytest.mark.parametrize("fn", [dhash, phash])
def test_hashes_survive_reencoding_and_separate_scenes(fn):
    a = scene(1)
    assert hamming(fn(a), fn(reencode(a.filter(ImageFilter.GaussianBlur(0.8)), 60))) <= 6
    assert min(hamming(fn(a), fn(scene(s))) for s in range(2, 30)) > 10


def test_near_duplicate_pairs_matches_brute_force():
    rng = random.Random(0)
    hashes = [rng.getrandbits(64) for _ in range(200)]
    hashes += [h ^ (1 << rng.randrange(64)) for h in hashes[:20]]  # 20 one-bit neighbours
    fast = {(i, j) for i, j, _ in near_duplicate_pairs(hashes, max_bits=3)}
    slow = {(i, j) for i in range(len(hashes)) for j in range(i + 1, len(hashes)) if hamming(hashes[i], hashes[j]) <= 3}
    assert fast == slow and len(fast) >= 20
    cross = near_duplicate_pairs(hashes[:5], hashes[200:205], max_bits=1)
    assert {(i, j) for i, j, _ in cross} == {(k, k) for k in range(5)}


# ---------------------------------------------------------------- splits

def test_split_assignment_is_stable_and_order_independent():
    groups = [f"site-{i}" for i in range(200)]
    first = {g: split_for_group(g, 42, 0.2, 0.1) for g in groups}
    second = {g: split_for_group(g, 42, 0.2, 0.1) for g in reversed(groups)}
    assert first == second
    share = sum(v == "gold" for v in first.values()) / len(groups)
    assert 0.1 < share < 0.3


def test_video_registry_freezes_assignments_and_keeps_groups_together(tmp_path):
    reg = VideoRegistry(tmp_path / "videos.json", seed=42, gold_fraction=0.2, val_fraction=0.1)
    a = reg.register("cam1_monday", group="gate1")
    b = reg.register("cam1_tuesday", group="gate1")
    assert a["split"] == b["split"]
    forced = reg.register("new_site_video", group="site-x", split="gold")
    assert forced["split"] == "gold"
    assert reg.register("new_site_video", split="pool")["split"] == "gold"   # frozen: no move
    with pytest.raises(ValueError):
        reg.register("cam1_wednesday", group="gate1", split="gold" if a["split"] != "gold" else "pool")


def test_leakage_check_finds_cross_split_near_duplicates_only():
    base = scene(7)
    same_split_twin = dhash(reencode(base))
    hashes = {
        "pool": [("p1", dhash(base)), ("p2", same_split_twin), ("p3", dhash(scene(8)))],
        "gold": [("g1", dhash(reencode(base, 50))), ("g2", dhash(scene(9))), ("g3", None)],
        "val": [("v1", dhash(scene(10)))],
    }
    leaks = leakage_check(hashes, max_bits=6)
    pairs = {(l.a_id, l.b_id) for l in leaks}
    assert {("g1", "p1"), ("g1", "p2")} <= pairs                     # gold vs pool twins found
    assert not any("p2" == l.a_id and "p1" == l.b_id for l in leaks)  # within-split pairs ignored
    assert not any("g3" in (l.a_id, l.b_id) for l in leaks)            # unreadable images skipped


# ---------------------------------------------------------------- hash-chained log

def test_chain_log_appends_and_verifies(tmp_path):
    log = ChainLog(tmp_path / "log.jsonl")
    for i in range(5):
        log.append({"action": "accept", "item": i})
    entries = log.entries()
    assert [e["seq"] for e in entries] == list(range(5)) and log.verify() == []
    assert entries[0]["prev_hash"] == "0" * 64 and entries[1]["prev_hash"] == entries[0]["hash"]
    with pytest.raises(ValueError):
        log.append({"seq": 99})


@pytest.mark.parametrize("tamper", ["edit", "delete", "reorder", "truncate_middle"])
def test_chain_log_detects_tampering(tmp_path, tamper):
    path = tmp_path / "log.jsonl"
    log = ChainLog(path)
    for i in range(4):
        log.append({"action": "accept", "item": i, "text": f"PB65AB000{i}"})
    lines = path.read_text().splitlines()
    if tamper == "edit":
        entry = json.loads(lines[1])
        entry["text"] = "FAKE"
        lines[1] = json.dumps(entry, sort_keys=True)
    elif tamper == "delete":
        del lines[2]
    elif tamper == "reorder":
        lines[1], lines[2] = lines[2], lines[1]
    else:
        lines = lines[:1] + lines[2:]
    path.write_text("\n".join(lines) + "\n")
    assert log.verify(), "tampering went unnoticed"
    with pytest.raises(ChainError):
        log.entries()
    with pytest.raises(ChainError):
        log.append({"action": "accept"})


def test_chain_log_concurrent_appends_stay_consistent(tmp_path):
    log = ChainLog(tmp_path / "log.jsonl")
    errors = []

    def worker(n):
        try:
            for i in range(25):
                log.append({"worker": n, "i": i})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and log.verify() == [] and len(log.entries()) == 100


# ---------------------------------------------------------------- manifest + config

def test_manifest_hash_is_order_independent(tmp_path):
    rows = [{"video_id": "v1", "frame_idx": i, "ts": i / 2} for i in range(10)]
    h1 = write_manifest(tmp_path / "m.jsonl", rows)
    assert h1 == manifest_hash(list(reversed(rows)))
    assert read_manifest(tmp_path / "m.jsonl") == sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, separators=(",", ":")))
    assert manifest_hash(rows[:-1]) != h1


def test_config_defaults_guardrails_and_hash(tmp_path):
    cfg = load_config()
    assert cfg.class_names == ["license_plate"] and cfg.train.fliplr == 0.0 and not cfg.review.auto_accept.enabled
    assert cfg.sha256() == load_config().sha256()
    with pytest.raises(ValueError):
        Config.model_validate({"train": {"fliplr": 0.5}})
    with pytest.raises(ValueError):
        Config.model_validate({"class_names": ["plate", "car"]})
    assert load_config(data_root=str(tmp_path)).data_root == tmp_path
    assert np.isclose(cfg.train.replay_fraction, 0.30)
