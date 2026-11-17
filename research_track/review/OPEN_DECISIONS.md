# Formally Resolved Architecture & Research Decisions

Date of Formal Ratification: 2026-11-16  
Repository: `kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System`  
Governing Standard: `OBSERVE -> ASSOCIATE -> CONTEXTUALIZE -> RECORD -> ALERT`  
Mandate: Human security guards retain ultimate, non-delegable gate access control; AI/ML systems operate strictly as assistive perception and policy advisors.

---

## Decision 1: Track A Split Protocol & Zero Data Leakage Prevention Protocol

* **Status:** **RESOLVED**
* **Previous State:** Evaluation plan declared a 30% val / 70% test partition, but earlier synthetic runners evaluated across unpartitioned fixtures without enforcing visual near-duplicate clustering across consecutive video frames.
* **Formal Decision & Specification:**
  1. **Split Protocol Definition:**
     - The held-out evaluation corpus is strictly partitioned into **30% Validation** and **70% Test** by group-shuffled assignment (`seed=42`).
     - **Test Partition Quarantining Invariant:** Under no circumstances may any hyperparameter calibration, threshold tuning (similarity threshold $\theta = 0.82$, ambiguity margin $\Delta = 0.07$), or optical character confusion weighting ($w_{\text{ocr}} = 0.25$) touch or inspect the test partition. All tuning occurs strictly on the validation partition.
  2. **Domain-Hard Held-Out Quarantining:**
     - Challenging video sources, specifically `deepakat002` 1080p surveillance video frames (where baseline recall was $0.12$ and YOLO11n reached $0.70$, highlighting small-plate crop blur and steep perspective angles), are pinned into the held-out test split to test generalization under realistic surveillance conditions.
  3. **Zero Plate-Text & Visual Leakage Prevention Protocol:**
     - **Canonical Text Normalization:** Every plate string is normalized via `normalize_plate()` (stripping whitespace, hyphens, dots, and applying state/BH-series syntax rules).
     - **Exact Plate String Grouping:** Every image instance bearing identical normalized plate text is assigned to the same group ID.
     - **Perceptual dHash Near-Duplicate Merging:** Video sequences contain consecutive frames of the same vehicle/plate with slight pixel translations or annotation typos (e.g., `GJO1HW3542` vs `GJ01HW3542` or `GJ27TG0469` vs `GJ27TG0466`). Using 64-bit difference hashing (`dHash`) with an EXIF-aware orientation pipeline, any plate images within Hamming distance $\le 2$ bits (or $\le 6$ bits for video crops) are merged into equivalence classes via Union-Find.
     - **Transitive Cluster Closure:** If image $A$ is linked to plate text 1 and image $B$ (near-duplicate of $A$) is linked to plate text 2, both plate texts are merged into an atomic, indivisible cluster.
     - **Formal Partition Invariant:**
       $$\text{Train}_{\text{plates}} \cap \text{Test}_{\text{plates}} = \emptyset, \quad \text{Train}_{\text{hashes}} \cap \text{Test}_{\text{hashes}} = \emptyset$$

---

## Decision 2: Track B Line-Item Alignment (Deterministic Optimal Bipartite Matching)

* **Status:** **RESOLVED**
* **Previous State:** Finding `B-S1-003` flagged that `align_line_items()` originally used greedy matching, which creates race conditions and order dependencies where an early suboptimal match deprives another item of its true optimal counterpart.
* **Formal Decision & Specification:**
  1. **Optimal Assignment Formulation:**
     Line-item alignment between predicted items $P = \{p_1, \dots, p_m\}$ and ground-truth items $G = \{g_1, \dots, g_n\}$ is formally specified as a **Maximum Weight Bipartite Matching** problem:
     $$\max_{X} \sum_{i=1}^m \sum_{j=1}^n w_{i,j} x_{i,j}$$
     $$\text{subject to: } \sum_{j=1}^n x_{i,j} \le 1 \; \forall i, \quad \sum_{i=1}^m x_{i,j} \le 1 \; \forall j, \quad x_{i,j} \in \{0, 1\}$$
  2. **Edge Weight Scoring Metric ($w_{i,j}$):**
     $$w_{i,j} = \alpha \cdot \text{TokenSim}(p_i.\text{desc}, g_j.\text{desc}) + \beta \cdot \text{PriceMatch}(p_i.\text{total}, g_j.\text{total})$$
     where $\alpha = 0.70$, $\beta = 0.30$.
     $$\text{PriceMatch}(p_i, g_j) = \begin{cases} 
     1.0 & \text{if } |p_i.\text{total} - g_j.\text{total}| = 0 \\
     0.5 & \text{if } |p_i.\text{total} - g_j.\text{total}| \le 0.02 \\
     0.0 & \text{otherwise}
     \end{cases}$$
     Edges with $w_{i,j} < \tau_{\text{sim}} = 0.50$ are pruned from the bipartite graph.
  3. **Strict 4-Level Deterministic Tie-Breaking Hierarchy:**
     To eliminate greedy order sensitivity and non-determinism across duplicate descriptions or identical prices:
     - **Level 1 (Maximum Cardinality):** Maximize total matched pairs $\sum x_{i,j}$.
     - **Level 2 (Maximum Score):** Maximize cumulative assignment weight $\sum w_{i,j} x_{i,j}$ using exact `Decimal` arithmetic.
     - **Level 3 (Lexicographical Description):** Sort candidates by predicted description string $p_i.\text{desc}$ ascending, then ground-truth description $g_j.\text{desc}$ ascending.
     - **Level 4 (Document Appearance Index):** Sort by original 0-based document sequence indices: tuple $(p_i.\text{index}, g_j.\text{index})$ ascending.
     - Solved deterministically via the Hungarian (Kuhn-Munkres) / Jonker-Volgenant algorithm or exact bitmask DP for $n \le 20$.

---

## Decision 3: Track B Locale Policy (Indian Financial System, Currency Prefixes & Fees)

* **Status:** **RESOLVED**
* **Previous State:** Finding `B-S2-004` identified ambiguity in parsing comma-separated amounts (e.g., `1,234`), missing formal support for the Indian numbering system (`1,23,456.78`), and unverified handling of delivery/packaging fees and discounts.
* **Formal Decision & Specification:**
  1. **Dual Numbering System Parsing:**
     - **International Grouping:** Matches `\d{1,3}(,\d{3})*(\.\d{2})?` (e.g., `123,456.78`).
     - **Indian Lakh/Crore Grouping:** Matches `\d{1,2}(,\d{2})*,\d{3}(\.\d{2})?` (e.g., `1,23,456.78` or `12,34,567.89`).
  2. **Comma vs. Decimal Separator Policy:**
     - The default campus locale is strictly `en-IN` (Indian English), where the dot `.` is the authoritative decimal separator.
     - Commas `,` are strictly grouping/thousands separators.
     - **Resolution of Ambiguous Strings (e.g., `1,234` vs `50,00`):**
       - If string has a comma followed by 3 digits (e.g., `1,234` without a period), it is parsed as integer `Decimal("1234.00")`.
       - If string has a comma followed by 2 digits (e.g., `50,00`), in the absence of an explicit European document locale header (`de`, `fr`, `es`), it is **NOT** guessed. It triggers validation finding `VAL_AMBIGUOUS_NUMERIC_LOCALE` and is escalated to guard review to prevent misinterpreting ₹50.00 as ₹5,000.
  3. **Currency Prefix & Normalization:**
     - Supports prefixes and suffixes: `₹`, `Rs.`, `Rs`, `INR`, `/-`, `Re.`.
     - Canonicalized to ISO 4217 code `INR`.
  4. **Financial Reconciliation Invariant:**
     - Mathematical balance enforced by `InvoiceReconciler` using pure `Decimal`:
       $$\text{Reconciled Total} = \sum_{k=1}^K \text{LineTotal}_k - \text{Discount}_{\text{order}} + \text{Tax}_{\text{total}} + \text{DeliveryFee} + \text{PackagingFee} + \text{HandlingFee} + \text{PlatformFee}$$
     - Line items with stated discounts enforce: $\text{unit\_price} \times \text{quantity} - \text{item\_discount} = \text{line\_total} \pm 0.02$.
     - Delivery, packaging, and handling fees are classified as non-inventory logistics surcharges and reconciled against `invoice_subtotal + charges = invoice_grand_total`.

---

## Decision 4: Track C Uncertainty Policy & Guard Escalation Invariant

* **Status:** **RESOLVED**
* **Previous State:** Need formalization that low-confidence or uncertain classifier predictions never silently allow prohibited or hazardous items through campus perimeter gates.
* **Formal Decision & Specification:**
  1. **Decoupled Perception vs. Authoritative Policy:**
     The ML classifier (Qwen3-1.7B QLoRA) is strictly an observational feature extractor emitting predicted category $\hat{c}$, confidence $s \in [0.0, 1.0]$, and boolean `is_uncertain`. The deterministic `PolicyEngine` evaluates safety rules and makes all policy decisions.
  2. **Mandatory Uncertainty Escalation Invariant:**
     For any item where deterministic rule evaluation would otherwise result in `ALLOW`:
     - If `is_uncertain == True`: The outcome **MUST** escalate immediately to `REVIEW` (`outcome = REVIEW`, reason code: `MANUAL_REVIEW_REQUIRED`, trace method: `_downgraded_due_to_uncertain_classification`).
     - If `confidence < 0.70` (or `confidence is None` / missing): The outcome **MUST** escalate immediately to `REVIEW` (`outcome = REVIEW`, reason code: `LOW_CLASSIFIER_CONFIDENCE` or `MISSING_CLASSIFIER_CONFIDENCE`).
  3. **Non-Degradation of Security Alerts:**
     - If deterministic rule evaluation yields `ALERT` (e.g., contraband, weapons, unauthorized bulk hazardous materials), **`ALERT` never degrades to `REVIEW` or `ALLOW`**, regardless of confidence score or uncertainty flag.
     - An uncertain `ALERT` candidate remains an active `ALERT` with an added flag for heightened manual inspection.
  4. **Guard Gate Control Retention:**
     - Automated systems never execute autonomous denial of entry.
     - `ALLOW`: Routine access with automated gate clearance logging.
     - `REVIEW`: Vehicle held at gate; guard prompted on dashboard to visually inspect invoice/package.
     - `ALERT`: Gate remains closed; visual and audible alert sounded on guard console; security supervisor notified.

---

## Decision 5: Cross-Track Adapter Ownership (`adapter_c.py`)

* **Status:** **RESOLVED**
* **Previous State:** Finding `X-S1-001` noted the absence of an executable, lossless bridge converting Track B invoice structures into Track C screening inputs without creating circular dependencies.
* **Formal Decision & Specification:**
  1. **Ownership & Placement:**
     The adapter is implemented as a pure functional module at `research_track/track_b/src/adapter_c.py` (and corresponding backend service `backend/app/services/screening_adapter.py`). It imports zero Track C policy rules or database models.
  2. **Data Preservation Invariants:**
     - **Lossless `Decimal` Quantities:** `quantity` is parsed and maintained as `Decimal` or `None`. Floating-point conversion is prohibited. Supports fractional amounts (e.g., `2.5` KG).
     - **Nullable Quantity Preservation:** Missing or unparseable quantities strictly evaluate to `None`. Under no circumstances may missing quantities be defaulted to `0` or `1`, which would subvert quantity-dependent policy thresholds (e.g., hazardous chemicals $\ge 3$ units).
     - **Unit Taxonomy Normalization:** Units are mapped via `CANONICAL_UNIT_MAP` (e.g., `litres` $\to$ `LTR`, `kgs` $\to$ `KG`, `packets` $\to$ `PACK`), while unmapped strings are preserved in uppercase to trigger policy reason code `UNSUPPORTED_QUANTITY_UNIT`.
     - **Deterministic Line IDs:** Propagates `line_item_id` intact or generates canonical deterministic ID: `f"line-{document_id}-{index + 1}"`.
     - **Description Provenance:** Retains both `normalized_description` for NLP inference and `raw_description` for audit trails.
  3. **Verification:** Verified by isolated unit test `research_track/review/tests/test_adapter_c.py` passing 100%.

---

## Decision 6: Database Contract (Hybrid Schema for Indexing & Tamper-Proof Audit)

* **Status:** **RESOLVED**
* **Previous State:** Finding `X-S2-002` noted divergence between draft models and requirements for nullable confidence, stable reason codes, policy versioning, and immutable audit trails.
* **Formal Decision & Specification:**
  1. **Hybrid Architecture Specification:**
     The database schema implements a two-tier hybrid model:
     - **Tier 1: Normalized Columns for Relational Querying & High-Speed Filtering:**
       - `id (UUID)`, `invoice_id (UUID)`, `outcome (Enum: ALLOW, REVIEW, ALERT)`, `policy_version (VARCHAR(40))`, `security_alert_id (UUID, nullable)`, `created_at (TIMESTAMPTZ)`.
       - Array columns for fast filtering: `reason_codes (VARCHAR(80)[])`, `matched_rule_ids (UUID[])`.
       - In `invoice_line_classifications`: `confidence` is explicitly `Float, nullable=True`; `is_uncertain` is `Boolean, nullable=False, default=False`.
     - **Tier 2: Full Immutable Raw Screening JSON Payload (`raw_screening_payload` JSONB):**
       - Stores the complete, tamper-proof audit trail of the decision event:
         - Complete classifier output (raw tokens, candidate probabilities, model version).
         - Rule evaluation trace (`rules_considered`, `matching_candidates`, `rejected_rules` with specific rejection rationales, `conflicts_detected`, `applied_rule_id`, `resolution_method`).
         - Canonical SHA-256 event digest (`scr-{line_item_id}-{hash}`) verifying payload non-repudiation.
  2. **Security & Auditability Guarantees:**
     - The `invoice_screening_results` table is strictly append-only. Database-level permissions revoke `UPDATE` and `DELETE` operations for the application role.
     - Any historical screening decision can be bit-for-bit replayed and audited against the historical `policy_version` active at the timestamp of entry.

---

## Operational Protocols for Remaining Prerequisites

### Item 7: Authorized Real-World Campus Data Collection Protocol
* **Status:** **OPERATIONAL PROTOCOL ACTIVE**
* **Protocol:**
  1. Target Domain: Punjab Engineering College (PEC) perimeter gates (`GATE_1`, `GATE_2`, `GATE_3`).
  2. Image & Video Acquisition: Capture 200+ day/night/blur/high-angle gate camera frames with explicit institutional authorization.
  3. Commercial Invoices: Collect 100+ consented delivery invoices (Zomato, Swiggy, Blinkit, Amazon, local courier slips) with PII redacted (names, phone numbers, delivery addresses).
  4. Item Taxonomy: Collect and human-label 500+ real campus delivery line items to calibrate Qwen3-1.7B QLoRA confidence thresholds.
  5. **Provenance Tagging:** All benchmark and report metrics must continue to display the explicit provenance label: *"Benchmark on synthetic/third-party dataset, NOT PEC gate performance"* until this real campus dataset is collected and evaluated.

### Item 8: Compute Approval & Training Resource Management
* **Status:** **OPERATIONAL PROTOCOL ACTIVE**
* **Protocol:**
  1. **Local Training Environment:**
     - To prevent RAM gate failures, ensure GNOME `localsearch-3` is halted (`tracker3 daemon -t` or `systemctl --user stop tracker-extract-3`) before ML execution, maintaining $\ge 6.0\text{ GiB}$ free RAM.
     - Set `export KERAS_BACKEND=torch` in the Python 3.12 virtual environment (`~/ml-assets/campus/.venv-ml`) to avoid TensorFlow 2.21 CUDA incompatibility.
     - Run OCR fine-tuning using `cct_s_v2_global.keras` with 11-slot configuration on `prepared/ocr_in_v1`.
  2. **Cloud/VLM Training:**
     - Training `Qwen3-VL-2B-Instruct` on invoices requires $\ge 16\text{ GiB}$ GPU VRAM. Requires AWS EC2 `g4dn.xlarge` (or equivalent) gated on explicit user compute approval and cost token before provisioning.
