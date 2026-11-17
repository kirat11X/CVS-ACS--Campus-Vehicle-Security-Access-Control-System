"""
Comprehensive Review Tests for Track A:
- Normalization, Indian plate formats, confusion variants
- Multi-reader candidate ranking & scoring
- Registry-constrained fuzzy matching, ambiguity margins, tie-breaking
- Resolver adapter compatibility
- Evaluation metrics, CER, Levenshtein, error breakdown
- ANPR pipeline Baselines 0-3
"""

from decimal import Decimal
import os
import pytest
from typing import List

from research_track.track_a.src.normalization import (
    PlateNormalizer,
    NormalizedPlate,
    normalize_plate,
    INDIAN_STATE_CODES,
    OCR_CONFUSION_MAP,
)
from research_track.track_a.src.candidate_ranking import (
    OCRCandidate,
    RankedCandidate,
    OCRCandidateRanker,
)
from research_track.track_a.src.registry_matcher import (
    RegistryMatcher,
    RegistryRecord,
    RegistryMatchResult,
    MatchCandidate,
    MatchStatus,
    is_ocr_confusion,
    weighted_levenshtein,
    compute_string_similarity,
)
from research_track.track_a.src.resolver_adapter import Phase5AResolverAdapter
from research_track.track_a.src.metrics import (
    standard_levenshtein,
    calculate_cer,
    ErrorBreakdown,
    EvaluationSummary,
    MetricCalculator,
)
from research_track.track_a.src.pipeline import ANPRPipeline, PipelineResult


# ==============================================================================
# 1. Normalization & Plate Syntax Tests
# ==============================================================================

def test_normalization_formats():
    norm = PlateNormalizer()

    # Standard format
    res_std = norm.normalize("pb-65-ab-0902")
    assert res_std.is_valid_format
    assert res_std.format_type == "STANDARD_INDIAN"
    assert res_std.state_code == "PB"
    assert res_std.district_code == "65"
    assert res_std.series_code == "AB"
    assert res_std.number_code == "0902"
    assert res_std.status == "VALID"

    # Bharat (BH) series format
    res_bh = norm.normalize("22BH1234AA")
    assert res_bh.is_valid_format
    assert res_bh.format_type == "BH_SERIES"
    assert res_bh.status == "VALID"

    # Military format
    res_mil = norm.normalize("21D123456A")
    assert res_mil.is_valid_format
    assert res_mil.format_type == "MILITARY"
    assert res_mil.status == "VALID"

    # Diplomatic format
    res_dip = norm.normalize("22CD1234")
    assert res_dip.is_valid_format
    assert res_dip.format_type == "DIPLOMATIC"
    assert res_dip.status == "VALID"

    # Malformed too short
    res_short = norm.normalize("PB1")
    assert not res_short.is_valid_format
    assert res_short.format_type == "MALFORMED_TOO_SHORT"
    assert res_short.status in ("UNREADABLE", "INVALID_FORMAT")

    # Malformed too long
    res_long = norm.normalize("PB65AB09021234567")
    assert not res_long.is_valid_format
    assert res_long.format_type == "MALFORMED_TOO_LONG"
    assert res_long.status in ("UNREADABLE", "INVALID_FORMAT")

    # Standard syntax with invalid state code
    res_bad_state = norm.normalize("ZZ01AB1234")
    assert not res_bad_state.is_valid_format
    assert res_bad_state.format_type == "STANDARD_INDIAN"
    assert res_bad_state.status == "INVALID_FORMAT"

    # Empty whitespace
    res_empty = norm.normalize("   ")
    assert not res_empty.is_valid_format
    assert res_empty.status == "UNREADABLE"

    # Non-standard alphanumeric of valid length
    res_nonstd = norm.normalize("ABCDEFGH")
    assert not res_nonstd.is_valid_format
    assert res_nonstd.format_type == "NON_STANDARD"

    # Functional convenience normalize_plate
    res_fn = normalize_plate("CH01AA1111")
    assert res_fn.is_valid_format
    assert res_fn.clean_text == "CH01AA1111"

    # clean_string helper
    clean, _ = norm.clean_string("  p-b. 65 ! ")
    assert clean == "PB65"
    clean_empty, _ = norm.clean_string("")
    assert clean_empty == ""


def test_confusion_variants_generation():
    norm = PlateNormalizer(enable_variant_generation=True, max_variants=4)

    # Plate with digit 0 in state position: "0B65AB0902" -> '0' replaced with 'O'
    res_state = norm.normalize("0B65AB0902")
    assert len(res_state.confusion_variants) > 0
    assert any("OB65AB0902" in v[0] for v in res_state.confusion_variants)

    # Plate with letter 'O' in district position: "PBOSAB0902" -> 'O' replaced with '0'
    res_dist = norm.normalize("PBOSAB0902")
    assert len(res_dist.confusion_variants) > 0

    # Plate with letter 'O' or 'B' in number block: "PB65AB09O2" -> 'O' replaced with '0'
    res_num = norm.normalize("PB65AB09O2")
    assert len(res_num.confusion_variants) > 0
    assert any("PB65AB0902" in v[0] for v in res_num.confusion_variants)


# ==============================================================================
# 2. Candidate Ranking Tests
# ==============================================================================

def test_ocr_candidate_ranker_scoring():
    ranker = OCRCandidateRanker()

    cands = [
        OCRCandidate(raw_text="PB65AB0902", source="camera_primary", confidence=0.95),
        OCRCandidate(raw_text="PB65AB0902", source="paddleocr_vl", confidence=None),  # missing confidence
        OCRCandidate(raw_text="PB65", source="fallback", confidence=0.40),             # too short
        OCRCandidate(raw_text="PB65AB0902ZZZZ", source="fallback", confidence=1.50),  # clipped confidence
    ]

    ranked = ranker.rank_candidates(cands)
    assert len(ranked) == 4
    assert ranked[0].rank == 1
    assert ranked[0].ranking_score >= ranked[1].ranking_score
    assert ranked[0].has_confidence is True
    assert ranked[1].has_confidence is False  # defaulted to neutral
    assert ranked[3].component_scores["confidence_score"] <= 1.0  # clipped from 1.50

    # Empty candidate list
    assert ranker.rank_candidates([]) == []


# ==============================================================================
# 3. Registry Constrained Matcher & Ambiguity Tests
# ==============================================================================

def test_weighted_levenshtein_and_similarity():
    # Identical
    assert is_ocr_confusion("O", "0") is True
    assert is_ocr_confusion("A", "B") is False
    assert weighted_levenshtein("PB01", "PB01") == 0.0
    assert compute_string_similarity("PB01", "PB01") == 1.0

    # Optical confusion vs arbitrary substitution
    conf_dist = weighted_levenshtein("PBO1", "PB01")   # O vs 0
    norm_dist = weighted_levenshtein("PBX1", "PB01")   # X vs 0
    assert conf_dist < norm_dist

    # Empty strings
    assert compute_string_similarity("", "") == 1.0
    assert compute_string_similarity("PB01", "") == 0.0


def test_registry_matcher_logic():
    records = [
        RegistryRecord(registry_id="REG-01", plate="PB65AB0902"),
        RegistryRecord(registry_id="REG-02", plate="PB65AB0903"),  # near duplicate (1 char diff)
        RegistryRecord(registry_id="REG-03", plate="CH01AA1111"),
    ]
    matcher = RegistryMatcher(registry=records, min_similarity_threshold=0.80, ambiguity_margin=0.08)

    # Empty input
    res_empty = matcher.match("")
    assert res_empty.status == MatchStatus.INVALID_INPUT

    # Exact match
    res_exact = matcher.match("PB65AB0902")
    assert res_exact.status == MatchStatus.EXACT_MATCH
    assert res_exact.matched_record.registry_id == "REG-01"
    assert res_exact.similarity_score == 1.0
    assert res_exact.is_ambiguous is False

    # Ambiguous near-tie: "PB65AB0900" is equidistant to REG-01 (0902) and REG-02 (0903)
    res_ambig = matcher.match("PB65AB0900")
    assert res_ambig.status == MatchStatus.AMBIGUOUS
    assert res_ambig.is_ambiguous is True
    assert res_ambig.score_margin < 0.08

    # Confident fuzzy match (CH01AA111O has optical confusion O vs 1 with CH01AA1111, distant from PB records)
    res_fuzzy = matcher.match("CH01AA111I")  # I vs 1
    assert res_fuzzy.status == MatchStatus.FUZZY_CONFIDENT
    assert res_fuzzy.matched_record.registry_id == "REG-03"

    # No match
    res_nomatch = matcher.match("DL04ZZ9999")
    assert res_nomatch.status == MatchStatus.NO_MATCH


# ==============================================================================
# 4. Phase 5A Resolver Adapter Tests
# ==============================================================================

def test_resolver_adapter_contract():
    # Empty candidates
    obs_empty = Phase5AResolverAdapter.to_phase5a_observation([])
    assert obs_empty["plate"] is None

    # Ranked candidates
    norm = normalize_plate("PB65AB0902")
    cand = OCRCandidate(raw_text="PB65AB0902", source="camera", confidence=0.92, normalized=norm)
    ranked = RankedCandidate(
        candidate=cand,
        rank=1,
        ranking_score=0.95,
        has_confidence=True,
        component_scores={},
        explanation="test"
    )
    obs = Phase5AResolverAdapter.to_phase5a_observation([ranked], observation_id="OBS-100")
    assert obs["observation_id"] == "OBS-100"
    assert obs["plate"] == "PB65AB0902"
    assert obs["plate_confidence"] == 0.92

    # from_phase5a_result mapping
    class MockResult:
        def __init__(self, status, method, sim=1.0):
            self.identity_status = status
            self.match_method = method
            self.match_similarity = sim
            self.vehicle = {"id": "V-1", "plate": "PB65AB0902"}
            self.candidates = []

    res_known = Phase5AResolverAdapter.from_phase5a_result(MockResult("KNOWN", "EXACT_NORMALIZED"))
    assert res_known.status == MatchStatus.EXACT_MATCH
    assert res_known.matched_plate == "PB65AB0902"

    res_fuzzy = Phase5AResolverAdapter.from_phase5a_result(MockResult("KNOWN", "FUZZY_CONFIDENT", 0.88))
    assert res_fuzzy.status == MatchStatus.FUZZY_CONFIDENT

    res_ambig = Phase5AResolverAdapter.from_phase5a_result(MockResult("AMBIGUOUS", "AMBIGUOUS_CANDIDATES"))
    assert res_ambig.status == MatchStatus.AMBIGUOUS

    res_unknown = Phase5AResolverAdapter.from_phase5a_result(MockResult("UNKNOWN", "NO_CANDIDATE"))
    assert res_unknown.status == MatchStatus.NO_MATCH

    res_dict = Phase5AResolverAdapter.from_phase5a_result({"identity_status": "UNKNOWN", "match_method": "NO_CANDIDATE"})
    assert res_dict.status == MatchStatus.NO_MATCH


# ==============================================================================
# 5. Offline Metrics & Error Taxonomy Tests
# ==============================================================================

def test_offline_metrics_and_error_breakdown():
    # Levenshtein & CER
    assert standard_levenshtein("PB65", "PB65") == 0
    assert standard_levenshtein("PB65", "PB66") == 1
    assert calculate_cer("PB65", "PB65") == 0.0
    assert calculate_cer("PB65", "PB66") == 0.25
    assert calculate_cer("", "") == 0.0
    assert calculate_cer("PB65", "") == 1.0

    # Error classification
    errs = MetricCalculator.classify_plate_errors("PB65AB0902", "PB65AB0902")
    assert sum(errs.values()) == 0

    # Optical confusion: O vs 0
    errs_opt = MetricCalculator.classify_plate_errors("PB65ABO902", "PB65AB0902")
    assert errs_opt["substitutions"] == 1
    assert errs_opt["optical_confusions"] == 1
    assert errs_opt["non_optical_substitutions"] == 0

    # Insertions, deletions, state errors
    errs_diff = MetricCalculator.classify_plate_errors("CH65AB09021", "PB65AB0902")
    assert errs_diff["insertions"] == 1
    assert errs_diff["state_code_errors"] == 1

    # compute_metrics empty list
    summary_empty = MetricCalculator.compute_metrics([])
    assert summary_empty.total_samples == 0

    # compute_metrics with evaluation records
    records = [
        {
            "observed_plate": "PB65AB0902",
            "ground_truth_plate": "PB65AB0902",
            "status": "EXACT_MATCH",
            "matched_registry_id": "REG-1",
            "expected_registry_id": "REG-1",
            "expected_status": "EXACT_MATCH",
            "latency_ms": 12.5,
        },
        {
            "observed_plate": "PB65AB0903",
            "ground_truth_plate": "PB65AB0902",
            "status": "FUZZY_CONFIDENT",
            "matched_registry_id": "REG-2",
            "expected_registry_id": "REG-1",  # False match
            "expected_status": "EXACT_MATCH",
            "latency_ms": 15.0,
        },
        {
            "observed_plate": "DL01ZZ0000",
            "ground_truth_plate": "DL01ZZ0000",
            "status": "NO_MATCH",
            "matched_registry_id": None,
            "expected_registry_id": None,
            "expected_status": "NO_MATCH",
            "latency_ms": 8.0,
        },
        {
            "observed_plate": "PB65AB0900",
            "ground_truth_plate": "PB65AB0902",
            "status": "AMBIGUOUS",
            "matched_registry_id": None,
            "expected_registry_id": None,
            "expected_status": "AMBIGUOUS",
            "latency_ms": 10.0,
        },
    ]

    summary = MetricCalculator.compute_metrics(records, baseline_id="baseline_3")
    assert summary.total_samples == 4
    assert summary.exact_plate_accuracy == 0.5  # 2 exact plates out of 4
    assert summary.false_match_rate_matched > 0.0
    assert summary.no_match_rate == 0.25
    assert summary.ambiguity_rate == 0.25
    assert summary.latency_mean_ms is not None

    summary_dict = summary.to_dict()
    assert summary_dict["baseline_id"] == "baseline_3"
    assert "error_breakdown" in summary_dict

    md_table = summary.format_markdown_table()
    assert "Baseline `baseline_3` Performance Summary" in md_table


# ==============================================================================
# 6. ANPR Pipeline Baselines 0-3 Execution Tests
# ==============================================================================

def test_anpr_pipeline_baselines():
    pipeline = ANPRPipeline.from_config("research_track/track_a/config.yaml")

    cands = [
        OCRCandidate(raw_text="PB65AB0902", source="camera_primary", confidence=0.98),
        OCRCandidate(raw_text="PB65AB090O", source="paddleocr_vl", confidence=0.85),
    ]

    for b_id in ["baseline_0", "baseline_1", "baseline_2", "baseline_3"]:
        res = pipeline.process(cands, baseline_id=b_id)
        assert isinstance(res, PipelineResult)
        res_dict = res.to_dict()
        assert res_dict["baseline_id"] == b_id
        assert "status" in res_dict


def test_plate_normalizer_statutory_patterns():
    from research_track.track_a.src.plate_normalizer import is_valid_indian_plate
    norm = PlateNormalizer()

    # Delhi commercial category
    res_dl = norm.normalize("DL1C1234")
    assert res_dl.is_valid_format
    assert any("Delhi vehicle category" in n for n in res_dl.validation_notes)

    # Legacy state
    res_legacy = norm.normalize("UA01AB1234")
    assert res_legacy.is_valid_format
    assert any("Former state/UT code" in n for n in res_legacy.validation_notes)

    # Vintage plate: State (2 letters) + VA + Series (2 letters) + Number (4 digits)
    res_vin = norm.normalize("DLVAAB1234")
    assert res_vin.is_valid_format
    assert res_vin.format_type == "VINTAGE"

    # Temporary plate: T + Month + Year + State + Number + Series (1 letter)
    res_tmp = norm.normalize("T0524DL1234A")
    assert res_tmp.is_valid_format
    assert res_tmp.format_type == "TEMPORARY"

    # Trade certificate
    res_trd = norm.normalize("DL01TC1234")
    assert res_trd.is_valid_format
    assert res_trd.format_type == "COMMERCIAL_TRADE"

    # Statutory violations: single digit RTO outside Delhi
    res_rto = norm.normalize("PB1AB1234")
    assert not res_rto.is_valid_format

    # Number 0000
    res_0000 = norm.normalize("PB65AB0000")
    assert not res_0000.is_valid_format

    # Series contains I or O
    res_io = norm.normalize("PB65AI1234")
    assert not res_io.is_valid_format

    # is_valid_indian_plate helper
    assert is_valid_indian_plate("PB65AB0902") is True
    assert is_valid_indian_plate("ZZZZZZZZ") is False


def test_anpr_pipeline_dataset_evaluation():
    pipeline = ANPRPipeline.from_config("research_track/track_a/config.yaml")
    csv_path = "research_track/track_a/fixtures/labeled_examples.csv"
    assert os.path.exists(csv_path)
    examples = pipeline.load_examples_from_csv(csv_path)
    assert len(examples) > 0
    summary = pipeline.evaluate_dataset(examples[:10], baseline_id="baseline_3")
    assert summary.total_samples == 10

