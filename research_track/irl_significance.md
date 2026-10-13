# Real-World Significance: PEC Campus Vehicle Security ML Track

Date: 2026-10-09. Companion to `research.md` (the literature) and `finetune/RESULTS_*.md` (the measured numbers).

This document explains why the three research tracks matter outside the lab: who they help, what could go wrong, and what still has to happen before any of it touches a real gate. Every number quoted here carries its provenance label. **None of them is a measurement of performance at PEC's gates.**

---

## 1. The real problem

PEC Chandigarh has three perimeter gates staffed by guards. Today the guards:

- note vehicle plates by eye and cross-check them against who is allowed in;
- receive a growing stream of quick-commerce deliveries (Blinkit, Zepto, Swiggy Instamart, Zomato) whose contents they cannot see;
- carry final responsibility for every entry, usually with no searchable record of what happened at the other two gates.

The system this track supports is a **decision-support layer, not an access-control robot**. It records what the cameras and invoices show, links that to registered campus context where the evidence is strong enough, and gives the guard a short, explained summary. The guard still decides. The barrier is never actuated by software.

## 2. What each track would change at a gate

| Track | Real-world job | Who benefits | Current evidence (provenance) |
|---|---|---|---|
| **A: Indian plate reading + registry match** | Read the plate, suggest the matching registered vehicle, or say "ambiguous / no match" | Guards (less manual typing and lookup), residents (faster entry), security office (a searchable timeline across all three gates) | Plate detector mAP50 0.897 on 36 Kaggle images; pretrained Indian LPRNet read 21/23 crops correctly in an informal check. Label: *"IN-02 Kaggle CC0 crops, NOT PEC gate performance"*. No OCR model has been fine-tuned yet (no licensed text-labelled data). |
| **B: Invoice line-item extraction** | Turn a WhatsApp invoice photo into a structured list of items, quantities and totals | Guards (no need to read small print on a phone), delivery workers (faster, more consistent checks) | Deterministic baseline on 32 synthetic invoices: schema-valid 100%, arithmetic pass 87.5%. Not approved for training. |
| **C: Item category proposal** | Propose a category (alcohol, tobacco, Rx drug, hazardous, sharp, normal, unknown) for each line item. A **deterministic policy table**, not the model, maps the category to ALLOW / REVIEW / ALERT. | Guards (attention focused on the few items that matter), administration (consistent, auditable rules) | QLoRA Qwen3-1.7B: test accuracy 0.841 [0.746, 0.921], macro-F1 0.818. Label: *"synthetic LLM-authored items; measures fit to that distribution, not real invoice accuracy"*. |

### Why this is worth doing

- **Indian plates are under-served.** Both Indian ANPR papers in `research.md` say that models trained on Chinese, Brazilian or European plates transfer poorly to Indian plates. Indian plates mix fonts, two-line layouts, non-standard designs, HSRP and BH-series formats. A PEC-specific evaluation adds evidence where little exists.
- **It runs on cheap hardware.** Everything so far ran on one laptop GPU (RTX 4050, 6 GB) at $0. On CPU, three pretrained plate readers together processed 1,840 crops in 47 s, model loading included (under 26 ms per crop for all three combined; per-model latency was not measured separately). A campus or housing society could run this without cloud costs or sending images off-site.
- **One timeline across three gates.** Linking observations from all gates is what turns isolated sightings into useful context, such as "this vehicle entered at Gate 1 but no exit was recorded".
- **Delivery volume keeps rising.** Manually reading every invoice does not scale. A structured list plus a category proposal lets a guard check 10 items in seconds and spend attention on the one flagged item.

## 3. Why the design rules matter in practice

The project's invariants are not bureaucratic. Each one prevents a specific real-world harm.

| Invariant | Real-world harm it prevents |
|---|---|
| **A plate is not an identity** | Plates are cloned, borrowed, misread or swapped. Treating "plate read = person present" would wrongly accuse the registered owner. The system only says *this plate string was observed*. |
| **Observation ≠ decision; no barrier control** | A misread must never lock someone out or let someone in. The pretrained LPRNet confidently printed `MH09BB4445` for an unreadable crop. That output is harmless only because a human reviews it. |
| **ML perception separate from deterministic policy** | Rules ("alcohol → ALERT") stay readable, versioned and changeable by the administration without retraining a model. When something goes wrong, you can tell whether the model or the rule was at fault. |
| **Ambiguity is rejected, not guessed** (Track A Δ < 0.07 → AMBIGUOUS) | Near-identical plates (`MH12AB1234` vs `MH12AB1284`) must not be silently resolved to the wrong owner. |
| **UNKNOWN never becomes NORMAL** | "Some unknown item" must not slip through as safe. Track C's one safety-relevant test error was exactly this (`koi anjaan samaan` → NORMAL). That is why a missing or low confidence forces REVIEW. |
| **Append-only, soft-delete audit** | Every alert and override can be traced later. This protects guards ("I followed the system") and the people screened ("why was I flagged?"). |

## 4. Risks and who carries them

| Risk | Who is affected | Mitigation in this design | Still open |
|---|---|---|---|
| **Privacy and surveillance creep**: plate logs reveal people's movements | Students, staff, residents, visitors, delivery workers | Plate ≠ identity; registry match only for registered vehicles; data stays on campus | Retention period, access control, notice and signage, purpose limitation (see §5) |
| **Misreads cause false alerts** | Whoever drives the misread vehicle | Human review; ambiguity rejection; no barrier control | No measured misread rate on PEC footage yet |
| **Uneven error rates**: two-line plates, faded or non-standard plates, motorcycles | Owners of older or two-wheeler vehicles, who may be flagged more often | Error analysis per plate type is planned | Two-line plates were LPRNet's main failure; needs PEC data to quantify |
| **Over-escalation in Track C**: dosage strings pull items to "Rx", and Hinglish phrasing causes errors | Delivery workers (delays), residents ordering ordinary medicine | Over-escalation goes to REVIEW (safe direction) | 4 of 10 test errors were over-escalations; real invoices may differ |
| **Automation bias**: guards rubber-stamp the system | Everyone | UI shows evidence and reasons, not just a verdict | Guard training and override-rate monitoring are not yet designed |
| **Licensing** | The institution | Licenses recorded in MANIFEST files | Indian LPRNet weights have **no license**: research comparison only, not deployable without author permission |

## 5. Legal and regulatory context (India)

This is context for the thesis, not legal advice. Verify every item against the official Gazette text before relying on it.

- **Digital Personal Data Protection Act, 2023** (assent 11 Aug 2023). A plate linked to a registered owner is personal data. Consent or a legitimate use, purpose limitation, data minimisation, security safeguards and erasure obligations apply to the registry and the observation logs.
- **DPDP Rules, 2025** (G.S.R. 846(E), 13 Nov 2025). Commencement is phased: some rules in force from 13 Nov 2025, Rule 4 from 13 Nov 2026, most operative rules (3, 5–16, 22–23) from 13 May 2027. A pilot after May 2027 would fall under the full rules, so the deployment plan should be designed for them now.
- **High Security Registration Plates (HSRP).** MoRTH amended the Central Motor Vehicles Rules (notification dated 6 Dec 2018) so that new vehicles come with pre-fitted HSRP from 1 April 2019. Many states also require retrofitting. Standardised HSRP fonts help OCR, but older non-HSRP plates remain on campus roads.
- **Bharat (BH) series** (G.S.R. 594(E), 26 Aug 2021, effective 15 Sep 2021). Format `YY BH #### XX`, for example `22BH1234AA`. A reader trained only on state-code plates will misread these. Track A's normaliser already treats them as a separate format.

## 6. What "real-world ready" would require

Today's status is **research prototype, synthetic or third-party data only**. A responsible path to a real gate:

1. **Consented PEC data.** Gate footage collected with notice and signage, and an approved retention period. Hand-labelled plate text for a held-out test set. Consented invoice screenshots. Real line items labelled by people, including UNKNOWN and ambiguous cases.
2. **Privacy assessment** in the spirit of the DPDP Act: purpose, data flows, retention, access roles, and how a person can ask what was recorded about them.
3. **Shadow mode at one gate.** The system observes and suggests, but nothing is shown to guards as a recommendation. Compare its suggestions with what guards actually did.
4. **Measure the right things.** Guard override rate, false-alert rate per 100 vehicles, time to clear a delivery, misread rate by plate type (HSRP / old / two-line / BH / two-wheeler), and how often UNKNOWN items are caught.
5. **Calibrated confidence** for Track C before any model NORMAL is allowed to contribute to ALLOW.
6. **Licensed models only** in anything beyond research. Use MIT or Apache models (fast-plate-ocr global CCT, Qwen3), not the unlicensed LPRNet weights.
7. **Guard training and a clear escalation path.** The system supports guards' judgement; it does not replace it.

## 7. Broader significance

- **Reusable pattern.** "Probabilistic perception → deterministic, auditable policy → human decision" applies to any Indian institution with gates: universities, hospitals, housing societies, industrial campuses.
- **Honest evaluation practice.** Family-grouped splits, a test split touched exactly once, bootstrap confidence intervals and explicit provenance labels make the results trustworthy at small scale. Many ANPR results do not do this (see the near-duplicate study in `research.md`).
- **Low-cost, on-premise AI.** Showing useful accuracy on a laptop GPU with zero cloud cost makes this feasible for institutions with small budgets, and keeps personal data on-site.

## Sources (legal/regulatory)

- DPDP Act 2023 text (TRAI-hosted copy): https://www.trai.gov.in/sites/default/files/2024-09/DPDT_11082024.pdf. Official: https://www.indiacode.nic.in
- DPDP Rules 2025 PIB backgrounder: https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf
- DPDP Rules 2025 commencement summary: https://www.scconline.com/blog/post/2025/11/14/meity-notified-digital-personal-data-protection-rules-2025/
- HSRP mandate, MoRTH Dec 2018: https://indianinfrastructure.com/2018/12/03/morth-mandates-sale-of-vehicles-with-pre-fitted-hsrp/ ; https://www.hondacarindia.com/honda-services/important-information/hsrp-regulation
- BH series, G.S.R. 594(E): https://factly.in/explainer-all-you-need-to-know-about-the-new-bharat-or-bh-series-for-vehicle-registration
