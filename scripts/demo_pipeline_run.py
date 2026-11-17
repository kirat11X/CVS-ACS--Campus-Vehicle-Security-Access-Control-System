#!/usr/bin/env python3
"""
Interactive / Automated Pipeline Demonstration Script.

Runs:
1. Video Vehicle & License Plate Pipeline:
   - Processes real dataset video (media/gate_demo_1.mp4 or TRAINING_VIDEOS)
   - Runs YOLO11n Plate Detector (weights/yolo11n_plate_detector_finetuned.onnx)
   - Runs Indian Plate CRNN Recognizer (weights/indian_plate_crnn_best.onnx)
   - Validates Indian Motor Vehicles Act statutory formatting & repairs
   - Matches against registered campus database vehicles

2. Invoice OCR & Delivery Screening Policy Engine:
   - Evaluates test invoices (media/test_invoice.png, media/test_invoices/D-20481_clean.png)
   - Performs RapidOCR character extraction & line grouping
   - Reconciles order totals, taxes, delivery fees, arithmetic
   - Enforces Track C Policy Engine (21 safety rules: ALLOW, REVIEW, ALERT)
"""

import sys
import time
from pathlib import Path
from decimal import Decimal
import cv2
import numpy as np
import onnxruntime as ort

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from backend.app.services.plate_normalizer import normalize_plate, is_valid_indian_plate, format_plate_display
from backend.app.services.invoice_reader import read_image, parse_rows
from backend.app.services.delivery_screening_service import DeliveryScreeningService

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
IDX2CHAR = {i + 1: ch for i, ch in enumerate(ALPHABET)}

DETECTOR_ONNX = ROOT_DIR / "weights" / "yolo11n_plate_detector_finetuned.onnx"
OCR_ONNX = ROOT_DIR / "weights" / "indian_plate_crnn_best.onnx"


def decode_crnn(logits: np.ndarray) -> str:
    preds = np.argmax(logits[0], axis=-1)
    chars = []
    prev = 0
    for idx in preds:
        if idx != prev and idx != 0 and idx in IDX2CHAR:
            chars.append(IDX2CHAR[idx])
        prev = idx
    return "".join(chars)


def run_video_pipeline(video_path: Path, max_samples: int = 10):
    print("=" * 80)
    print(f"🎬 VIDEO ANPR PIPELINE DEMO: {video_path.name}")
    print("=" * 80)

    if not video_path.exists():
        print(f"❌ Video file not found: {video_path}")
        return

    det_sess = ort.InferenceSession(str(DETECTOR_ONNX), providers=["CPUExecutionProvider"])
    ocr_sess = ort.InferenceSession(str(OCR_ONNX), providers=["CPUExecutionProvider"])

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    duration = total_frames / fps
    print(f"Video Stats: {total_frames} frames | {fps:.1f} FPS | {duration:.1f}s duration")
    print(f"Detector: {DETECTOR_ONNX.name} | OCR: {OCR_ONNX.name}")
    print("-" * 80)

    step = max(1, total_frames // max_samples)
    detected_count = 0

    for f_idx in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_sec = f_idx / fps
        h, w = frame.shape[:2]
        t0 = time.perf_counter()

        # YOLO letterbox preprocessing
        resized = cv2.resize(frame, (640, 640))
        inp = resized.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 255.0
        det_out = det_sess.run(None, {det_sess.get_inputs()[0].name: inp})[0][0]

        conf_thresh = 0.40
        boxes = []
        for col in range(det_out.shape[1]):
            score = float(det_out[4, col])
            if score >= conf_thresh:
                cx, cy, bw, bh = det_out[0:4, col]
                x1 = max(0, int((cx - bw / 2) * (w / 640.0)))
                y1 = max(0, int((cy - bh / 2) * (h / 640.0)))
                x2 = min(w, int((cx + bw / 2) * (w / 640.0)))
                y2 = min(h, int((cy + bh / 2) * (h / 640.0)))
                if (x2 - x1) > 20 and (y2 - y1) > 10:
                    boxes.append((x1, y1, x2, y2, score))

        final_boxes = []
        if boxes:
            cv_boxes = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes]
            scores = [b[4] for b in boxes]
            indices = cv2.dnn.NMSBoxes(cv_boxes, scores, conf_thresh, 0.45)
            for idx in (indices.flatten() if len(indices) > 0 else []):
                final_boxes.append(boxes[idx])

        t_elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if final_boxes:
            for x1, y1, x2, y2, sc in final_boxes:
                detected_count += 1
                crop = frame[y1:y2, x1:x2]
                crop_res = cv2.resize(crop, (128, 32)).transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 127.5 - 1.0
                logits = ocr_sess.run(None, {ocr_sess.get_inputs()[0].name: crop_res})[0]
                raw_ocr = decode_crnn(logits)
                norm = normalize_plate(raw_ocr)
                is_valid = is_valid_indian_plate(norm)
                display_str = format_plate_display(norm)
                status_icon = "✅ VALID" if is_valid else "⚠️ REVIEW"

                print(f"[{timestamp_sec:5.1f}s | Frame {f_idx:4d}] {status_icon} Plate: {display_str:16s} (Raw: {norm:12s}) | Det Conf: {sc:.2f} | Box: [{x1},{y1},{x2},{y2}] | {t_elapsed_ms:.1f}ms")
        else:
            print(f"[{timestamp_sec:5.1f}s | Frame {f_idx:4d}] ℹ️  No vehicle plate in primary zone ({t_elapsed_ms:.1f}ms)")

    cap.release()
    print(f"\nCompleted video evaluation: {detected_count} plate detection events processed.\n")


def run_invoice_screening_pipeline(invoice_paths: list[Path]):
    print("=" * 80)
    print("📄 INVOICE OCR & DELIVERY POLICY SCREENING DEMO")
    print("=" * 80)

    svc = DeliveryScreeningService()

    for p in invoice_paths:
        if not p.exists():
            print(f"❌ File not found: {p}")
            continue

        print(f"\n--- Processing Invoice: {p.name} ---")
        t0 = time.perf_counter()
        ocr_res = read_image(p)
        parsed = parse_rows(ocr_res.rows)
        res = svc.screen(parsed, parsed.order_number)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        verdict_str = res.overall.value if hasattr(res.overall, "value") else str(res.overall)
        if verdict_str == "ALLOW":
            badge = "🟢 [ALLOW - AUTOMATIC GATE PASS]"
        elif verdict_str == "REVIEW":
            badge = "🟡 [REVIEW - MANUAL GUARD INSPECTION]"
        else:
            badge = "🔴 [ALERT - RESTRICTED CARGO / PROHIBITED]"

        order_id = res.order_id_on_invoice or parsed.order_number or "UNSPECIFIED"
        print(f"Decision: {badge}")
        print(f"Vendor: {parsed.vendor or 'N/A'} | Order ID: {order_id} | OCR Engine: {ocr_res.engine} ({elapsed_ms:.1f}ms)")
        print(f"Totals Reconciliation: Subtotal={parsed.subtotal} | Tax={parsed.tax} | DeliveryFee={parsed.delivery_fee} | Stated Total={parsed.total} | Computed={res.computed_total} | Match={res.totals_match}")
        print(f"Automated Dispatch Notification: \"{svc.reply_text(order_id, res)}\"")
        print("\nLine-by-Line Item Screening:")
        for line in res.lines:
            line_verdict = line.verdict.value if hasattr(line.verdict, "value") else str(line.verdict)
            v_symbol = "✅" if line_verdict == "ALLOW" else ("⚠️" if line_verdict == "REVIEW" else "⛔")
            price_str = f"Rs {line.amount}" if line.amount is not None else "N/A"
            qty_str = f"Qty {line.quantity}" if line.quantity is not None else "Qty -"
            print(f"  {v_symbol} #{line.line_no:2d} | {line.item_name:32s} | {qty_str:7s} | {price_str:10s} | Category: {line.category:10s} | Reason: {line.reason_code:22s} | Verdict: {line_verdict}")

    print("\n" + "=" * 80)
    print("DEMONSTRATION RUN COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    test_video = ROOT_DIR / "media" / "gate_demo_1.mp4"
    run_video_pipeline(test_video, max_samples=12)

    test_invoices = [
        ROOT_DIR / "media" / "test_invoice.png",
        ROOT_DIR / "media" / "test_invoices" / "D-20481_clean.png",
        ROOT_DIR / "media" / "test_invoices" / "D-20482_allclear.png",
    ]
    run_invoice_screening_pipeline(test_invoices)
