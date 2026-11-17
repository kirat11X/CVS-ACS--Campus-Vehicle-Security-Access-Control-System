import math

import pytest

from anpr_hitl.config import PromoteConfig, load_config
from anpr_hitl.promote import promotion_gate
from anpr_hitl.registry import Registry, RegistryError
from anpr_hitl.store import Store

GOLD = "gold-sha"


def metrics(map50_95=0.50, exact=0.70, slices=None, gold=GOLD, ci=None):
    m = {"gold_manifest_sha256": gold, "detection": {"map50_95": map50_95, "map50": 0.8}, "slices": slices or {}}
    if exact is not None:
        m["ocr"] = {"exact": exact}
    if ci is not None:
        m["paired_gain_ci_pt"] = ci
    return m


CFG = PromoteConfig()  # +1 pt mAP50-95 or +2 pt exact; slices may drop <= 2 pt when n >= 30


def test_first_model_becomes_champion():
    assert promotion_gate(metrics(), None, CFG).promote


@pytest.mark.parametrize("gain_pt, expected", [(1.0, True), (0.99, False), (1.01, True), (0.0, False), (-3.0, False)])
def test_map_threshold_is_inclusive(gain_pt, expected):
    champion = metrics(map50_95=0.5000, exact=0.70)
    candidate = metrics(map50_95=0.5000 + gain_pt / 100, exact=0.70)
    assert promotion_gate(candidate, champion, CFG).promote is expected


@pytest.mark.parametrize("gain_pt, expected", [(2.0, True), (1.99, False)])
def test_exact_match_alone_can_promote(gain_pt, expected):
    champion = metrics(map50_95=0.50, exact=0.700)
    candidate = metrics(map50_95=0.50, exact=0.700 + gain_pt / 100)
    assert promotion_gate(candidate, champion, CFG).promote is expected


@pytest.mark.parametrize("drop_pt, expected", [(2.0, True), (2.01, False), (0.5, True)])
def test_slice_regression_limit(drop_pt, expected):
    champion = metrics(0.50, slices={"det:night": {"n": 40, "value": 0.80}})
    candidate = metrics(0.52, slices={"det:night": {"n": 40, "value": 0.80 - drop_pt / 100}})
    decision = promotion_gate(candidate, champion, CFG)
    assert decision.promote is expected
    assert decision.slice_changes_pt["det:night"] == pytest.approx(-drop_pt)


def test_small_slices_are_reported_but_not_gated():
    champion = metrics(0.50, slices={"det:rain": {"n": 12, "value": 0.9}})
    candidate = metrics(0.52, slices={"det:rain": {"n": 12, "value": 0.5}})
    assert promotion_gate(candidate, champion, CFG).promote


def test_missing_slice_or_nan_or_other_gold_is_rejected():
    champion = metrics(0.50, slices={"ocr:state=PB": {"n": 50, "value": 0.7}})
    assert not promotion_gate(metrics(0.60, slices={}), champion, CFG).promote
    assert not promotion_gate(metrics(math.nan), metrics(0.5), CFG).promote
    assert not promotion_gate(metrics(0.60, exact=math.inf), metrics(0.5), CFG).promote
    assert not promotion_gate(metrics(0.60, gold="other-gold"), metrics(0.5), CFG).promote
    assert not promotion_gate(metrics(0.60, exact=None), metrics(0.5, exact=0.7), CFG).promote


def test_optional_significance_requirement():
    strict = PromoteConfig(require_significant=True)
    champion = metrics(0.50)
    noisy = metrics(0.515, ci={"map50_95": [-0.4, 3.1]})
    solid = metrics(0.515, ci={"map50_95": [0.3, 2.8]})
    assert promotion_gate(noisy, champion, CFG).promote          # default: thresholds only
    assert not promotion_gate(noisy, champion, strict).promote
    assert promotion_gate(solid, champion, strict).promote


# ---------------------------------------------------------------- registry

@pytest.fixture
def registry(tmp_path):
    store = Store(tmp_path)
    reg = Registry(store)
    weights = []
    for i in range(3):
        w = tmp_path / f"w{i}.pt"
        w.write_bytes(f"weights-{i}".encode())
        weights.append(w)
    return reg, weights, store


def test_register_promote_rollback_cycle(registry):
    reg, weights, _ = registry
    cfg = load_config()
    v1 = reg.register(weights[0], cfg, "data-1", "r00", metrics(0.40))["version"]
    assert reg.champion() is None
    reg.promote(v1, {"promote": True}, "test")
    v2 = reg.register(weights[1], cfg, "data-2", "r01", metrics(0.45), parent=v1)["version"]
    reg.promote(v2, {"promote": True}, "test")
    v3 = reg.register(weights[2], cfg, "data-3", "r02", metrics(0.44), parent=v2)["version"]
    reg.reject(v3, {"promote": False}, "test")
    assert (v1, v2, v3) == ("v0001", "v0002", "v0003")
    assert reg.champion()["version"] == v2
    reg.rollback(v1, "night regression found in the field", "kirat")
    assert reg.champion()["version"] == v1
    with pytest.raises(RegistryError):
        reg.rollback(v3, "never champion", "kirat")
    with pytest.raises(RegistryError):
        reg.rollback(v1, "already champion", "kirat")
    record = reg.models()[v2]
    assert record["git_sha"] and record["config_sha256"] == cfg.sha256() and record["parent"] == v1
    assert reg.verify() == []


def test_modified_weights_are_detected(registry):
    reg, weights, store = registry
    v1 = reg.register(weights[0], load_config(), "d", "r00", metrics())["version"]
    reg.promote(v1, {}, "t")
    (store.root / reg.models()[v1]["weights"]).write_bytes(b"swapped")
    assert any("modified" in p for p in reg.verify())
    with pytest.raises(RegistryError):
        reg.champion()
