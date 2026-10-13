# Track A: Offline Evaluation Protocol & Experimental Plan

This document establishes the experimental protocol, mathematical metric formulations, error taxonomies, and baseline comparison methodology for the Indian ANPR research track at PEC Chandigarh (`research_track/track_a/`).

---

## 1. Executive Summary & Experimental Objectives

The primary objective of Track A is to rigorously evaluate candidate license plate hypotheses against an authorized vehicle registry under controlled, offline conditions. This prototype establishes:

1. **Ablation of ANPR Pipeline Stages**: Isolating the individual contributions of non-destructive normalization, multi-OCR candidate ranking, weighted Levenshtein matching, and ambiguity margin enforcement.
2. **Safety-First Operational Invariant**: Demonstrating that rejecting ambiguous candidates as `AMBIGUOUS` prevents critical False-Match errors (vehicle misattribution) without degrading legitimate recall.
3. **Decoupling from Production**: Operating entirely within `research_track/track_a/` using synthetic fixtures (`fixtures/synthetic_registry.csv` and `fixtures/labeled_examples.csv`) without live database connections or GPU execution.

---

## 2. Experimental Protocol

### 2.1 Dataset Splits
The evaluation dataset is partitioned deterministically using a seeded pseudo-random hash (`seed=42`) into:
- **Validation Split (30%, 18 cases)**: Used for hyperparameter calibration (tuning the minimum similarity threshold $\theta = 0.82$, ambiguity margin $\Delta = 0.07$, and optical confusion penalty $w_{\text{ocr}} = 0.25$).
- **Test Split (70%, 42 cases)**: Held out for final offline reporting across all four baselines.

Both splits preserve the categorical distribution across the eight test case archetypes:
1. Clean exact matches
2. 1-character optical OCR confusions
3. Formatting and separator noise
4. Insertions, deletions, and truncations
5. Multi-reader disagreements
6. Missing confidence scores
7. Negative out-of-registry plates
8. Near-duplicate registry ambiguity pairs

### 2.2 Offline Evaluation Workflow
The evaluation harness executes sequentially without network I/O:
1. Load synthetic vehicle registry (50 records).
2. Load labeled test examples (60 cases).
3. For each baseline ($B_0, B_1, B_2, B_3$):
   - Ingest candidates.
   - Execute baseline resolution logic.
   - Record decision status, matched record ID, predicted plate string, and execution latency.
4. Calculate aggregate metrics, confusion rates, dual-denominator False-Match Rates, and error taxonomy breakdowns via `MetricCalculator`.
5. Output structured JSON and Markdown evaluation reports to `results/`.

---

## 3. Mathematical Metric Definitions

Let $N$ denote the total number of evaluation samples ($N = 60$).  
Let $S_i \in \{\text{EXACT\_MATCH}, \text{FUZZY\_CONFIDENT}, \text{AMBIGUOUS}, \text{NO\_MATCH}, \text{INVALID\_INPUT}\}$ denote the pipeline status for sample $i$.  
Let $P_i$ denote the predicted cleaned plate string, and $G_i$ denote the ground-truth cleaned plate string.  
Let $R_i \in \text{Registry}$ denote the resolved registry record ID (or $\emptyset$ if unresolved), and $R_i^*$ denote the expected registry record ID (or $\emptyset$ if negative or ambiguous).

### 3.1 Exact-Plate Accuracy (EPA)
Measures the fidelity of OCR hypothesis selection prior to or in conjunction with registry matching:
$$\text{EPA} = \frac{1}{N} \sum_{i=1}^N \mathbf{1}[P_i = G_i]$$

### 3.2 Character Error Rate (CER)
Measures normalized string edit distance per sample using standard unit-cost Levenshtein distance:
$$\text{CER}_i = \frac{\text{Levenshtein}(P_i, G_i)}{\max(|G_i|, 1)}$$
$$\text{Mean CER} = \frac{1}{N} \sum_{i=1}^N \text{CER}_i$$

### 3.3 Registry Match Accuracy (RMA)
Measures correct categorical resolution across all cases (matching the right vehicle when present, and safely rejecting when absent or ambiguous):
$$\text{RMA} = \frac{1}{N} \sum_{i=1}^N \mathbf{1}[R_i = R_i^* \land \text{StatusCorrect}_i]$$
where $\text{StatusCorrect}_i$ is true if the categorical decision matches the expected outcome.

### 3.4 False-Match Rate (FMR) — Dual Denominator Formulation
A False Match occurs when the pipeline resolves an observation to an incorrect vehicle record ($R_i \neq \emptyset \land R_i \neq R_i^*$). This represents a critical campus security failure (e.g. logging an unauthorized vehicle under an authorized faculty member's permit).

To prevent deceptive reporting, Track A defines both standard denominators:

#### Denominator A: Matched Population ($\text{FMR}_{\text{matched}}$)
Measures the error rate strictly among samples where the pipeline attempted a positive match:
$$N_{\text{matched}} = \sum_{i=1}^N \mathbf{1}[S_i \in \{\text{EXACT\_MATCH}, \text{FUZZY\_CONFIDENT}\}]$$
$$\text{FMR}_{\text{matched}} = \frac{\sum_{i=1}^N \mathbf{1}[R_i \neq \emptyset \land R_i \neq R_i^*]}{N_{\text{matched}}} \quad (\text{if } N_{\text{matched}} > 0, \text{ else } 0)$$

#### Denominator B: Total Population ($\text{FMR}_{\text{total}}$)
Measures the absolute risk across the entire operational traffic volume:
$$\text{FMR}_{\text{total}} = \frac{\sum_{i=1}^N \mathbf{1}[R_i \neq \emptyset \land R_i \neq R_i^*]}{N}$$

### 3.5 No-Match Rate (NMR) & Ambiguity Rate (AR)
Measures safe rejections:
$$\text{NMR} = \frac{1}{N} \sum_{i=1}^N \mathbf{1}[S_i = \text{NO\_MATCH}]$$
$$\text{AR} = \frac{1}{N} \sum_{i=1}^N \mathbf{1}[S_i = \text{AMBIGUOUS}]$$

### 3.6 Coverage
Proportion of input observations that successfully resolve to an authorized vehicle record:
$$\text{Coverage} = \frac{N_{\text{matched}}}{N} = \frac{1}{N} \sum_{i=1}^N \mathbf{1}[S_i \in \{\text{EXACT\_MATCH}, \text{FUZZY\_CONFIDENT}\}]$$

### 3.7 Latency Metrics
Calculated across processing times $t_i$ (in milliseconds):
- **Mean Latency**: $\bar{t} = \frac{1}{N} \sum t_i$
- **P50 (Median)**: 50th percentile of sorted $t$
- **P90**: 90th percentile of sorted $t$
- **P95**: 95th percentile of sorted $t$

---

## 4. Expected Baseline Progression

The four baselines demonstrate clear, monotonic improvements along key operational axes:

```
[B0: Naive Exact]  --->  [B1: Multi-OCR Exact]  --->  [B2: Blind Fuzzy]  --->  [B3: Full Track A]
  Lowest Recall           Solves multi-reader          High Recall but          High Recall AND
  0% confusions           disagreements                High False-Match         0% False Matches
```

| Metric / Property | Baseline 0 | Baseline 1 | Baseline 2 | Baseline 3 | Progression Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Exact-Plate Acc.** | Moderate (~55%) | High (~65%) | High (~65%) | High (~65%) | Multi-OCR ranker recovers corrupted primary reads. |
| **Mean CER** | Moderate (~0.08) | Lower (~0.05) | Lower (~0.05) | Lower (~0.05) | Secondary OCR selection reduces character errors. |
| **Coverage** | 30.0% (18/60) | 38.3% (23/60) | **75.0% (45/60)** | **66.7% (40/60)** | B2 artificially inflates coverage by guessing. |
| **False-Match Rate (Tot)**| 0.0% | 0.0% | **8.33% (5/60)** | **0.0% (0/60)** | **B3 eliminates all 5 false matches made by B2.** |
| **False-Match Rate (Mat)**| 0.0% | 0.0% | **11.11% (5/45)**| **0.0% (0/40)** | 1 out of 9 matches in B2 is wrong vehicle! |
| **Ambiguity Rate** | 0.0% | 0.0% | 0.0% | **8.33% (5/60)** | B3 correctly routes near-ties to AMBIGUOUS. |
| **Registry Accuracy** | 38.3% (23/60) | 46.7% (28/60) | 83.3% (50/60) | **91.7% (55/60)** | B3 achieves highest safe operational accuracy. |

---

## 5. Granular Error Taxonomy

Track A categorizes all pipeline errors into an auditable hierarchy:

1. **Character Substitution Errors**:
   - *Optical Confusions*: Confusions between visually identical glyphs ($O \leftrightarrow 0, I \leftrightarrow 1, B \leftrightarrow 8, S \leftrightarrow 5, Z \leftrightarrow 2, G \leftrightarrow 6$). Penalized at $0.25$.
   - *Non-Optical Substitutions*: Random OCR corruptions ($K \leftrightarrow R, X \leftrightarrow 4$). Penalized at $1.00$.
2. **Structural / Alignment Errors**:
   - *Insertion Errors*: Spurious characters from plate border noise or mounting screws.
   - *Deletion Errors*: Dropped digits or truncated series letters.
3. **Indian Syntax Violations**:
   - *State Code Errors*: Misread of the 2-letter RTO state prefix (e.g. `PH` instead of `PB`).
   - *District / Series Errors*: Errors in the 2-digit district or 1-2 letter series code.
   - *Sequence Number Errors*: Misreading of the 4-digit unique registration number.
4. **Resolution Policy Outcomes**:
   - *Incorrect Record Accepted (`FALSE_MATCH`)*: Top candidate matched to wrong vehicle record. (Severity: CRITICAL).
   - *Ambiguous Rejection (`AMBIGUOUS`)*: Two or more records within margin $\Delta < 0.07$. (Severity: BENIGN / SAFE).
   - *Unmatched Out-of-Registry (`NO_MATCH`)*: Correctly determined vehicle is not registered. (Severity: EXPECTED).

---

## 6. Separation of Concerns: Candidate Matching vs Future Image ANPR

It is vital to distinguish what Track A evaluates today versus what future perception tracks will evaluate:

| Dimension | Track A Prototype (Current Scope) | Future End-to-End Image ANPR |
| :--- | :--- | :--- |
| **Input Data** | Text hypotheses, confidences, sources | Raw RGB images / video streams |
| **Perception Stack** | Mocked / synthetic OCR outputs | YOLOv8/v11-plate + PaddleOCR/FastPlateOCR |
| **Evaluated Stages** | Normalization, ranking, registry matching | Detection, warping, recognition, matching |
| **Execution Mode** | Fast offline CPU benchmark ($< 1$ ms/sample) | GPU neural network inference ($15-50$ ms/frame) |
| **Hardware Required**| Lightweight CPU only, no GPU | Dedicated CUDA GPU (RTX 4060/4090 or cloud) |
| **Primary Risk** | Ambiguous record association, over-matching | Occlusion, low-light, blur, skewed angles |

This decoupling ensures that the matching and security invariants are mathematically verified and battle-tested **before** heavy GPU models are wired into the perception layer.
