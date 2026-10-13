# Track C: Synthetic Test Cases & Evaluation Matrix

This document specifies the complete evaluation matrix of **115 synthetic screening test cases** designed for offline evaluation of the Track C item classifier interface and deterministic screening policy engine.

All test fixtures are stored in machine-readable JSON under `fixtures/synthetic_screening_cases.json` and `fixtures/synthetic_ground_truth.json`.

---

## 1. Test Suite Summary

| Suite ID | Test Range | Category / Feature Under Test | Expected Outcome | Key Reason Code |
| :--- | :--- | :--- | :--- | :--- |
| **S1** | TC-001 – TC-015 | Prohibited Tobacco & Nicotine (cigarettes, bidi, vapes, gutka, Hinglish sutta) | `ALERT` | `CATEGORY_RULE_ALERT` |
| **S2** | TC-016 – TC-030 | Prohibited Alcohol (beer, whisky, rum, vodka, Hinglish daru, truncated names) | `ALERT` | `CATEGORY_RULE_ALERT` |
| **S3** | TC-031 – TC-045 | Prohibited Rx Scheduled Drugs (codeine, alprazolam, tramadol, ritalin, steroids) | `ALERT` | `CATEGORY_RULE_ALERT` |
| **S4** | TC-046 – TC-055 | Permitted OTC Medicines (paracetamol, cough drops, antiseptics, antacids, band-aids) | `ALLOW` | `CATEGORY_RULE_ALLOW` |
| **S5** | TC-056 – TC-065 | Hazardous Chemicals Bulk ($\ge 3$ units: drain cleaner, acid, phenyl, pesticides) | `REVIEW` | `CATEGORY_RULE_REVIEW`, `HAZARDOUS_THRESHOLD_MET` |
| **S6** | TC-066 – TC-075 | Hazardous Chemicals Household ($< 3$ units: single-pack disinfectant, nail polish remover) | `ALLOW` | `CATEGORY_RULE_ALLOW` |
| **S7** | TC-076 – TC-080 | Hazardous Chemicals Edge Cases (missing quantity, negative quantity, invalid unit) | `REVIEW` | `MISSING_QUANTITY`, `INVALID_QUANTITY`, `UNSUPPORTED_QUANTITY_UNIT` |
| **S8** | TC-081 – TC-090 | Controlled Sharp Objects (kitchen knives, razor blades, paper cutters, scissors, scalpels) | `REVIEW` | `CATEGORY_RULE_REVIEW` |
| **S9** | TC-091 – TC-093 | Platform Overrides (Instamart delivery of sharp objects escalating to priority 5) | `ALERT` | `CATEGORY_RULE_ALERT`, `MULTIPLE_RULES_MATCHED` |
| **S10** | TC-094 – TC-097 | Deterministic Priority Tie Conflicts (two matching rules with equal priority & differing actions) | `REVIEW` | `POLICY_RULE_CONFLICT`, `MANUAL_REVIEW_REQUIRED` |
| **S11** | TC-098 – TC-100 | Low Classifier Confidence ($< 0.70$ threshold safety degradation) | `REVIEW` | `LOW_CLASSIFIER_CONFIDENCE` |
| **S12** | TC-101 – TC-103 | Missing Classifier Confidence (`None` safety degradation) | `REVIEW` | `MISSING_CLASSIFIER_CONFIDENCE` |
| **S13** | TC-104 – TC-108 | Explicit `UNKNOWN` Category & Corrupted OCR / Novel SKUs | `REVIEW` | `UNKNOWN_CATEGORY`, `MANUAL_REVIEW_REQUIRED` |
| **S14** | TC-109 – TC-115 | Permitted Normal Campus Goods (snacks, dairy, bakery, stationery, electronics) | `ALLOW` | `CATEGORY_RULE_ALLOW` |

---

## 2. Detailed Test Cases Matrix

### Suite 1: Prohibited Tobacco & Nicotine Products (TC-001 – TC-015)
*Campus Security Invariant: Direct ALERT regardless of quantity or platform.*

| ID | Description | Style | Qty / Unit | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-001` | Gold Flake Kings (10s) | normal | 1.0 PACK | BLINKIT | 0.98 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-002` | Classic Milds 20 Pack | normal | 2.0 PACK | ZEPTO | 0.95 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-003` | Marlboro Advance Filter | normal | 1.0 PACK | INSTAMART | 0.97 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-004` | Chhoti Gold Flake | hinglish | 1.0 PACK | BLINKIT | 0.91 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-005` | Badi Advance sutta | hinglish | 2.0 PCS | ZEPTO | 0.93 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-006` | Classic Reg 10 Pk | truncated | 1.0 PACK | BLINKIT | 0.92 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-007` | Marl Adv 20s | truncated | 1.0 PACK | INSTAMART | 0.94 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-008` | Ganesh Beedi Bundle | normal | 5.0 PACK | BLINKIT | 0.96 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-009` | bidi packet chota | hinglish | 2.0 PACK | ZEPTO | 0.90 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-010` | Rajnigandha Pan Masala | normal | 1.0 PACK | BLINKIT | 0.94 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-011` | Shikhar gutka | hinglish | 10.0 PACK | BLINKIT | 0.95 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-012` | Vape Pen 5000 puffs | normal | 1.0 PCS | INSTAMART | 0.96 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-013` | Elfbar Kiwi Passion | normal | 1.0 PCS | ZEPTO | 0.95 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-014` | Nicotex 2mg Mint | normal | 1.0 PACK | BLINKIT | 0.88 | `ALERT` | `RULE-TOBACCO-DEFAULT` |
| `TC-015` | Hookah flavor double apple | hinglish | 1.0 PACK | BLINKIT | 0.92 | `ALERT` | `RULE-TOBACCO-DEFAULT` |

---

### Suite 2: Prohibited Alcohol Products (TC-016 – TC-030)
*Campus Security Invariant: Direct ALERT regardless of volume or delivery service.*

| ID | Description | Style | Qty / Unit | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-016` | Kingfisher Premium Beer 650ml | normal | 2.0 BOTTLE | BLINKIT | 0.99 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-017` | Budweiser Magnum Strong 500ml | normal | 4.0 BOTTLE | ZEPTO | 0.99 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-018` | Bira 91 White Pint | normal | 1.0 BOTTLE | INSTAMART | 0.98 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-019` | KF Strong 650ml | truncated | 1.0 BOTTLE | BLINKIT | 0.96 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-020` | Thandi beer bottle | hinglish | 2.0 BOTTLE | ZEPTO | 0.94 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-021` | Royal Stag Deluxe Whisky 750ml | normal | 1.0 BOTTLE | BLINKIT | 0.99 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-022` | Blenders Pride Rare Premium 750ml | normal | 1.0 BOTTLE | INSTAMART | 0.99 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-023` | RS Whisky qtr | truncated | 2.0 BOTTLE | BLINKIT | 0.95 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-024` | desi daru quarter | hinglish | 1.0 BOTTLE | ZEPTO | 0.97 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-025` | Old Monk Rum 750ml | normal | 1.0 BOTTLE | BLINKIT | 0.99 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-026` | Bacardi Carta Blanca 750ml | normal | 1.0 BOTTLE | INSTAMART | 0.98 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-027` | Sula Chenin Blanc 750ml | normal | 1.0 BOTTLE | BLINKIT | 0.98 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-028` | Magic Moments Vodka 750ml | normal | 1.0 BOTTLE | ZEPTO | 0.98 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-029` | vodka santra flavor | hinglish | 1.0 BOTTLE | BLINKIT | 0.95 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |
| `TC-030` | Breezer Cranberry 275ml | normal | 3.0 BOTTLE | INSTAMART | 0.95 | `ALERT` | `RULE-ALCOHOL-DEFAULT` |

---

### Suite 3: Prohibited Rx Scheduled Drugs (TC-031 – TC-045)
*Campus Security Invariant: Narcotics, sedatives, controlled stimulants, and steroids trigger ALERT.*

| ID | Description | Style | Qty / Unit | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-031` | Corex Cough Syrup | normal | 1.0 BOTTLE | BLINKIT | 0.97 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-032` | Phensedyl Linctus | normal | 1.0 BOTTLE | ZEPTO | 0.98 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-033` | Rexcod cough | truncated | 1.0 BOTTLE | INSTAMART | 0.94 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-034` | khasi ki dawai nasha | hinglish | 1.0 BOTTLE | BLINKIT | 0.91 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-035` | Alprax 0.5mg Tablets | normal | 1.0 PACK | ZEPTO | 0.98 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-036` | Restyl 0.25mg | normal | 1.0 PACK | BLINKIT | 0.97 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-037` | neend ki goli | hinglish | 1.0 PACK | ZEPTO | 0.92 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-038` | Tramadol Hydrochloride 50mg | normal | 1.0 PACK | INSTAMART | 0.99 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-039` | Ultracet Tablet | normal | 1.0 PACK | BLINKIT | 0.98 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-040` | dard ki heavy goli | hinglish | 1.0 PACK | ZEPTO | 0.89 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-041` | Ritalin 10mg | normal | 1.0 PACK | BLINKIT | 0.99 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-042` | Modalert 200mg | normal | 1.0 PACK | INSTAMART | 0.97 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-043` | Testoviron Depot | normal | 2.0 BOTTLE | BLINKIT | 0.98 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-044` | Diazepam 5mg | normal | 1.0 PACK | ZEPTO | 0.99 | `ALERT` | `RULE-RX-DEFAULT` |
| `TC-045` | calmpose goli | hinglish | 1.0 PACK | BLINKIT | 0.95 | `ALERT` | `RULE-RX-DEFAULT` |

---

### Suite 4: Permitted OTC Medicine & First Aid (TC-046 – TC-055)
*Standard medical sundries are permitted (ALLOW).*

| ID | Description | Style | Qty / Unit | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-046` | Crocin Advance 500mg | normal | 1.0 PACK | BLINKIT | 0.99 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-047` | Dolo 650 Tablets | normal | 1.0 PACK | ZEPTO | 0.99 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-048` | bukhar ki goli | hinglish | 1.0 PACK | BLINKIT | 0.92 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-049` | Vicks VapoRub 25ml | normal | 1.0 BOTTLE | INSTAMART | 0.98 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-050` | Strepsils Orange 8s | normal | 2.0 PACK | BLINKIT | 0.97 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-051` | Burnol Cream 10g | normal | 1.0 PCS | ZEPTO | 0.96 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-052` | Digene Tablets Mint | normal | 1.0 PACK | BLINKIT | 0.97 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-053` | Volini Spray 40g | normal | 1.0 BOTTLE | INSTAMART | 0.98 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-054` | Band-Aid Standard | normal | 1.0 PACK | BLINKIT | 0.99 | `ALLOW` | `RULE-OTC-DEFAULT` |
| `TC-055` | Eno Lemon Sachet | normal | 5.0 PACK | ZEPTO | 0.98 | `ALLOW` | `RULE-OTC-DEFAULT` |

---

### Suite 5: Hazardous Chemicals Bulk ($\ge 3$ units) (TC-056 – TC-065)
*Quantities at or above threshold trigger REVIEW with HAZARDOUS_THRESHOLD_MET.*

| ID | Description | Style | Qty / Unit | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-056` | Harpic Power Plus 500ml | normal | 3.0 BOTTLE | BLINKIT | 0.98 | `REVIEW` | `RULE-HAZMAT-BULK-BOTTLE` |
| `TC-057` | Kiwi Dranex Drain Cleaner | normal | 4.0 PACK | ZEPTO | 0.97 | `REVIEW` | `RULE-HAZMAT-BULK-PACK` |
| `TC-058` | Lizol Floor Cleaner 1L | normal | 5.0 BOTTLE | INSTAMART | 0.96 | `REVIEW` | `RULE-HAZMAT-BULK-BOTTLE` |
| `TC-059` | safai acid toilet | hinglish | 3.0 BOTTLE | BLINKIT | 0.95 | `REVIEW` | `RULE-HAZMAT-BULK-BOTTLE` |
| `TC-060` | phenyl ki bottle | hinglish | 6.0 BOTTLE | ZEPTO | 0.94 | `REVIEW` | `RULE-HAZMAT-BULK-BOTTLE` |
| `TC-061` | HIT Black Aerosol | normal | 3.0 BOTTLE | BLINKIT | 0.96 | `REVIEW` | `RULE-HAZMAT-BULK-BOTTLE` |
| `TC-062` | Baygon Roach Killer | normal | 4.0 BOTTLE | INSTAMART | 0.95 | `REVIEW` | `RULE-HAZMAT-BULK-BOTTLE` |
| `TC-063` | Ratol Rat Poison | normal | 3.0 PACK | ZEPTO | 0.98 | `REVIEW` | `RULE-HAZMAT-BULK-PACK` |
| `TC-064` | Paint Thinner Bottle | normal | 3.0 BOTTLE | BLINKIT | 0.97 | `REVIEW` | `RULE-HAZMAT-BULK-BOTTLE` |
| `TC-065` | Bleaching Powder 500g | normal | 5.0 PACK | ZEPTO | 0.95 | `REVIEW` | `RULE-HAZMAT-BULK-PACK` |

---

### Suite 6: Hazardous Chemicals Household ($< 3$ units) (TC-066 – TC-075)
*Small domestic quantities permitted with audit record.*

| ID | Description | Style | Qty / Unit | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-066` | Harpic Power Plus 500ml | normal | 1.0 BOTTLE | BLINKIT | 0.98 | `ALLOW` | `RULE-HAZMAT-LOW-BOTTLE` |
| `TC-067` | Kiwi Dranex Drain Cleaner | normal | 2.0 PACK | ZEPTO | 0.97 | `ALLOW` | `RULE-HAZMAT-LOW-PACK` |
| `TC-068` | Lizol Floor Cleaner 1L | normal | 1.0 BOTTLE | INSTAMART | 0.96 | `ALLOW` | `RULE-HAZMAT-LOW-BOTTLE` |
| `TC-069` | HIT Black Aerosol | normal | 1.0 BOTTLE | BLINKIT | 0.96 | `ALLOW` | `RULE-HAZMAT-LOW-BOTTLE` |
| `TC-070` | Colorbar Nail Polish Remover | ambiguous | 1.0 BOTTLE | INSTAMART | 0.88 | `ALLOW` | `RULE-HAZMAT-LOW-BOTTLE` |
| `TC-071` | Mortein Mosquito Spray | normal | 2.0 BOTTLE | ZEPTO | 0.97 | `ALLOW` | `RULE-HAZMAT-LOW-BOTTLE` |
| `TC-072` | chuhe marne ki dawa | hinglish | 1.0 PACK | BLINKIT | 0.92 | `ALLOW` | `RULE-HAZMAT-LOW-PACK` |
| `TC-073` | Acetone Thinner 100ml | normal | 1.0 BOTTLE | ZEPTO | 0.95 | `ALLOW` | `RULE-HAZMAT-LOW-BOTTLE` |
| `TC-074` | Bleach Pdr 50 | truncated | 2.0 PACK | BLINKIT | 0.93 | `ALLOW` | `RULE-HAZMAT-LOW-PACK` |
| `TC-075` | Hrpc Pwr 500m | truncated | 2.0 BOTTLE | BLINKIT | 0.94 | `ALLOW` | `RULE-HAZMAT-LOW-BOTTLE` |

---

### Suite 7: Hazardous Chemicals Input Anomalies (TC-076 – TC-080)
*Missing quantity, negative values, and unsupported units must safely route to REVIEW.*

| ID | Description | Anomaly Type | Qty / Unit | Expected Outcome | Triggered Reason Code |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-076` | Kiwi Dranex Drain Cleaner | Missing quantity | null / null | `REVIEW` | `MISSING_QUANTITY` |
| `TC-077` | Harpic Power Plus 500ml | Negative quantity | -2.0 BOTTLE | `REVIEW` | `INVALID_QUANTITY` |
| `TC-078` | Lizol Floor Cleaner 1L | Unsupported unit | 1.0 INVALID_UNIT | `REVIEW` | `UNSUPPORTED_QUANTITY_UNIT` |
| `TC-079` | Mortein Mosquito Spray | Null quantity | null / BOTTLE | `REVIEW` | `MISSING_QUANTITY` |
| `TC-080` | Paint Thinner Bottle | Negative quantity | -1.0 BOTTLE | `REVIEW` | `INVALID_QUANTITY` |

---

### Suite 8: Controlled Sharp Objects (TC-081 – TC-090)
*Kitchen cutlery, razor blades, and box cutters require guard inspection (REVIEW).*

| ID | Description | Style | Qty / Unit | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-081` | Crystal Stainless Steel Knife | normal | 1.0 PCS | BLINKIT | 0.98 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-082` | Gillette Mach3 Razor | normal | 1.0 PACK | ZEPTO | 0.97 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-083` | Gillette 7 O'Clock Blades | normal | 2.0 PACK | BLINKIT | 0.98 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-084` | chaaku kitchen wala | hinglish | 1.0 PCS | ZEPTO | 0.94 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-085` | blade packet | hinglish | 1.0 PACK | BLINKIT | 0.95 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-086` | Kangaro Paper Cutter | normal | 1.0 PCS | BLINKIT | 0.96 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-087` | Maped Scissors 17cm | normal | 1.0 PCS | ZEPTO | 0.97 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-088` | Box Cutter Utility | normal | 1.0 PCS | BLINKIT | 0.98 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-089` | kainchi chhoti | hinglish | 1.0 PCS | ZEPTO | 0.93 | `REVIEW` | `RULE-SHARP-DEFAULT` |
| `TC-090` | Surgical Blades Pack | normal | 1.0 PACK | BLINKIT | 0.97 | `REVIEW` | `RULE-SHARP-DEFAULT` |

---

### Suite 9: Platform-Specific Rule Overrides (TC-091 – TC-093)
*Higher-precedence platform rule (priority 5) overrides category default (priority 10).*

| ID | Description | Platform | Priority | Expected Outcome | Applied Rule ID | Reason Codes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-091` | Crystal Stainless Steel Knife | INSTAMART | 5 | `ALERT` | `RULE-OVERRIDE-INSTAMART-SHARP` | `CATEGORY_RULE_ALERT` |
| `TC-092` | Meat Cleaver Heavy Duty | INSTAMART | 5 | `ALERT` | `RULE-OVERRIDE-INSTAMART-SHARP` | `CATEGORY_RULE_ALERT` |
| `TC-093` | Victorinox Swiss Army Knife | INSTAMART | 5 | `ALERT` | `RULE-OVERRIDE-INSTAMART-SHARP` | `CATEGORY_RULE_ALERT` |

---

### Suite 10: Deterministic Priority Tie Conflict Resolution (TC-094 – TC-097)
*Two rules matching at equal highest priority with conflicting actions must NEVER allow; routes safely to REVIEW.*

| ID | Description | Platform | Matched Conflicting Rules | Expected Outcome | Triggered Reason Code |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-094` | Crocin Advance 500mg | TEST_CONFLICT | RULE-CONFLICT-A & B (p=15) | `REVIEW` | `POLICY_RULE_CONFLICT`, `MANUAL_REVIEW_REQUIRED` |
| `TC-095` | Dolo 650 Tablets | TEST_CONFLICT | RULE-CONFLICT-A & B (p=15) | `REVIEW` | `POLICY_RULE_CONFLICT`, `MANUAL_REVIEW_REQUIRED` |
| `TC-096` | Vicks Action 500 | TEST_CONFLICT | RULE-CONFLICT-A & B (p=15) | `REVIEW` | `POLICY_RULE_CONFLICT`, `MANUAL_REVIEW_REQUIRED` |
| `TC-097` | Band-Aid Standard | TEST_CONFLICT | RULE-CONFLICT-A & B (p=15) | `REVIEW` | `POLICY_RULE_CONFLICT`, `MANUAL_REVIEW_REQUIRED` |

---

### Suite 11: Low Classifier Confidence Safety Degradation (TC-098 – TC-100)
*Model confidence $< 0.70$ downgrades ALLOW to REVIEW.*

| ID | Description | Category | Confidence | Original Outcome | Degraded Outcome | Reason Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-098` | Lays Magic Masala 52g | NORMAL | 0.45 | ALLOW | `REVIEW` | `LOW_CLASSIFIER_CONFIDENCE` |
| `TC-099` | Amul Taaza Milk 500ml | NORMAL | 0.62 | ALLOW | `REVIEW` | `LOW_CLASSIFIER_CONFIDENCE` |
| `TC-100` | Crocin Advance 500mg | OTC_MEDICINE | 0.55 | ALLOW | `REVIEW` | `LOW_CLASSIFIER_CONFIDENCE` |

---

### Suite 12: Missing Classifier Confidence Safety Degradation (TC-101 – TC-103)
*Classifier confidence is `None` (lexical baseline); downgrades ALLOW to REVIEW.*

| ID | Description | Category | Confidence | Original Outcome | Degraded Outcome | Reason Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-101` | Maggi 2-Min Masala Pack | NORMAL | null | ALLOW | `REVIEW` | `MISSING_CLASSIFIER_CONFIDENCE` |
| `TC-102` | Britannia Brown Bread 400g | NORMAL | null | ALLOW | `REVIEW` | `MISSING_CLASSIFIER_CONFIDENCE` |
| `TC-103` | Dolo 650 Tablets | OTC_MEDICINE | null | ALLOW | `REVIEW` | `MISSING_CLASSIFIER_CONFIDENCE` |

---

### Suite 13: Explicit UNKNOWN Category & Corrupted OCR (TC-104 – TC-108)
*Items with no recognized category trigger mandatory human review.*

| ID | Description | Category | Confidence | Expected Outcome | Triggered Reason Code |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-104` | XKJ-9943 1pc | UNKNOWN | 0.20 | `REVIEW` | `UNKNOWN_CATEGORY`, `MANUAL_REVIEW_REQUIRED` |
| `TC-105` | random barcode ### | UNKNOWN | null | `REVIEW` | `UNKNOWN_CATEGORY`, `MANUAL_REVIEW_REQUIRED` |
| `TC-106` | Unknown Box item #44 | UNKNOWN | 0.15 | `REVIEW` | `UNKNOWN_CATEGORY`, `MANUAL_REVIEW_REQUIRED` |
| `TC-107` | Misprinted receipt text ?? | UNKNOWN | null | `REVIEW` | `UNKNOWN_CATEGORY`, `MANUAL_REVIEW_REQUIRED` |
| `TC-108` | Unspecified Chemical Vial | UNKNOWN | 0.35 | `REVIEW` | `UNKNOWN_CATEGORY`, `MANUAL_REVIEW_REQUIRED` |

---

### Suite 14: Permitted Normal Campus Goods (TC-109 – TC-115)
*Standard food, snacks, stationery, and cables evaluate to ALLOW.*

| ID | Description | Platform | Confidence | Expected Outcome | Applied Rule ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `TC-109` | Lays Magic Masala 52g | BLINKIT | 0.99 | `ALLOW` | `RULE-OVERRIDE-BLINKIT-NORMAL` |
| `TC-110` | Parle-G Biscuit 800g | ZEPTO | 0.99 | `ALLOW` | `RULE-NORMAL-DEFAULT` |
| `TC-111` | Amul Taaza Milk 500ml | BLINKIT | 0.99 | `ALLOW` | `RULE-OVERRIDE-BLINKIT-NORMAL` |
| `TC-112` | Kinley Water Bottle 1L | INSTAMART | 0.99 | `ALLOW` | `RULE-NORMAL-DEFAULT` |
| `TC-113` | Classmate Notebook 140 Pages | BLINKIT | 0.98 | `ALLOW` | `RULE-OVERRIDE-BLINKIT-NORMAL` |
| `TC-114` | Apple iPhone 20W Charger | ZEPTO | 0.97 | `ALLOW` | `RULE-NORMAL-DEFAULT` |
| `TC-115` | Cadbury Dairy Milk Silk 150g | BLINKIT | 0.99 | `ALLOW` | `RULE-OVERRIDE-BLINKIT-NORMAL` |

---

## 3. Property-Based Verification Matrix

Beyond individual test cases, the offline verification suite validates these invariants:

1. **Rule-Order Invariance**: Shuffling the order of rules in the loaded ruleset yields 100% identical outputs for all 115 test cases.
2. **Determinism**: Re-evaluating the test set 100 times produces bit-exact identical outputs.
3. **Safety Fallback on Priority Tie**: When multiple active rules conflict at equal priority, outcome is guaranteed to be `REVIEW`, never `ALLOW`.
4. **Zero Silent ALLOW on Perception Failure**: Zero instances where `is_uncertain=True`, `confidence=None`, or `confidence < 0.70` result in an `ALLOW` outcome.
