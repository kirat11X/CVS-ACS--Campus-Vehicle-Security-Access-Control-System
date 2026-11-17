"""
Track C: Item Taxonomy Dataset Integrity & Canonical Seed Verification Tests.

Validates DATA-001 requirements:
- seed_items.csv and track_c fixtures/item_taxonomy_seed.csv are synchronized.
- Verified canonical count is exactly 320 items across 8 institutional security categories.
- Headers are identical and formatting is valid.
- No null or blank item texts exist.
- Category strings map 1:1 to recognized ItemCategoryCode taxonomy enums.
"""

import csv
from pathlib import Path
import pytest

from research_track.track_c.src.category_normalization import CategoryNormalizer
from research_track.track_c.src.types import ItemCategoryCode

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SEED_DATASET_PATH = REPO_ROOT / "research_track/datasets/item_taxonomy_seed/seed_items.csv"
FIXTURE_TAXONOMY_PATH = REPO_ROOT / "research_track/track_c/fixtures/item_taxonomy_seed.csv"

EXPECTED_HEADER = ["item_text", "category", "style"]
CANONICAL_ROW_COUNT = 320

EXPECTED_CATEGORY_COUNTS = {
    "NORMAL": 140,
    "TOBACCO_NICOTINE": 30,
    "ALCOHOL": 30,
    "OTC_MEDICINE": 30,
    "RX_SCHEDULED_DRUG": 25,
    "HAZARDOUS_CHEMICAL": 25,
    "SHARP_OBJECT": 20,
    "UNKNOWN": 20,
}


def _read_taxonomy_csv(path: Path):
    assert path.exists(), f"Taxonomy file missing: {path}"
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    assert len(rows) > 0, f"Taxonomy file empty: {path}"
    header = rows[0]
    data_rows = rows[1:]
    return header, data_rows


def test_taxonomy_files_exist():
    """Both dataset seed and Track C fixture files must exist."""
    assert SEED_DATASET_PATH.exists(), f"Missing {SEED_DATASET_PATH}"
    assert FIXTURE_TAXONOMY_PATH.exists(), f"Missing {FIXTURE_TAXONOMY_PATH}"


def test_taxonomy_headers_identical():
    """Both files must have exact identical headers matching canonical format."""
    seed_header, _ = _read_taxonomy_csv(SEED_DATASET_PATH)
    fixture_header, _ = _read_taxonomy_csv(FIXTURE_TAXONOMY_PATH)

    assert seed_header == EXPECTED_HEADER, f"Unexpected seed header: {seed_header}"
    assert fixture_header == EXPECTED_HEADER, f"Unexpected fixture header: {fixture_header}"
    assert seed_header == fixture_header, "Headers between seed and fixture do not match"


def test_canonical_row_count_exactly_320():
    """Both files must contain exactly 320 canonical taxonomy rows (DATA-001)."""
    _, seed_rows = _read_taxonomy_csv(SEED_DATASET_PATH)
    _, fixture_rows = _read_taxonomy_csv(FIXTURE_TAXONOMY_PATH)

    assert len(seed_rows) == CANONICAL_ROW_COUNT, (
        f"seed_items.csv has {len(seed_rows)} rows, expected exactly {CANONICAL_ROW_COUNT}"
    )
    assert len(fixture_rows) == CANONICAL_ROW_COUNT, (
        f"fixtures/item_taxonomy_seed.csv has {len(fixture_rows)} rows, expected exactly {CANONICAL_ROW_COUNT}"
    )


def test_files_are_content_identical():
    """Both CSV files must contain identical rows in identical sequence."""
    _, seed_rows = _read_taxonomy_csv(SEED_DATASET_PATH)
    _, fixture_rows = _read_taxonomy_csv(FIXTURE_TAXONOMY_PATH)

    assert seed_rows == fixture_rows, "Row content mismatch between seed_items.csv and fixtures/item_taxonomy_seed.csv"


def test_taxonomy_category_distribution():
    """Taxonomy must span all 8 institutional security categories with exact class balance."""
    _, data_rows = _read_taxonomy_csv(FIXTURE_TAXONOMY_PATH)

    counts = {}
    for row in data_rows:
        assert len(row) == 3, f"Malformed row (expected 3 columns): {row}"
        item_text, category, style = row
        assert item_text.strip(), f"Empty item_text found in row: {row}"
        counts[category] = counts.get(category, 0) + 1

    assert counts == EXPECTED_CATEGORY_COUNTS, (
        f"Category distribution mismatch: observed {counts}, expected {EXPECTED_CATEGORY_COUNTS}"
    )
    assert sum(counts.values()) == CANONICAL_ROW_COUNT


def test_every_taxonomy_item_normalizes_to_valid_enum():
    """Every category string in the 320 rows must normalize via CategoryNormalizer."""
    _, data_rows = _read_taxonomy_csv(FIXTURE_TAXONOMY_PATH)

    for row in data_rows:
        item_text, category_str, _ = row
        normalized = CategoryNormalizer.normalize(category_str)
        assert isinstance(normalized, ItemCategoryCode)
        assert normalized.value == category_str


def test_bug_tester_data_001_check():
    """Verifies that cvs_acs_bug_tester.py's check_taxonomy_row_counts passes."""
    import json
    import subprocess
    import sys
    import tempfile

    tester_path = REPO_ROOT / "research/cvs_acs_bug_tester.py"
    assert tester_path.exists(), f"Missing bug tester at {tester_path}"

    with tempfile.NamedTemporaryFile(suffix=".json", mode="w+", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        proc = subprocess.run(
            [sys.executable, str(tester_path), "--repo-root", str(REPO_ROOT), "--json-out", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert tmp_path.exists(), f"JSON report was not generated: {proc.stderr}"
        report = json.loads(tmp_path.read_text(encoding="utf-8"))
        data_001_results = [r for r in report["results"] if r["check_id"] == "DATA-001"]
        assert len(data_001_results) == 1, f"Expected 1 DATA-001 result, got {data_001_results}"
        assert data_001_results[0]["status"] == "PASS", f"DATA-001 failed: {data_001_results[0]}"
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
