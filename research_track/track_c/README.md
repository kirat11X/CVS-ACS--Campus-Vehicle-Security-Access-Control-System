# Track C: Item Classification Interface & Deterministic Screening Policy Engine

**PEC Chandigarh Campus Vehicle Security & Access-Control System**  
**Subsystem:** Automated Quick-Commerce Delivery Screening Pipeline  
**Directory:** `research_track/track_c/`  
**Phase:** Research & Evaluation Prototype (Additive-Only, Isolated)

---

## 1. Overview & Architectural Role

Track C provides a standalone, model-independent item classification interface coupled with a pure deterministic policy screening engine.

In the automated campus delivery workflow:
```
WhatsApp Invoice Image ➔ n8n ➔ FastAPI ➔ Track B (Invoice OCR/Parsing)
                                              ↓
                             Track C: Classification Interface
                                              ↓
                             Track C: Deterministic Policy Engine
                                              ↓
                             Gate Barrier (ALLOW) / Guard Review (REVIEW) / Security Alarm (ALERT)
```

### Core Design Philosophy: Decoupled Perception vs. Policy
- **The Classifier** observes raw invoice text and proposes a category (`category`, `confidence`). It has **zero authority** over access decisions.
- **The Policy Engine** evaluates categorical hypotheses against an institutional rule table to produce an authoritative security outcome (`ALLOW`, `REVIEW`, `ALERT`).
- Model confidence or predictions **never** directly trigger gate barriers.

---

## 2. Directory Layout

```
research_track/track_c/
├── config.yaml                          # Global thresholds, versioning, and policy config
├── SPECIFICATION.md                     # Formal data contracts, schemas, and 13 invariants
├── IMPLEMENTATION_REPORT.md             # Engineering implementation report (Deliverable 15)
├── README.md                            # System architecture, quickstart, and deferred usage
├── schemas/                             # JSON Schemas (Draft 2020-12)
│   ├── classification_input.schema.json
│   ├── classification_output.schema.json
│   ├── policy_rule.schema.json
│   └── screening_result.schema.json
├── src/                                 # Pure Python core domain logic (zero external ML deps)
│   ├── __init__.py                      # Public package exports
│   ├── types.py                         # Dataclasses & enums (ScreeningOutcome, CategoryCode)
│   ├── category_normalization.py        # 8-category taxonomy normalizer & synonym mapper
│   ├── reason_codes.py                  # Standardized immutable machine-readable reason codes
│   ├── classifier_interface.py          # Abstract ItemClassifier & LexicalMappingClassifier
│   ├── policy_engine.py                 # DeterministicPolicyEngine with conflict safety
│   ├── audit_records.py                 # Immutable audit ledger & human review event tracking
│   └── evaluation.py                    # Independent perception & policy evaluation metrics
├── fixtures/                            # Deterministic evaluation test sets
│   ├── item_taxonomy_seed.csv           # 321 curated items across 8 categories (synthetic)
│   ├── policy_rules.json                # 21 versioned rules (defaults, overrides, conflicts)
│   ├── synthetic_screening_cases.json   # 115 test cases covering all edge scenarios
│   └── synthetic_ground_truth.json      # 115 expected ground-truth labels and outcomes
├── tests/
│   └── test_cases.md                    # Evaluation matrix for all 115 test cases
├── reports/
│   └── EVALUATION_PLAN.md               # Future model comparison framework & property tests
└── results/
    └── .gitkeep                         # Placeholder for future empirical benchmark outputs
```

---

## 3. Key Invariants

1. **Separation of Concerns**: Classifiers propose; policy engines decide.
2. **Confidence Safety**: Low confidence ($< 0.70$) or missing confidence (`None`) safely downgrades `ALLOW` to `REVIEW`. `ALERT` is never downgraded.
3. **Order Invariance**: Rules are evaluated strictly by priority (lower integer = higher priority). Shuffling rules never alters outcomes.
4. **Conflict Safety**: Multiple rules matching at equal priority with conflicting actions emit `POLICY_RULE_CONFLICT` and route safely to `REVIEW`.
5. **No Silent `NORMAL`**: Unrecognized tokens resolve strictly to `UNKNOWN`, triggering mandatory guard review.
6. **Strict Units**: Quantity rules require unit matches (`PACK`, `BOTTLE`, `PCS`). No cross-unit assumptions.
7. **Dual-Threshold Hazardous Chemical Policy**: Quantities $\ge 3$ trigger `REVIEW`; small quantities $< 3$ allow domestic entry with audit trails.

---

## 4. Usage Example (Python stdlib)

```python
import json
from research_track.track_c.src.types import ClassificationInput, PolicyRule
from research_track.track_c.src.classifier_interface import LexicalMappingClassifier
from research_track.track_c.src.policy_engine import DeterministicPolicyEngine

# 1. Initialize lexical classifier baseline from seed taxonomy
classifier = LexicalMappingClassifier.from_csv(
    csv_path="research_track/track_c/fixtures/item_taxonomy_seed.csv",
    default_confidence=None  # Preserves missing confidence as None
)

# 2. Initialize deterministic policy engine with versioned rules
with open("research_track/track_c/fixtures/policy_rules.json", "r") as f:
    rules = [PolicyRule(**r) for r in json.load(f)]
engine = DeterministicPolicyEngine(rules=rules, default_policy_version="v1.0")

# 3. Classify an incoming delivery item
input_item = ClassificationInput(
    line_item_id="li-001",
    raw_item_description="Gold Flake Kings (10s)",
    quantity=1.0,
    unit="PACK",
    platform="BLINKIT"
)
classification = classifier.classify(input_item)

# 4. Evaluate screening outcome deterministically
result = engine.evaluate(
    classification=classification,
    quantity=input_item.quantity,
    unit=input_item.unit,
    platform=input_item.platform
)

print("Outcome:", result.outcome.value)           # Output: ALERT
print("Reason Codes:", result.reason_codes)       # Output: ['CATEGORY_RULE_ALERT']
print("Applied Rule:", result.matched_rule_ids)   # Output: ['RULE-TOBACCO-DEFAULT']
```

---

## 5. Synthetic Data & Compliance Notice

All taxonomy items (`item_taxonomy_seed.csv`), test cases (`synthetic_screening_cases.json`), and ground-truth records (`synthetic_ground_truth.json`) are **100% synthetically generated**:
- No real student, faculty, or resident personal delivery receipts were used.
- Contains zero Personally Identifiable Information (PII).
- Fully compliant with the Indian Digital Personal Data Protection Act (DPDPA 2023).

---

## 6. Deferred Execution Notice

In compliance with repository safety constraints:
- Zero background processes, live dev servers, or model training sessions have been executed.
- Model weights for zero-shot LLM evaluation (e.g. Qwen3-1.7B) are deferred until explicitly staged under `~/ml-assets/campus/models/`.
- All Python code and JSON schemas have been statically verified for syntax and contract validity.
