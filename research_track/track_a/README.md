# Track A: Indian ANPR Research & Evaluation Prototype

Offline evaluation and research harness for Indian vehicle number plate recognition, multi-candidate ranking, and registry-constrained fuzzy matching for the PEC Chandigarh Campus Vehicle Security System.

---

## 1. Directory Structure

```text
research_track/track_a/
├── config.yaml                     # Pipeline parameters, ranking weights, baselines, and split configs
├── fixtures/
│   ├── synthetic_registry.csv      # 50 synthetic authorized campus vehicle records (PB, CH, HR, DL, HP, BH)
│   └── labeled_examples.csv        # 60 labeled evaluation cases across 8 edge case categories
├── reports/
│   └── EVALUATION_PLAN.md          # Formal evaluation methodology, metric formulas, and error taxonomy
├── results/
│   └── .gitkeep                    # Target directory for deferred offline evaluation outputs
├── src/
│   ├── __init__.py                 # Module exports
│   ├── candidate_ranking.py        # Multi-reader OCR hypothesis ranking & transparent scoring
│   ├── metrics.py                  # CER, Exact Accuracy, False-Match Rate (dual denominators), and error breakdowns
│   ├── normalization.py            # Non-destructive Indian plate cleaner, regex validator, confusion generator
│   ├── pipeline.py                 # End-to-end ANPRPipeline implementing Baselines 0 through 3
│   ├── registry_matcher.py         # Weighted Levenshtein matcher with strict ambiguity rejection
│   └── resolver_adapter.py         # Bidirectional adapter to Phase 5A IdentityResolver schema
├── tests/
│   └── test_cases.md               # Detailed 60-case evaluation matrix and expected baseline outcomes
├── IMPLEMENTATION_REPORT.md        # Comprehensive implementation and architectural audit report
├── SPECIFICATION.md                # Formal system specification, data models, and contracts
└── README.md                       # This documentation file
```

---

## 2. Key Architecture Concepts

### 2.1 Non-Destructive Normalization
Unlike naive normalizers that mutate characters in-place (e.g. blindly replacing all 'O's with '0's), Track A's `PlateNormalizer`:
- Permanently preserves the raw string in immutable fields.
- Strips delimiters (hyphens, dots, spaces) and enforces uppercase formatting.
- Detects structural segments according to the Motor Vehicles Act (State, District, Series, Number, Bharat Series).
- Generates alternative hypothesis variants with explicit penalty costs rather than silently rewriting input.

### 2.2 Transparent Multi-Reader Ranking
Upstream perception pipelines often run multiple OCR models (e.g., lightweight edge detector and vision-language model). `OCRCandidateRanker`:
- Explicitly handles missing confidence values by imputing a neutral $0.50$ without claiming false certainty.
- Scores candidates using a weighted formula combining confidence, regex format plausibility, character length, and reader source reliability.
- Keeps OCR confidence, ranking scores, and registry similarity metrics strictly separate.

### 2.3 Registry-Constrained Fuzzy Matching with Ambiguity Margins
`RegistryMatcher` searches candidate plates against an offline registry using a weighted Levenshtein distance:
- Known optical character confusions ($O \leftrightarrow 0, I \leftrightarrow 1, B \leftrightarrow 8, S \leftrightarrow 5, Z \leftrightarrow 2, G \leftrightarrow 6$) receive a discounted edit penalty ($0.25$ vs $1.00$).
- **The Ambiguity Invariant**: If two registry candidates both pass the similarity threshold ($0.82$) but are separated by less than the ambiguity margin ($\Delta < 0.07$), the system rejects the match as `AMBIGUOUS`.
- Enforces the core security invariant: **UNKNOWN over WRONG RECORD** and **AMBIGUOUS over FALSE CERTAINTY**.

---

## 3. How to Interpret Evaluation Metrics

- **Exact-Plate Accuracy**: Fraction of cases where the top candidate text matches the ground-truth plate string.
- **Character Error Rate (CER)**: Normalized Levenshtein distance per plate string ($\frac{\text{Distance}}{\text{Length}}$). Target: $< 0.05$.
- **False-Match Rate (FMR)**: Evaluated with **both** denominators:
  - $\text{FMR}_{\text{matched}}$: False matches divided by total matched predictions. Indicates how often an accepted match is wrong.
  - $\text{FMR}_{\text{total}}$: False matches divided by total test samples. Indicates campus-wide risk.
- **Coverage**: Fraction of samples that resolve to an authorized vehicle record.
- **Ambiguity Rate**: Fraction of samples safely rejected due to near-tie candidates.

---

## 4. Deferred Execution Instructions

Per the project's strict isolation invariants, **zero code or tests have been executed during development**. When ready to execute offline benchmarks on a dedicated CPU environment, run:

```bash
# 1. Activate isolated ML virtual environment
source ~/ml-assets/campus/.venv-ml/bin/activate

# 2. Execute offline evaluation harness across all baselines
python -c "
import os, json
from research_track.track_a.src.pipeline import ANPRPipeline

pipe = ANPRPipeline.from_config('research_track/track_a/config.yaml')
examples = pipe.load_examples_from_csv('research_track/track_a/fixtures/labeled_examples.csv')

for b_id in ['baseline_0', 'baseline_1', 'baseline_2', 'baseline_3']:
    summary = pipe.evaluate_dataset(examples, baseline_id=b_id)
    print(summary.format_markdown_table())
    with open(f'research_track/track_a/results/{b_id}_summary.json', 'w') as f:
        json.dump(summary.to_dict(), f, indent=2)
"
```

---

## 5. Limitations & Synthetic Data Disclosure

1. **Synthetic Data Disclosure**: All 50 registry records and 60 labeled examples are synthetic, generated specifically to model Indian RTO conventions and challenging edge cases (near-duplicates, OCR noise). No actual personal data or live campus permit records are included.
2. **Text-Level Scope**: Track A evaluates text hypothesis normalization, ranking, and registry matching. It does not perform image detection, cropping, or neural OCR inference.
3. **No Gate Barrier Control**: In accordance with system architecture invariants, Track A output is an observation context. It never triggers gate opening or physical barrier actuators.
