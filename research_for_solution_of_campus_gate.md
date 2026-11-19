# Research for Solution of Campus Gate (CVS-ACS ANPR Upgrade)

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Scope:** Camera & ANPR Pipeline Only (`backend/app/workers/camera_stream_runner.py`, `backend/app/services/plate_normalizer.py`, `research_track/track_a/`, and `ec2/`). **Telegram connector (`backend/app/telegram/`) remains untouched.**

---

## 1. Deep Analysis: Mapping the 5 Solutions to the Actual CVS-ACS Codebase

| Solution from Research | What CVS-ACS Already Has | What Is Missing / Broken in CVS-ACS | Verdict |
| :--- | :--- | :--- | :--- |
| **Solution 1:** Soft CIE LAB Yellow-Black Color Remapping | Nothing — raw BGR crop goes straight to OCR | Useful as a **fallback** for yellow-biased weights; **fix Python syntax bugs in pasted snippet** (`212.0 * (1.0 - fg_score)`) | **Keep as Fallback** |
| **Solution 2:** Multi-Color & EV Dataset Fine-Tuning | `prepared/plate_det_in_v1` (1,716 imgs), `prepared/ocr_in_v1` (13,698 crops), `ec2/` scripts | Missing Indian **Green EV** plates (white-on-green & yellow-on-green), `umar1103/final-licence`, and 200–400 real PEC gate frames | **Phase 2 (EC2 / T4 GPU)** |
| **Solution 3:** Color-Agnostic CLAHE + Otsu Polarity Inversion + 2–98% Stretch | Whole-frame Laplacian `< 40` only | **Primary missing fix** — strips color bias and auto-inverts green EV plates (3.40:1–4.52:1 contrast) into dark-on-bright text | **Implement First (Primary)** |
| **Solution 4:** Plate-Specialized ONNX OCR + Padding + Deskew + 2-Line Split | `indian_plate_crnn_best.onnx` & `track_a_ocr_cct.onnx` exist, **but RapidOCR runs first**; `0px` crop padding; no deskew; no 2-line split | Flip OCR order (`CCT/CRNN` first, `Awiros/anpr-ocr` or RapidOCR fallback), add `+8% W / +5% H` padding, deskew (`>5°`), and horizontal ink-projection split when `w/h < 2.4` | **Implement Immediately** |
| **Solution 5:** CMVR Rule 50 Positional Grammar + Per-Track Voting | Non-positional `itertools.combinations` in `backend/app/services/plate_normalizer.py`; gate-level buffer | Replace with positional State + `BH` grammar corrector (`O/0, I/1, B/8, S/5, G/6, D/0, A/4, Z/2`), tie voting strictly to `track_id`, and route 5-frame non-standard consensus (military/diplomatic/temp) to `SecurityReviewPage` | **Implement Immediately** |

### Critical Code Bugs Caught in the Pasted Research Snippets
1. **Broken arithmetic in Solution 1 & Solution 3 snippets:** The pasted text dropped `*` and `-` operators (`212.0(1.0fg_score)` and `255L_eq`). All Antigravity prompts below specify the corrected formulas (`212.0 * (1.0 - fg_score) + 18.0 * fg_score` and `255 - L_eq`).
2. **Do not apply Solution 1 AND Solution 3 blindly in series:** Run **Solution 3 (`normalize_plate_agnostic`)** as the primary preprocessor for ONNX OCR (`fast-plate-ocr` / CRNN / RapidOCR). Only run **Solution 1 (`remap_to_yellow_black`)** as a secondary pass if Solution 3 returns low confidence (`< 0.65`) or fails grammar validation.
3. **Skip the left 14% HSRP blue `IND` strip** when computing Otsu polarity or CIE LAB green/yellow ratios so the blue band never biases EV detection.

---

## 2. Sub-Region Copy-Paste Prompts for Antigravity

Execute these **4 sub-region prompts in order** so each subsystem is cleanly built, unit-tested, and verified before moving to the next.

---

### Sub-Region 1: Save Research Doc + Crop Preprocessing (Padding, Deskew, Solution 3 & Solution 1)

```text
Work ONLY on the camera/ANPR preprocessing layer in `/home/kirat/coding/honours` (do NOT modify `backend/app/telegram/` or `backend/app/routes/telegram.py`):

1. Save a clean documentation file at `research/RESEARCH_FOR_SOLUTION_OF_CAMPUS_GATE.md` documenting the 5-solution white & green-EV plate recognition architecture (CMVR Rule 50 contrast bottlenecks, CIE LAB remapping, CLAHE + Otsu polarity inversion + 2-98% stretch, plate-specialized ONNX OCR + 2-line split, positional RTO grammar + ByteTrack consensus, and Phase 2 dataset plan).

2. Create `backend/app/services/plate_preprocessor.py` implementing:
   - `pad_plate_bbox(x1, y1, x2, y2, frame_w, frame_h, pad_x=0.08, pad_y=0.05)`: expands Stage-1 YOLO boxes by +8% width and +5% height (clamped to frame) so trailing digits and leading state letters are never clipped.
   - `deskew_plate(crop_bgr)`: estimates tilt via Hough/minAreaRect when skew is between 3° and 25° and rotates via `cv2.getRotationMatrix2D` + `warpAffine`.
   - `split_two_line_plate(crop_bgr)`: when `w / h < 2.4` (2-wheelers, auto-rickshaws, square car plates), splits horizontally along the minimum ink-projection row between 38% and 62% of image height, returning `[top_crop, bottom_crop]`; otherwise returns `[crop_bgr]`.
   - `normalize_plate_agnostic(crop_bgr) -> tuple[np.ndarray, bool]` (Solution 3 — Primary): converts BGR -> LAB, applies CLAHE (`clipLimit=2.5, tileGridSize=(8, 4)`) on `L*`, runs Otsu thresholding on the central ROI (`y: 15%-85%, x: 15%-92%`, skipping the left 14% blue `IND` strip), inverts via `255 - L_eq` when `mean(bw == 255) < 0.45` (white-on-green / yellow-on-green EV plates), and applies 2nd–98th percentile stretching.
   - `remap_to_yellow_black(crop_bgr) -> tuple[np.ndarray, str]` (Solution 1 — Fallback): soft CIE LAB continuous alpha-blending (skipping left 14% `IND` strip) with exact math: `out_L = np.clip(212.0 * (1.0 - fg_score) + 18.0 * fg_score, 0, 255)` etc. for green EV (`green_fraction > 0.30`) and white private plates (`yellow_fraction < 0.25`).

3. Add unit tests in `backend/tests/test_plate_preprocessor.py` using synthetic Yellow Taxi, White Private, White-on-Green EV, Yellow-on-Green EV, tilted, and 2-line square plates verifying polarity inversion, percentile background normalization, padding clamping, and 2-line splitting. Run pytest and commit.
```

---

### Sub-Region 2: Plate-Specialized ONNX OCR Priority & Empty-Space Gate (`camera_stream_runner.py`)

```text
Upgrade Stage-2 OCR execution and false-positive filtering in `/home/kirat/coding/honours/backend/app/workers/camera_stream_runner.py` (leave `backend/app/telegram/` untouched):

1. Integrate `plate_preprocessor.py` into `process_frame()`:
   - Relax box limits to `0.9 <= w/h <= 6.0` and `bw >= 32, bh >= 16` so 2-wheeler and auto-rickshaw plates are not dropped.
   - Add a crop-level plate-likeness gate (reject flat/empty-space crops with grayscale `std < 22.0` or Canny edge density `< 0.04` or `> 0.55`).
   - Expand each YOLO plate box with `pad_plate_bbox(..., pad_x=0.08, pad_y=0.05)`, run `deskew_plate()`, and check `split_two_line_plate()`.
2. Dual-Pass Plate-Specialized OCR Cascade:
   - Pass 1 (Primary): Run `normalize_plate_agnostic()` (Solution 3) -> plate-specialized ONNX OCR (`weights/track_a_ocr_cct.onnx` or `weights/indian_plate_crnn_best.onnx`; for 2-line splits, run OCR on top & bottom halves and join `top + bottom`).
   - Pass 2 (Fallback): If Pass 1 returns empty, low confidence (`< 0.65`), or fails `correct_indian_plate()`, run `remap_to_yellow_black()` (Solution 1) + RapidOCR (with top-to-bottom, left-to-right box sorting) and keep the higher-confidence valid read.
3. Add unit tests verifying: (a) empty-wall crop rejection, (b) 2-line bike/auto split + join, and (c) green EV plate recovery via Solution 3 / Solution 1 cascade. Run pytest and commit.
```

---

### Sub-Region 3: CMVR Rule 50 Positional Grammar, Vehicle Class & Per-Track Voting

```text
Upgrade positional plate repair, vehicle classification, and per-track consensus in `/home/kirat/coding/honours` (leave `backend/app/telegram/` untouched):

1. Positional CMVR Rule 50 Corrector in `backend/app/services/plate_normalizer.py`:
   - Replace non-positional `itertools.combinations` with `correct_indian_plate(raw_text) -> tuple[str, bool, str]`:
     * Strip non-alphanumerics and accidental leading `IND` (`len >= 10`).
     * **Bharat Series (`YY BH NNNN XX`)**: detect `BH`/`8H`/`B4` at indices `2:4`; enforce `0:2` digits, `2:4` `BH`, `4:8` digits, `8:` letters (`A-HJ-NP-Z`).
     * **Standard State (`SS R[R] [XXX] NNNN`)**: enforce `0:2` valid state letters (`ALL_VALID_STATES`), `2:3` (and `3:4` for 2-digit RTO) digits, middle series letters (no `I`/`O`), and last `4` digits using `TO_DIGIT` (`O/Q/D->0, I/L->1, Z->2, S->5, G->6, B->8, A->4`) and `TO_ALPHA` (`0->O, 1->I, 2->Z, 4->A, 5->S, 6->G, 8->B`).
     * Preserve Vintage (`VA`), Diplomatic (`CD`/`CC`/`UN`), Temporary (`T...`), and Military detections as `NON_STANDARD_VALID` or route to manual review rather than silently dropping.
2. Vehicle Class & Same-Vehicle Tracking in `camera_stream_runner.py`:
   - Run vehicle detection (`yolo11n.onnx` / `yolo11n_indian_vehicle.onnx`) to tag `car`, `two_wheeler`, `auto_rickshaw`, `bus`, `truck` and require plate boxes to fall inside (or within 15% margin of) a detected vehicle box.
   - Assign persistent `track_id` per vehicle (IoU/Kalman + HSV/MobileNetV3 appearance signature `>= 0.82` for `is_same_vehicle`).
   - Run **confidence-weighted per-position voting** per `track_id` over `5-15` frames (weighting valid CMVR-length strings `1.5x` over truncated reads). Once `>= 3` matching reads agree, emit once per `track_id`. If `>= 5` frames yield consensus with `is_valid=False` (e.g., diplomatic/temp/damaged), route to `SecurityReviewPage` (`MANUAL_CHECK`) with the cropped plate image instead of dropping silently.
3. Add unit tests for `correct_indian_plate` (State, `BH`, `IND` strip, truncated rejection) and per-track weighted voting. Run pytest + `vite build` and push to `origin/main`.
```

---

### Sub-Region 4: Phase 2 — Campus Gate & Multi-Color/EV Fine-Tuning Pipeline (`ec2/` & `scripts/`)

```text
Prepare the Phase 2 multi-color (White, Yellow, Green EV) fine-tuning pipeline in `/home/kirat/coding/honours` (no live training yet—just scripts & dataset manifests):

1. Update `scripts/download_datasets.py` and `DATASETS_AND_MODELS.md` to add optional staging hooks for:
   - `umar1103/final-licence` (Kaggle CC BY 4.0 — 30,000 Indian plate OCR crops)
   - `dataclusterlabs` Electric Vehicle Number Plate dataset & Roboflow `electric-vehicle-number-plate-bwvra` (CC BY 4.0 — green EV plates)
   - `Awiros/anpr-ocr` (Hugging Face Apache-2.0 — Indian PP-OCRv5 checkpoint)
   - Explicitly exclude `minalchoudhary/india-ev-dataset` (tabular CSV, no images).
2. Add `scripts/capture_gate_calibration_frames.py` to sample 200–400 frames from `GATE_1` (prioritizing white private cars, green EVs, 2-wheelers, and autos) and enforce **leak-free splitting** grouped by `normalized_plate` and `> 5s` temporal burst gaps.
3. Update `ec2/train_track_a_ocr.sh` to support fine-tuning `fast-plate-ocr` (`cct-s-v2`) with `KERAS_BACKEND=torch` on the merged multi-color + EV + PEC gate split. Verify `--help` / dry-run passes and push to `origin/main`.
```
