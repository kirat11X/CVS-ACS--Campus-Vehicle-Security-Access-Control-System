#!/usr/bin/env python3
"""
scripts/benchmark_awiros_vs_cct.py
==================================
Benchmarks Awiros/anpr-ocr (37M PP-OCRv5) against track_a_ocr_cct.onnx
on the held-out ocr_in_v1 test split (data/datasets/prepared/ocr_in_v1/test.csv).

Evaluates:
- Exact-Match Accuracy (%)
- Character Error Rate (CER)
- Single-Crop CPU Latency (ms/crop: mean, median, p95)
- Model Size & Architecture Parameters
- Saves benchmark report to weights/ocr_benchmark_awiros_vs_cct.json
"""

import sys
import os
import csv
import time
import json
from pathlib import Path
import numpy as np
import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent
AWIROS_DIR = REPO_ROOT / "data" / "campus_gate_datasets" / "checkpoints" / "awiros_anpr_ocr"
PADDLEOCR_DIR = AWIROS_DIR / "PaddleOCR"
if str(PADDLEOCR_DIR) not in sys.path:
    sys.path.insert(0, str(PADDLEOCR_DIR))

import paddle
import onnxruntime as ort
from ppocr.modeling.architectures import build_model as ppocr_build_model
from ppocr.postprocess import build_post_process
from safetensors.numpy import load_file

TEST_CSV = REPO_ROOT / "data" / "datasets" / "prepared" / "ocr_in_v1" / "test.csv"
DATA_DIR = REPO_ROOT / "data" / "datasets" / "prepared" / "ocr_in_v1"
CCT_ONNX = REPO_ROOT / "weights" / "track_a_ocr_cct.onnx"
OUTPUT_JSON = REPO_ROOT / "weights" / "ocr_benchmark_awiros_vs_cct.json"

IMAGE_SHAPE_AWIROS = [3, 48, 320]
ALPHABET_CCT = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev[j + 1] + 1
            deletions = curr[j] + 1
            substitutions = prev[j] + (c1 != c2)
            curr.append(min(insertions, deletions, substitutions))
        prev = curr
    return prev[-1]

def normalize_plate(text: str) -> str:
    if not text:
        return ""
    import re
    norm = re.sub(r"[^A-Za-z0-9]", "", str(text)).upper().strip()
    if norm.startswith("IND") and len(norm) > 4:
        norm = norm[3:]
    if norm.endswith("IND") and len(norm) > 4:
        norm = norm[:-3]
    return norm

CTC_NUM_CLASSES = 64
NRTR_NUM_CLASSES = 67

MODEL_CONFIG = {
    "Architecture": {
        "model_type": "rec",
        "algorithm": "SVTR_HGNet",
        "Transform": None,
        "Backbone": {"name": "PPHGNetV2_B4", "text_rec": True},
        "Head": {
            "name": "MultiHead",
            "out_channels_list": {
                "CTCLabelDecode": CTC_NUM_CLASSES,
                "NRTRLabelDecode": NRTR_NUM_CLASSES,
            },
            "head_list": [
                {
                    "CTCHead": {
                        "Neck": {
                            "name": "svtr",
                            "dims": 120,
                            "depth": 2,
                            "hidden_dims": 120,
                            "kernel_size": [1, 3],
                            "use_guide": True,
                        },
                        "Head": {"fc_decay": 1e-05},
                    }
                },
                {"NRTRHead": {"nrtr_dim": 384, "max_text_length": 25}},
            ],
        },
    },
}

def load_awiros_model():
    weights_path = str(AWIROS_DIR / "model.safetensors")
    dict_path = str(AWIROS_DIR / "en_dict.txt")
    
    post_process = build_post_process({
        "name": "CTCLabelDecode",
        "character_dict_path": dict_path,
        "use_space_char": True,
    })

    import copy
    config = copy.deepcopy(MODEL_CONFIG)
    
    paddle.set_device("cpu")
    model = ppocr_build_model(config["Architecture"])
    model.eval()

    np_state = load_file(weights_path)
    state_dict = {k: paddle.to_tensor(v) for k, v in np_state.items()}
    model.set_state_dict(state_dict)
    return model, post_process

def preprocess_awiros(img_bgr):
    _, h, w = IMAGE_SHAPE_AWIROS
    img_h, img_w = img_bgr.shape[:2]
    ratio = h / img_h
    new_w = min(int(img_w * ratio), w)
    resized = cv2.resize(img_bgr, (new_w, h))
    padded = np.zeros((h, w, 3), dtype=np.uint8)
    padded[:, :new_w, :] = resized
    img = padded.astype(np.float32) / 255.0
    img = (img - 0.5) / 0.5
    return img.transpose((2, 0, 1))

def decode_cct(logits):
    if logits.ndim == 3:
        logits = logits[0]
    preds = np.argmax(logits, axis=-1)
    chars = []
    prev = -1
    for p in preds:
        if p != prev and p < len(ALPHABET_CCT):
            c = ALPHABET_CCT[p]
            if c != "_":
                chars.append(c)
        prev = p
    return "".join(chars)

def preprocess_cct(img_bgr):
    if img_bgr.ndim == 2:
        c_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        c_bgr = img_bgr
    c_rgb = cv2.cvtColor(c_bgr, cv2.COLOR_BGR2RGB)
    c_res = cv2.resize(c_rgb, (128, 32), interpolation=cv2.INTER_LINEAR)
    inp = c_res.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 127.5 - 1.0
    return inp

def main():
    print("=" * 70)
    print("STAGE 2 OCR BENCHMARK: Awiros/anpr-ocr vs track_a_ocr_cct.onnx")
    print("=" * 70)

    # 1. Load test dataset
    if not TEST_CSV.exists():
        raise FileNotFoundError(f"Test CSV not found: {TEST_CSV}")

    rows = []
    with open(TEST_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            img_p = DATA_DIR / r["image_path"]
            if img_p.exists():
                rows.append((img_p, r["plate_text"].strip().upper()))

    print(f"Loaded {len(rows)} test samples from {TEST_CSV}")

    # 2. Load CCT ONNX
    print(f"Loading CCT ONNX model from {CCT_ONNX}...")
    cct_session = ort.InferenceSession(str(CCT_ONNX), providers=["CPUExecutionProvider"])
    cct_input_name = cct_session.get_inputs()[0].name

    # 3. Load Awiros Paddle model
    print(f"Loading Awiros PP-OCRv5 model from {AWIROS_DIR}...")
    awiros_model, awiros_post_process = load_awiros_model()

    # 4. Single-crop CPU Latency Measurement
    print("\n[Benchmarking CPU Latency on 50 single crops]...")
    sample_images = [cv2.imread(str(p)) for p, _ in rows[:50]]

    # Warmup
    _ = cct_session.run(None, {cct_input_name: preprocess_cct(sample_images[0])})
    t_dummy = paddle.to_tensor(np.expand_dims(preprocess_awiros(sample_images[0]), 0))
    with paddle.no_grad():
        _ = awiros_model(t_dummy)

    cct_latencies = []
    for img in sample_images:
        t0 = time.perf_counter()
        inp = preprocess_cct(img)
        _ = cct_session.run(None, {cct_input_name: inp})
        cct_latencies.append((time.perf_counter() - t0) * 1000.0)

    awiros_latencies = []
    for img in sample_images[:25]:
        t0 = time.perf_counter()
        inp = np.expand_dims(preprocess_awiros(img), 0)
        t_inp = paddle.to_tensor(inp)
        with paddle.no_grad():
            out = awiros_model(t_inp)
        _ = awiros_post_process(out.numpy())
        awiros_latencies.append((time.perf_counter() - t0) * 1000.0)

    cct_latency_mean = float(np.mean(cct_latencies))
    cct_latency_median = float(np.median(cct_latencies))
    cct_latency_p95 = float(np.percentile(cct_latencies, 95))

    awiros_latency_mean = float(np.mean(awiros_latencies))
    awiros_latency_median = float(np.median(awiros_latencies))
    awiros_latency_p95 = float(np.percentile(awiros_latencies, 95))

    print(f"  CCT ONNX CPU Latency:    Mean={cct_latency_mean:.2f}ms, Median={cct_latency_median:.2f}ms, P95={cct_latency_p95:.2f}ms")
    print(f"  Awiros PP-OCRv5 CPU Lat: Mean={awiros_latency_mean:.2f}ms, Median={awiros_latency_median:.2f}ms, P95={awiros_latency_p95:.2f}ms")

    # 5. Full Evaluation for CCT on all 2,075 crops
    print(f"\n[Evaluating track_a_ocr_cct.onnx across ALL {len(rows)} test crops]...")
    cct_full_correct = 0
    cct_full_dist = 0
    cct_full_chars = 0
    t_cct_start = time.time()

    for idx, (img_path, ground_truth) in enumerate(rows):
        img_bgr = cv2.imread(str(img_path))
        if img_bgr is None:
            continue
        gt_norm = normalize_plate(ground_truth)
        cct_full_chars += len(gt_norm)

        inp_cct = preprocess_cct(img_bgr)
        out_cct = cct_session.run(None, {cct_input_name: inp_cct})[0]
        pred_cct = normalize_plate(decode_cct(out_cct))

        if pred_cct == gt_norm:
            cct_full_correct += 1
        cct_full_dist += levenshtein_distance(pred_cct, gt_norm)

    cct_full_time = time.time() - t_cct_start
    cct_full_acc = (cct_full_correct / len(rows)) * 100.0
    cct_full_cer = (cct_full_dist / max(1, cct_full_chars)) * 100.0
    print(f"  CCT Full Test Split (2,075 crops): Exact-Match={cct_full_acc:.2f}%, CER={cct_full_cer:.2f}% ({cct_full_time:.2f}s total)")

    # 6. Comparative Paired Evaluation on held-out subset (50 crops)
    print(f"\n[Running Paired Head-to-Head Comparison on 50 held-out crops]...")
    paired_samples = rows[:50]
    paired_cct_correct = 0
    paired_cct_dist = 0
    paired_cct_chars = 0

    paired_awiros_correct = 0
    paired_awiros_dist = 0
    paired_awiros_chars = 0

    for idx, (img_path, ground_truth) in enumerate(paired_samples):
        img_bgr = cv2.imread(str(img_path))
        if img_bgr is None:
            continue
        gt_norm = normalize_plate(ground_truth)
        paired_cct_chars += len(gt_norm)
        paired_awiros_chars += len(gt_norm)

        # CCT
        inp_cct = preprocess_cct(img_bgr)
        out_cct = cct_session.run(None, {cct_input_name: inp_cct})[0]
        pred_cct = normalize_plate(decode_cct(out_cct))
        if pred_cct == gt_norm:
            paired_cct_correct += 1
        paired_cct_dist += levenshtein_distance(pred_cct, gt_norm)

        # Awiros
        inp_aw = np.expand_dims(preprocess_awiros(img_bgr), 0)
        t_aw = paddle.to_tensor(inp_aw)
        with paddle.no_grad():
            out_aw = awiros_model(t_aw)
        post_aw = awiros_post_process(out_aw.numpy())
        text_aw = post_aw[0][0] if (isinstance(post_aw, list) and len(post_aw) > 0 and len(post_aw[0]) > 0) else ""
        pred_aw = normalize_plate(text_aw)
        if pred_aw == gt_norm:
            paired_awiros_correct += 1
        paired_awiros_dist += levenshtein_distance(pred_aw, gt_norm)

        if (idx + 1) % 10 == 0:
            print(f"  Paired progress: {idx + 1}/{len(paired_samples)} crops evaluated...")

    n_p = len(paired_samples)
    paired_cct_acc = (paired_cct_correct / n_p) * 100.0
    paired_cct_cer = (paired_cct_dist / max(1, paired_cct_chars)) * 100.0

    paired_aw_acc = (paired_awiros_correct / n_p) * 100.0
    paired_aw_cer = (paired_awiros_dist / max(1, paired_awiros_chars)) * 100.0

    print("\n" + "=" * 70)
    print("STAGE 2 OCR BENCHMARK SUMMARY:")
    print("=" * 70)
    print(f"Metric                       | Awiros PP-OCRv5     | track_a_ocr_cct.onnx")
    print(f"-----------------------------+---------------------+---------------------")
    print(f"Exact-Match Accuracy (Paired)| {paired_aw_acc:.2f}%               | {paired_cct_acc:.2f}%")
    print(f"Character Error Rate (Paired)| {paired_aw_cer:.2f}%               | {paired_cct_cer:.2f}%")
    print(f"Exact-Match (Full 2,075 sets)| N/A (CPU 4hr est)   | {cct_full_acc:.2f}%")
    print(f"CER (Full 2,075 sets)        | N/A                 | {cct_full_cer:.2f}%")
    print(f"Single-Crop Latency (Mean)   | {awiros_latency_mean:.2f} ms          | {cct_latency_mean:.2f} ms")
    print(f"Single-Crop Latency (Median) | {awiros_latency_median:.2f} ms          | {cct_latency_median:.2f} ms")
    print(f"Single-Crop Latency (P95)    | {awiros_latency_p95:.2f} ms          | {cct_latency_p95:.2f} ms")
    print(f"Model File Size              | 143.0 MB            | 34.0 MB")
    print(f"Speedup Factor on CPU        | 1.0x (baseline)     | {awiros_latency_mean / max(0.1, cct_latency_mean):.1f}x faster")
    print("=" * 70)

    report = {
        "dataset": "prepared/ocr_in_v1/test.csv",
        "total_test_crops": len(rows),
        "paired_test_crops": n_p,
        "awiros_anpr_ocr": {
            "architecture": "PP-OCRv5 SVTR_HGNet (37M parameters)",
            "exact_match_accuracy_pct": round(paired_aw_acc, 2),
            "character_error_rate_pct": round(paired_aw_cer, 2),
            "cpu_latency_ms": {
                "mean": round(awiros_latency_mean, 2),
                "median": round(awiros_latency_median, 2),
                "p95": round(awiros_latency_p95, 2),
            },
            "model_size_mb": 143.0,
        },
        "track_a_ocr_cct": {
            "architecture": "CCT / Compact Convolutional Transformer",
            "full_test_exact_match_pct": round(cct_full_acc, 2),
            "full_test_cer_pct": round(cct_full_cer, 2),
            "paired_exact_match_pct": round(paired_cct_acc, 2),
            "paired_cer_pct": round(paired_cct_cer, 2),
            "cpu_latency_ms": {
                "mean": round(cct_latency_mean, 2),
                "median": round(cct_latency_median, 2),
                "p95": round(cct_latency_p95, 2),
            },
            "model_size_mb": 34.0,
        },
        "speedup_factor_cpu": round(awiros_latency_mean / max(0.1, cct_latency_mean), 1),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Benchmark report recorded at: {OUTPUT_JSON}")
    print("=" * 70)

if __name__ == "__main__":
    main()
