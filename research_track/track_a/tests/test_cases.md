# Track A: Evaluation Test Cases & Baseline Outcome Matrix

This document provides the formal test case matrix for evaluating the Indian ANPR research prototype across Baselines 0 through 3. All 60 test cases correspond directly to `fixtures/labeled_examples.csv` and evaluate performance against `fixtures/synthetic_registry.csv`.

---

## 1. Baseline Definitions

- **Baseline 0 (`B0`)**: **Normalized Exact Matching Only**  
  Selects the first OCR candidate as-is, strips whitespace/separators, converts to uppercase, and performs exact string lookup in the registry hash table. No candidate ranking; no fuzzy matching.
- **Baseline 1 (`B1`)**: **Best OCR Candidate + Normalized Exact**  
  Ranks multiple OCR candidates using `OCRCandidateRanker` (weighting confidence, Indian regex syntax plausibility, character length, source reliability), takes the top-1 candidate, and performs exact string lookup in the registry. No fuzzy matching.
- **Baseline 2 (`B2`)**: **Ranked Candidate + Constrained Fuzzy (No Ambiguity Rejection)**  
  Ranks candidates, computes weighted Levenshtein similarity against all registry records, and accepts the top candidate if similarity $\ge 0.82$. Crucially, it does **not** check the ambiguity margin, blindly accepting the top hit even if multiple candidates are tied or separated by $< 0.07$.
- **Baseline 3 (`B3`)**: **Full Track A Pipeline (Weighted Fuzzy with Ambiguity Margin Rejection)**  
  Ranks candidates, evaluates similarity against registry using weighted Levenshtein (with optical OCR confusion discounting $0.25$), and enforces safety invariant: if $\Delta(\text{score}_1 - \text{score}_2) < 0.07$, the match is rejected as `AMBIGUOUS`.

---

## 2. Test Case Matrix (60 Synthetic Labeled Cases)

### Category 1: Clean Exact Matches (EX-001 – EX-010)
Standard campus vehicles with clean, high-confidence OCR reads matching active registry records.

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-001** | `CH01AB1234` (0.98, cam) | `CH01AB1234` | EXACT (REG-011) | EXACT (REG-011) | EXACT (REG-011) | EXACT (REG-011) | Direct match on single clean read. |
| **EX-002** | `PB65AK1122` (0.97, cam) | `PB65AK1122` | EXACT (REG-016) | EXACT (REG-016) | EXACT (REG-016) | EXACT (REG-016) | Direct match on Punjab faculty car. |
| **EX-003** | `HR70A1234` (0.95, cam) | `HR70A1234` | EXACT (REG-026) | EXACT (REG-026) | EXACT (REG-026) | EXACT (REG-026) | Direct match on Haryana two-wheeler. |
| **EX-004** | `DL01AA1234` (0.99, cam) | `DL01AA1234` | EXACT (REG-036) | EXACT (REG-036) | EXACT (REG-036) | EXACT (REG-036) | Direct match on Delhi vehicle. |
| **EX-005** | `HP12A1234` (0.96, cam) | `HP12A1234` | EXACT (REG-041) | EXACT (REG-041) | EXACT (REG-041) | EXACT (REG-041) | Direct match on Himachal Pradesh vehicle. |
| **EX-006** | `22BH2345CD` (0.94, cam) | `22BH2345CD` | EXACT (REG-046) | EXACT (REG-046) | EXACT (REG-046) | EXACT (REG-046) | Direct match on Bharat Series vehicle. |
| **EX-007** | `PB10AY9012` (0.95, cam) | `PB10AY9012` | EXACT (REG-023) | EXACT (REG-023) | EXACT (REG-023) | EXACT (REG-023) | Direct match on Ludhiana district car. |
| **EX-008** | `HR26DK3456` (0.96, cam) | `HR26DK3456` | EXACT (REG-029) | EXACT (REG-029) | EXACT (REG-029) | EXACT (REG-029) | Direct match on Gurugram visitor car. |
| **EX-009** | `DL03CC9012` (0.98, cam) | `DL03CC9012` | EXACT (REG-038) | EXACT (REG-038) | EXACT (REG-038) | EXACT (REG-038) | Direct match on Delhi staff two-wheeler. |
| **EX-010** | `23BH5678JK` (0.95, cam) | `23BH5678JK` | EXACT (REG-049) | EXACT (REG-049) | EXACT (REG-049) | EXACT (REG-049) | Direct match on 2023 BH series car. |

---

### Category 2: 1-Character Optical OCR Confusions (EX-011 – EX-025)
OCR errors caused by visual ambiguity (O/0, I/1, B/8, S/5, Z/2, G/6).

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-011** | `CHO1AB1234` (0.91, cam) | `CH01AB1234` | NO_MATCH | NO_MATCH | FUZZY (REG-011) | FUZZY (REG-011) | 'O' substituted for '0'. Exact fails; weighted Levenshtein gives 0.975 sim. |
| **EX-012** | `PB65AKI122` (0.89, cam) | `PB65AK1122` | NO_MATCH | NO_MATCH | FUZZY (REG-016) | FUZZY (REG-016) | 'I' substituted for '1'. Exact fails; optical penalty 0.25 resolves to REG-016. |
| **EX-013** | `PB028B1234` (0.88, cam) | `PB02BB1234` | NO_MATCH | NO_MATCH | FUZZY (REG-021) | FUZZY (REG-021) | '8' substituted for 'B'. Exact fails; fuzzy resolves. |
| **EX-014** | `HR70B567S` (0.87, cam) | `HR70B5678` | NO_MATCH | NO_MATCH | FUZZY (REG-027) | FUZZY (REG-027) | 'S' substituted for '8' (or '5'/'S' confusion in tail). Resolves cleanly. |
| **EX-015** | `DL01AA1Z34` (0.90, cam) | `DL01AA1234` | NO_MATCH | NO_MATCH | FUZZY (REG-036) | FUZZY (REG-036) | 'Z' substituted for '2'. Fuzzy resolves. |
| **EX-016** | `HP14C901Z` (0.86, cam) | `HP14C9012` | NO_MATCH | NO_MATCH | FUZZY (REG-043) | FUZZY (REG-043) | 'Z' substituted for '2' in number segment. Fuzzy resolves. |
| **EX-017** | `22BH34S6EF` (0.89, cam) | `22BH3456EF` | NO_MATCH | NO_MATCH | FUZZY (REG-047) | FUZZY (REG-047) | 'S' substituted for '5'. Optical confusion penalty resolves. |
| **EX-018** | `CH01AC567B` (0.88, cam) | `CH01AC5678` | NO_MATCH | NO_MATCH | FUZZY (REG-012) | FUZZY (REG-012) | 'B' substituted for '8'. Resolves to Chandigarh two-wheeler. |
| **EX-019** | `PB65AN77BB` (0.88, cam) | `PB65AN7788` | NO_MATCH | NO_MATCH | FUZZY (REG-019) | FUZZY (REG-019) | 'B' substituted for '8' in double digit. Resolves to REG-019. |
| **EX-020** | `HR26EM789O` (0.90, cam) | `HR26EM7890` | NO_MATCH | NO_MATCH | FUZZY (REG-030) | FUZZY (REG-030) | 'O' substituted for trailing '0'. Optical penalty resolves. |
| **EX-021** | `DL05EE789O` (0.92, cam) | `DL05EE7890` | NO_MATCH | NO_MATCH | FUZZY (REG-040) | FUZZY (REG-040) | 'O' substituted for trailing '0'. Resolves to vendor car. |
| **EX-022** | `PB11BZ34S6` (0.87, cam) | `PB11BZ3456` | NO_MATCH | NO_MATCH | FUZZY (REG-024) | FUZZY (REG-024) | 'S' substituted for '5'. Resolves to Patiala faculty car. |
| **EX-023** | `HR12V55G6` (0.86, cam) | `HR12V5566` | NO_MATCH | NO_MATCH | FUZZY (REG-033) | FUZZY (REG-033) | 'G' substituted for '6'. Resolves to Rohtak service car. |
| **EX-024** | `23BH4S67GH` (0.88, cam) | `23BH4567GH` | NO_MATCH | NO_MATCH | FUZZY (REG-048) | FUZZY (REG-048) | 'S' substituted for '5' in BH plate. Resolves to visitor. |
| **EX-025** | `CH01AF789O` (0.90, cam) | `CH01AF7890` | NO_MATCH | NO_MATCH | FUZZY (REG-015) | FUZZY (REG-015) | 'O' substituted for '0'. Resolves to faculty two-wheeler. |

---

### Category 3: Formatting & Separator Noise (EX-026 – EX-033)
Dirty characters, hyphens, spaces, mixed cases, punctuation.

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-026** | `CH-01-AD-9012` (0.95, cam) | `CH01AD9012` | EXACT (REG-013) | EXACT (REG-013) | EXACT (REG-013) | EXACT (REG-013) | Hyphens stripped cleanly by PlateNormalizer. |
| **EX-027** | `pb 65 ak 1122` (0.93, cam) | `PB65AK1122` | EXACT (REG-016) | EXACT (REG-016) | EXACT (REG-016) | EXACT (REG-016) | Spaces stripped and lower-to-upper conversion. |
| **EX-028** | `HR.26.DK.3456` (0.92, cam) | `HR26DK3456` | EXACT (REG-029) | EXACT (REG-029) | EXACT (REG-029) | EXACT (REG-029) | Periods stripped cleanly. |
| **EX-029** | `dl 04 dd 3456` (0.96, cam) | `DL04DD3456` | EXACT (REG-039) | EXACT (REG-039) | EXACT (REG-039) | EXACT (REG-039) | Lowercase and multiple spaces normalized. |
| **EX-030** | `HP-14-D-3456` (0.94, cam) | `HP14D3456` | EXACT (REG-044) | EXACT (REG-044) | EXACT (REG-044) | EXACT (REG-044) | Hyphens in Himachal visitor car. |
| **EX-031** | `22-BH-1001-AA` (0.95, cam) | `22BH1001AA` | EXACT (REG-009) | EXACT (REG-009) | EXACT (REG-009) | EXACT (REG-009) | Hyphens in Bharat Series format. |
| **EX-032** | `CH 01 AE 3456` (0.97, cam) | `CH01AE3456` | EXACT (REG-014) | EXACT (REG-014) | EXACT (REG-014) | EXACT (REG-014) | Space separation in Chandigarh plate. |
| **EX-033** | `PB-12-CA-7890` (0.93, cam) | `PB12CA7890` | EXACT (REG-025) | EXACT (REG-025) | EXACT (REG-025) | EXACT (REG-025) | Hyphenated Ropar service car. |

---

### Category 4: Insertions, Deletions & Truncations (EX-034 – EX-040)
Dropped digits, missing prefixes, spurious boundary characters.

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-034** | `CH01AB12345` (0.85, cam) | `CH01AB1234` | NO_MATCH | NO_MATCH | FUZZY (REG-011) | FUZZY (REG-011) | Extra trailing character '5' (insertion edit dist = 1, sim $\approx 0.909$). |
| **EX-035** | `B65AK1122` (0.84, cam) | `PB65AK1122` | NO_MATCH | NO_MATCH | FUZZY (REG-016) | FUZZY (REG-016) | Missing leading 'P' (deletion edit dist = 1, sim = 0.900). |
| **EX-036** | `HR26DK345` (0.83, cam) | `HR26DK3456` | NO_MATCH | NO_MATCH | FUZZY (REG-029) | FUZZY (REG-029) | Dropped trailing digit '6' (sim = 0.900). |
| **EX-037** | `DL02BB5678X` (0.82, cam) | `DL02BB5678` | NO_MATCH | NO_MATCH | FUZZY (REG-037) | FUZZY (REG-037) | Noise char 'X' at end (sim = 0.909). |
| **EX-038** | `HP12A123` (0.83, cam) | `HP12A1234` | NO_MATCH | NO_MATCH | FUZZY (REG-041) | FUZZY (REG-041) | Truncated number segment (sim = 0.889). |
| **EX-039** | `22BH2345C` (0.85, cam) | `22BH2345CD` | NO_MATCH | NO_MATCH | FUZZY (REG-046) | FUZZY (REG-046) | Dropped series letter in BH plate (sim = 0.900). |
| **EX-040** | `PB65AP990` (0.84, cam) | `PB65AP9900` | NO_MATCH | NO_MATCH | FUZZY (REG-020) | FUZZY (REG-020) | Dropped trailing zero (sim = 0.900). |

---

### Category 5: Multi-Reader Disagreement (EX-041 – EX-045)
Primary camera produces noisy/corrupt hypothesis, while secondary reader produces clean hypothesis.

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-041** | `CH01AB123X` (0.65, cam) \| `CH01AB1234` (0.98, ocr2) | `CH01AB1234` | NO_MATCH | EXACT (REG-011) | EXACT (REG-011) | EXACT (REG-011) | B0 takes 1st cand and fails. B1/B2/B3 rank cand 2 to top and resolve exact. |
| **EX-042** | `PB65AL3340` (0.70, cam) \| `PB65AL3344` (0.96, ocr2) | `PB65AL3344` | NO_MATCH | EXACT (REG-017) | EXACT (REG-017) | EXACT (REG-017) | Secondary reader has higher confidence and valid syntax. |
| **EX-043** | `HR70B567X` (0.62, fast) \| `HR70B5678` (0.95, ocr2) | `HR70B5678` | NO_MATCH | EXACT (REG-027) | EXACT (REG-027) | EXACT (REG-027) | B0 fails on corrupt first read; ranker promotes clean candidate. |
| **EX-044** | `DL01AA1230` (0.71, cam) \| `DL01AA1234` (0.97, ocr2) | `DL01AA1234` | NO_MATCH | EXACT (REG-036) | EXACT (REG-036) | EXACT (REG-036) | Secondary reader resolves exact match cleanly. |
| **EX-045** | `HP63E789X` (0.60, cam) \| `HP63E7890` (0.94, ocr2) | `HP63E7890` | NO_MATCH | EXACT (REG-045) | EXACT (REG-045) | EXACT (REG-045) | Secondary vision-language read promoted over corrupt edge read. |

---

### Category 6: Missing Confidence Scores (EX-046 – EX-050)
Upstream OCR pipeline emits candidates without confidence values.

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-046** | `CH01AD9012` (None, cam) | `CH01AD9012` | EXACT (REG-013) | EXACT (REG-013) | EXACT (REG-013) | EXACT (REG-013) | Default confidence 0.50 applied; syntax valid; matches exact. |
| **EX-047** | `PB65AM5566` (None, cam) | `PB65AM5566` | EXACT (REG-018) | EXACT (REG-018) | EXACT (REG-018) | EXACT (REG-018) | Missing confidence does not impede normalization or exact matching. |
| **EX-048** | `HR03R9012` (None, cam) | `HR03R9012` | EXACT (REG-028) | EXACT (REG-028) | EXACT (REG-028) | EXACT (REG-028) | Syntax plausibility score allows proper ranking. |
| **EX-049** | `DL03CC9012` (None, cam) | `DL03CC9012` | EXACT (REG-038) | EXACT (REG-038) | EXACT (REG-038) | EXACT (REG-038) | Auditable fallback scoring. |
| **EX-050** | `23BH6789LM` (None, cam) | `23BH6789LM` | EXACT (REG-050) | EXACT (REG-050) | EXACT (REG-050) | EXACT (REG-050) | BH plate without confidence successfully resolved. |

---

### Category 7: Negative Out-of-Registry Plates (EX-051 – EX-055)
Valid Indian plate format, but vehicle is not registered in the campus database.

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-051** | `UP16AB1234` (0.94, cam) | `UP16AB1234` | NO_MATCH | NO_MATCH | NO_MATCH | NO_MATCH | Noida vehicle not registered on campus; properly rejected. |
| **EX-052** | `RJ14CD5678` (0.92, cam) | `RJ14CD5678` | NO_MATCH | NO_MATCH | NO_MATCH | NO_MATCH | Jaipur vehicle not registered on campus; properly rejected. |
| **EX-053** | `MH12EF9012` (0.91, cam) | `MH12EF9012` | NO_MATCH | NO_MATCH | NO_MATCH | NO_MATCH | Pune vehicle not registered on campus; properly rejected. |
| **EX-054** | `KA03GH3456` (0.95, cam) | `KA03GH3456` | NO_MATCH | NO_MATCH | NO_MATCH | NO_MATCH | Bengaluru vehicle not registered on campus; properly rejected. |
| **EX-055** | `GJ01JK7890` (0.93, cam) | `GJ01JK7890` | NO_MATCH | NO_MATCH | NO_MATCH | NO_MATCH | Ahmedabad vehicle not registered on campus; properly rejected. |

---

### Category 8: Near-Duplicate Registry Ambiguity (EX-056 – EX-060)
Noisy reads falling within the ambiguity margin of two distinct authorized vehicles.

| ID | Raw Candidates (Conf, Source) | Ground Truth | Expected B0 | Expected B1 | Expected B2 | Expected B3 | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EX-056** | `CH01AB1000` (0.91, cam) | `CH01AB1000` | NO_MATCH | NO_MATCH | **FALSE MATCH** (REG-001) | **AMBIGUOUS** (Safe) | Equidistant to REG-001 (`...1001`) and REG-002 (`...1007`). B2 blindly accepts REG-001; B3 rejects as AMBIGUOUS ($\Delta = 0.00$). |
| **EX-057** | `PB65AB2225` (0.90, cam) | `PB65AB2225` | NO_MATCH | NO_MATCH | **FALSE MATCH** (REG-003) | **AMBIGUOUS** (Safe) | Equidistant to REG-003 (`...2222`) and REG-004 (`...2228`). B2 falsely accepts; B3 rejects. |
| **EX-058** | `HR26D00001` (0.92, cam) | `HR26D00001` | NO_MATCH | NO_MATCH | **FALSE MATCH** (REG-005) | **AMBIGUOUS** (Safe) | Optical confusion to both REG-005 (`...DQ...`) and REG-006 (`...DO...`). B2 guesses; B3 rejects. |
| **EX-059** | `DL08CA5556` (0.89, cam) | `DL08CA5556` | NO_MATCH | NO_MATCH | **FALSE MATCH** (REG-007) | **AMBIGUOUS** (Safe) | Close to both REG-007 (`...5555`) and REG-008 (`...5558`). B2 falsely accepts; B3 rejects. |
| **EX-060** | `22BH1001A` (0.90, cam) | `22BH1001A` | NO_MATCH | NO_MATCH | **FALSE MATCH** (REG-009) | **AMBIGUOUS** (Safe) | Prefix to both REG-009 (`...AA`) and REG-010 (`...AB`). B2 guesses REG-009; B3 rejects. |

---

## 3. Summary of Baseline Expected Behaviors

| Feature / Behavior | Baseline 0 (B0) | Baseline 1 (B1) | Baseline 2 (B2) | Baseline 3 (B3) |
| :--- | :--- | :--- | :--- | :--- |
| **Candidate Ingestion** | First candidate only | Multi-reader ranked | Multi-reader ranked | Multi-reader ranked |
| **Normalization** | Clean alphanumeric | Clean alphanumeric | Clean alphanumeric | Clean + Confusion variants |
| **Fuzzy Matching** | None | None | Weighted Levenshtein | Weighted Levenshtein |
| **Ambiguity Rejection** | N/A | N/A | **None (Blind Top)** | **Strict Margin ($\ge 0.07$)** |
| **Optical Confusions Resolved** | 0 / 15 (0.0%) | 0 / 15 (0.0%) | 15 / 15 (100.0%) | 15 / 15 (100.0%) |
| **Multi-Reader Resolved** | 0 / 5 (0.0%) | 5 / 5 (100.0%) | 5 / 5 (100.0%) | 5 / 5 (100.0%) |
| **Near-Duplicate Ambiguity** | 0 / 5 (Rejection) | 0 / 5 (Rejection) | **5 / 5 False Matches!** | **5 / 5 Safe AMBIGUOUS** |
| **False-Match Rate (Total)** | 0.00% | 0.00% | **8.33% (5 false)** | **0.00%** |
