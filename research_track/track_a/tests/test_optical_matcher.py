"""
Unit and integration tests for OpticalPlateMatcher and Ambiguity Margin enforcement.
Verifies exact matches, optical OCR confusion discounting, and guarantees
0.0% false match rate on near-duplicate plates when ambiguous (Delta < 0.07).
"""

import pytest
from research_track.track_a.src.plate_normalizer import normalize_plate
from research_track.track_a.src.registry_matcher import (
    MatchStatus,
    OpticalPlateMatcher,
    RegistryMatcher,
    RegistryRecord,
    compute_string_similarity,
    weighted_levenshtein,
)


class TestOpticalPlateMatcherExactAndFuzzy:
    """Verifies baseline exact matching and confident fuzzy resolution."""

    @pytest.fixture
    def matcher(self):
        records = [
            "CH01AB1234",
            "PB65AK1122",
            "HR70A1234",
            "DL01AA1234",
            "22BH2345CD",
        ]
        return OpticalPlateMatcher(registry=records, min_similarity_threshold=0.82, ambiguity_margin=0.07)

    def test_exact_match_fast_path(self, matcher):
        res = matcher.match("CH01AB1234")
        assert res.status == MatchStatus.EXACT_MATCH
        assert res.matched_plate == "CH01AB1234"
        assert res.similarity_score == 1.0
        assert res.score_margin == 1.0
        assert res.is_ambiguous is False

    def test_exact_match_with_normalized_plate_object(self, matcher):
        norm = normalize_plate("  ch-01-ab-1234  ")
        res = matcher.match(norm)
        assert res.status == MatchStatus.EXACT_MATCH
        assert res.matched_plate == "CH01AB1234"

    def test_optical_ocr_confusion_discounting(self, matcher):
        # 'O' in place of '0' should incur reduced penalty (0.25 vs 1.0)
        res = matcher.match("CHO1AB1234")
        assert res.status == MatchStatus.FUZZY_CONFIDENT
        assert res.matched_plate == "CH01AB1234"
        assert res.similarity_score >= 0.95
        assert res.score_margin >= 0.07
        assert res.is_ambiguous is False

    def test_i_vs_1_optical_confusion(self, matcher):
        # 'I' in place of '1' in numeric position
        res = matcher.match("PB65AKI122")
        assert res.status == MatchStatus.FUZZY_CONFIDENT
        assert res.matched_plate == "PB65AK1122"
        assert res.similarity_score >= 0.95

    def test_out_of_registry_returns_no_match(self, matcher):
        res = matcher.match("UP16AB1234")
        assert res.status == MatchStatus.NO_MATCH
        assert res.matched_record is None
        assert res.matched_plate is None

    def test_empty_input_returns_invalid_input(self, matcher):
        res_empty = matcher.match("")
        assert res_empty.status == MatchStatus.INVALID_INPUT
        res_none = matcher.match(None)
        assert res_none.status == MatchStatus.INVALID_INPUT


class TestNearDuplicateAmbiguityMarginRejection:
    """
    Verifies that OpticalPlateMatcher enforces Delta >= 0.07 ambiguity margin
    and achieves strictly 0.0% false match rate on near-duplicate plates.
    """

    def test_near_duplicate_dl01ab1234_vs_dl01ab1235(self):
        # Registry has two plates differing only in the last digit (4 vs 5)
        registry = ["DL01AB1234", "DL01AB1235"]
        matcher = OpticalPlateMatcher(registry=registry, min_similarity_threshold=0.82, ambiguity_margin=0.07)

        # Query DL01AB1230 is equidistant from both (1 substitution edit away from each)
        res_ambiguous = matcher.match("DL01AB1230")
        assert res_ambiguous.status == MatchStatus.AMBIGUOUS
        assert res_ambiguous.is_ambiguous is True
        assert res_ambiguous.matched_record is None  # MUST NOT GUESS!
        assert res_ambiguous.matched_plate is None
        assert res_ambiguous.score_margin < 0.07

        # Query DL01AB1239 is also equidistant
        res_ambiguous_9 = matcher.match("DL01AB1239")
        assert res_ambiguous_9.status == MatchStatus.AMBIGUOUS
        assert res_ambiguous_9.matched_record is None
        assert res_ambiguous_9.matched_plate is None

    def test_near_duplicate_dl01ab1234_vs_dl01ab1284(self):
        # Plates differing by '3' vs '8' in number block
        registry = ["DL01AB1234", "DL01AB1284"]
        matcher = OpticalPlateMatcher(registry=registry, min_similarity_threshold=0.82, ambiguity_margin=0.07)

        # Query DL01AB1204 is equidistant to both (1 substitution away from each)
        res_ambiguous = matcher.match("DL01AB1204")
        assert res_ambiguous.status == MatchStatus.AMBIGUOUS
        assert res_ambiguous.is_ambiguous is True
        assert res_ambiguous.matched_record is None
        assert res_ambiguous.matched_plate is None
        assert res_ambiguous.score_margin < 0.07

    def test_all_five_synthetic_near_duplicate_ambiguity_pairs_category8(self):
        """
        Tests the 5 canonical near-duplicate pairs defined in:
        research_track/track_a/tests/test_cases.md (Category 8: EX-056 to EX-060)
        and IMPLEMENTATION_REPORT.md.
        """
        registry_records = [
            RegistryRecord("REG-001", "CH01AB1001"),
            RegistryRecord("REG-002", "CH01AB1007"),
            RegistryRecord("REG-003", "PB65AB2222"),
            RegistryRecord("REG-004", "PB65AB2228"),
            RegistryRecord("REG-005", "HR26DQ0001"),
            RegistryRecord("REG-006", "HR26DO0001"),
            RegistryRecord("REG-007", "DL08CA5555"),
            RegistryRecord("REG-008", "DL08CA5558"),
            RegistryRecord("REG-009", "22BH1001AA"),
            RegistryRecord("REG-010", "22BH1001AB"),
        ]

        matcher = OpticalPlateMatcher(
            registry=registry_records,
            min_similarity_threshold=0.82,
            ambiguity_margin=0.07,
            ocr_confusion_penalty=0.25,
        )

        test_cases = [
            ("EX-056", "CH01AB1000", ("CH01AB1001", "CH01AB1007")),
            ("EX-057", "PB65AB2225", ("PB65AB2222", "PB65AB2228")),
            ("EX-058", "HR26D00001", ("HR26DQ0001", "HR26DO0001")),
            ("EX-059", "DL08CA5556", ("DL08CA5555", "DL08CA5558")),
            ("EX-060", "22BH1001A",  ("22BH1001AA", "22BH1001AB")),
        ]

        false_matches = 0
        ambiguous_rejections = 0

        for case_id, query, (cand1, cand2) in test_cases:
            res = matcher.match(query)
            if res.matched_record is not None:
                false_matches += 1
            if res.status == MatchStatus.AMBIGUOUS:
                ambiguous_rejections += 1
                assert res.is_ambiguous is True
                assert res.score_margin < 0.07
                qualifying_plates = [c.record.plate for c in res.qualifying_candidates]
                assert cand1 in qualifying_plates or cand2 in qualifying_plates

        # Safety Guarantee: False match rate on ambiguous queries MUST be strictly 0.0%
        false_match_rate = false_matches / len(test_cases)
        assert false_match_rate == 0.0, f"False match rate was {false_match_rate:.2%}, expected 0.0%"
        assert ambiguous_rejections == len(test_cases), f"Expected all {len(test_cases)} to be rejected as AMBIGUOUS"

    def test_naive_fuzzy_matcher_vulnerability_contrast(self):
        """
        Contrasts OpticalPlateMatcher against naive fuzzy matching without ambiguity margin,
        verifying that naive fuzzy yields 100% false matches on equidistant pairs.
        """
        registry_records = [
            RegistryRecord("REG-001", "CH01AB1001"),
            RegistryRecord("REG-002", "CH01AB1007"),
        ]

        # Naive matcher with ambiguity_margin = 0.0 (Baseline 2)
        naive_matcher = RegistryMatcher(
            registry=registry_records,
            min_similarity_threshold=0.82,
            ambiguity_margin=0.00,
        )

        # Safe matcher with ambiguity_margin = 0.07 (Baseline 3)
        safe_matcher = OpticalPlateMatcher(
            registry=registry_records,
            min_similarity_threshold=0.82,
            ambiguity_margin=0.07,
        )

        query = "CH01AB1000"

        # Naive matcher incorrectly asserts a match (blindly accepts top hit)
        naive_res = naive_matcher.match(query)
        assert naive_res.status == MatchStatus.FUZZY_CONFIDENT
        assert naive_res.matched_record is not None  # Vulnerability: False certainty!

        # OpticalPlateMatcher safely rejects
        safe_res = safe_matcher.match(query)
        assert safe_res.status == MatchStatus.AMBIGUOUS
        assert safe_res.matched_record is None
        assert safe_res.is_ambiguous is True
