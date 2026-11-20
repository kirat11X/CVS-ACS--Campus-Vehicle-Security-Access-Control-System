#!/usr/bin/env python3
"""
scripts/benchmark_gate_demo_videos.py
=====================================
Benchmarks the complete Campus Gate ANPR 3-Stage Cascade on gate demo videos:
- Stage 0: Zero-training Indian Vehicle Gatekeeper (UVH-26 YOLO11-S) with early exit
- Stage 1: Fine-tuned Multi-Color & Green-EV Plate Detector (YOLO11n) inside vehicle crops
- Stage 2: Agnostic Preprocessing, Dual-Pass OCR, CMVR Rule 50 Positional Repair, and Track Voting

Runs on:
- media/gate_demo_1.mp4
- media/gate_demo_2.mp4
"""

import sys
import os
import time
import json
from pathlib import Path
from typing import Dict, Any, List

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend.app.workers.camera_stream_runner import (
    VehicleGatekeeper,
    VehicleTrack,
    letterbox_image,
    WEIGHTS_DIR,
)
from backend.app.services.anpr.color_remap import remap_to_yellow_black
from backend.app.services.anpr.polarity_normalizer import normalize_plate_agnostic
from backend.app.services.anpr.ocr_engine import (
    pad_plate_bbox,
    is_plate_like_crop,
    split_two_line_plate,
    deskew_plate,
    run_dual_pass_ocr,
)
from backend.app.services.anpr.track_voter import TrackVoter
from backend.app.services.plate_normalizer import (
    correct_indian_plate,
    is_valid_indian_plate,
    classify_plate_format,
    normalize_plate,
)

import onnxruntime as ort

DEMO_VIDEOS = [
    REPO_ROOT / "media" / "gate_demo_1.mp4",
    REPO_ROOT / "media" / "gate_demo_2.mp4",
]
OUTPUT_METRICS = WEIGHTS_DIR / "gate_demo_benchmark_results.json"


def evaluate_video(
    video_path: Path,
    gatekeeper: VehicleGatekeeper,
    det_sess: ort.InferenceSession,
    max_frames: int = 150,
) -> Dict[str, Any]:
    print("\n" + "=" * 70)
    print(f"🎬 EVALUATING GATE VIDEO: {video_path.name}")
    print("=" * 70)

    if not video_path.is_file():
        print(f"❌ Video file not found: {video_path}")
        return {"error": "file_not_found", "video": str(video_path)}

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    duration_s = total_frames / video_fps
    print(f"Stats: {total_frames} frames | {video_fps:.1f} FPS | {duration_s:.1f}s")

    track_voter = TrackVoter(min_consensus_frames=3, max_track_frames=8)

    frames_processed = 0
    stage0_early_exits = 0
    total_vehicles_seen = 0
    total_plates_detected = 0
    total_ocr_reads = 0
    unique_tracks = set()

    stage0_latencies = []
    stage1_latencies = []
    stage2_latencies = []

    detections_log = []

    step = max(1, total_frames // max_frames)

    for f_idx in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        frames_processed += 1
        h, w = frame.shape[:2]
        frame_ts = f_idx / video_fps

        # -------------------------------------------------------------
        # Stage 0: Vehicle Gatekeeper (UVH-26)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        v_dets = gatekeeper.detect_vehicles(frame)
        stage0_latencies.append((time.perf_counter() - t0) * 1000.0)

        if not v_dets:
            stage0_early_exits += 1
            continue

        total_vehicles_seen += len(v_dets)

        # -------------------------------------------------------------
        # Stage 1: Zoomed Plate Detection inside each vehicle crop
        # -------------------------------------------------------------
        t1 = time.perf_counter()
        frame_plate_boxes = []

        for v_idx, v_det in enumerate(v_dets):
            v_crop, (vx1, vy1, vx2, vy2) = VehicleGatekeeper.crop_vehicle(frame, v_det.bbox, pad_pct=0.05)
            if v_crop.size == 0 or v_crop.shape[0] < 20 or v_crop.shape[1] < 20:
                continue

            vh, vw = v_crop.shape[:2]
            canvas, scale, dx, dy = letterbox_image(v_crop, 640)
            canvas_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
            inp = canvas_rgb.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 255.0

            det_out = det_sess.run(None, {det_sess.get_inputs()[0].name: inp})[0][0]

            conf_thresh = 0.55
            cand_boxes = []
            for col in range(det_out.shape[1]):
                score = float(det_out[4, col])
                if score >= conf_thresh:
                    cx_pad, cy_pad, bw_pad, bh_pad = det_out[0:4, col]
                    cx_orig = (cx_pad - dx) / scale
                    cy_orig = (cy_pad - dy) / scale
                    bw_orig = bw_pad / scale
                    bh_orig = bh_pad / scale

                    aspect = bw_orig / max(1.0, bh_orig)
                    if aspect < 0.9 or aspect > 6.0:
                        continue
                    if bw_orig > 0.95 * vw or bh_orig > 0.85 * vh:
                        continue
                    if bw_orig < 20 or bh_orig < 10:
                        continue

                    local_x1 = max(0, int(cx_orig - bw_orig / 2))
                    local_y1 = max(0, int(cy_orig - bh_orig / 2))
                    local_x2 = min(vw, int(cx_orig + bw_orig / 2))
                    local_y2 = min(vh, int(cy_orig + bh_orig / 2))

                    orig_x1 = min(w, max(0, vx1 + local_x1))
                    orig_y1 = min(h, max(0, vy1 + local_y1))
                    orig_x2 = min(w, max(0, vx1 + local_x2))
                    orig_y2 = min(h, max(0, vy1 + local_y2))
                    cand_boxes.append((orig_x1, orig_y1, orig_x2, orig_y2, score, v_det))

            if cand_boxes:
                cv_boxes = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in cand_boxes]
                scores = [b[4] for b in cand_boxes]
                indices = cv2.dnn.NMSBoxes(cv_boxes, scores, conf_thresh, 0.45)
                for idx in (indices.flatten() if len(indices) > 0 else []):
                    frame_plate_boxes.append(cand_boxes[idx])

        stage1_latencies.append((time.perf_counter() - t1) * 1000.0)
        total_plates_detected += len(frame_plate_boxes)

        # -------------------------------------------------------------
        # Stage 2: Agnostic Preprocessing, OCR & Positional Repair
        # -------------------------------------------------------------
        t2 = time.perf_counter()
        for px1, py1, px2, py2, p_score, v_det in frame_plate_boxes:
            track_id = f"demo_{v_det.vehicle_class}_{v_idx}"
            unique_tracks.add(track_id)

            pad_x1, pad_y1, pad_x2, pad_y2 = pad_plate_bbox(
                [px1, py1, px2, py2],
                frame.shape[:2],
                pad_w_pct=0.08,
                pad_h_pct=0.05,
            )
            crop = frame[pad_y1:pad_y2, pad_x1:pad_x2]
            if crop.size == 0 or not is_plate_like_crop(crop):
                continue

            # Run dual-pass OCR
            raw_text, ocr_conf, ocr_engine_used = run_dual_pass_ocr(crop)
            if raw_text:
                total_ocr_reads += 1
                repaired, rule50_conf, fmt_meta = correct_indian_plate(raw_text)

                track_voter.add_observation(
                    track_id=track_id,
                    plate_text=repaired or raw_text,
                    confidence=float(ocr_conf),
                    bbox=[px1, py1, px2, py2],
                    frame_ts=frame_ts,
                    frame_bgr=crop,
                )

                detections_log.append({
                    "frame": f_idx,
                    "timestamp_s": round(frame_ts, 2),
                    "vehicle_class": v_det.vehicle_class,
                    "vehicle_conf": round(float(v_det.confidence), 3),
                    "plate_score": round(p_score, 3),
                    "raw_ocr": raw_text,
                    "repaired_plate": repaired,
                    "is_valid": is_valid_indian_plate(repaired),
                    "format": fmt_meta.get("format_category") if isinstance(fmt_meta, dict) else str(fmt_meta),
                    "ocr_engine": ocr_engine_used,
                })

        stage2_latencies.append((time.perf_counter() - t2) * 1000.0)

    cap.release()

    # Collect Track Consensus
    consensus_results = {}
    for tid in unique_tracks:
        cons = track_voter.get_consensus(tid)
        if cons is not None:
            consensus_results[tid] = {
                "fused_plate": cons["fused_plate"],
                "confidence": round(cons["confidence"], 3),
                "agreement_rate": round(cons["agreement_rate"], 3),
                "format_category": cons["format_category"],
                "is_valid": cons["is_valid"],
                "action": cons["action"],
                "frame_count": cons["frame_count"],
            }

    summary = {
        "video": video_path.name,
        "frames_evaluated": frames_processed,
        "stage0_early_exits": stage0_early_exits,
        "early_exit_pct": round(stage0_early_exits / max(1, frames_processed) * 100, 1),
        "vehicles_detected": total_vehicles_seen,
        "plates_detected": total_plates_detected,
        "ocr_reads": total_ocr_reads,
        "unique_tracks": len(unique_tracks),
        "tracks_with_consensus": len(consensus_results),
        "consensus_plates": consensus_results,
        "avg_latency_ms": {
            "stage0_gatekeeper": round(float(np.mean(stage0_latencies)), 2) if stage0_latencies else 0.0,
            "stage1_plate_detector": round(float(np.mean(stage1_latencies)), 2) if stage1_latencies else 0.0,
            "stage2_ocr_and_voting": round(float(np.mean(stage2_latencies)), 2) if stage2_latencies else 0.0,
        },
        "sample_detections": detections_log[:15],
    }

    print("\n--- Summary for " + video_path.name + " ---")
    print(f"Frames: {frames_processed} | Stage 0 Early Exits: {stage0_early_exits} ({summary['early_exit_pct']}%)")
    print(f"Vehicles: {total_vehicles_seen} | Plates Detected: {total_plates_detected} | OCR Reads: {total_ocr_reads}")
    print(f"Consensus Plates: {list(consensus_results.values())}")
    print(f"Latencies: S0: {summary['avg_latency_ms']['stage0_gatekeeper']}ms | S1: {summary['avg_latency_ms']['stage1_plate_detector']}ms | S2: {summary['avg_latency_ms']['stage2_ocr_and_voting']}ms")
    return summary


def main():
    print("=" * 70)
    print("CAMPUS GATE ANPR DEMO VIDEO BENCHMARK")
    print("=" * 70)

    # Load Gatekeeper
    gatekeeper = VehicleGatekeeper()
    print("Loaded Stage 0 Vehicle Gatekeeper (UVH-26)")

    # Load Plate Detector
    det_path = WEIGHTS_DIR / "yolo11n_plate_detector_finetuned.onnx"
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    det_sess = ort.InferenceSession(str(det_path), opts, providers=["CPUExecutionProvider"])
    print(f"Loaded Stage 1 Plate Detector ({det_path.name})")

    all_results = {}
    for vpath in DEMO_VIDEOS:
        all_results[vpath.name] = evaluate_video(vpath, gatekeeper, det_sess)

    with open(OUTPUT_METRICS, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print("\n" + "=" * 70)
    print(f"Benchmark results saved to: {OUTPUT_METRICS}")
    print("=" * 70)


if __name__ == "__main__":
    main()
