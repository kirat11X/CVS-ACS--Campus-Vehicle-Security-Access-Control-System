"""Turn a round's tracked plate reads into campus-backend observation payloads: proposals only.

The pipeline decides nothing. One payload per video track goes to the backend's POST /observations (admin token)
with source "OTHER" and metadata {"proposal": true, ...}; the backend's deterministic rules decide what an
observation means, and nothing here or there actuates a barrier. The default is a dry run: payloads are written to
the private data root and the console shows counts and masked plate text only.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections import defaultdict

from anpr_hitl.config import Config
from anpr_hitl.store import Store, read_jsonl, write_jsonl

TOKEN_ENV = "ANPR_BACKEND_TOKEN"
MAX_PLATE_LEN = 30          # backend ObservationCreate.raw_plate
MAX_EVENT_ID_LEN = 100      # backend ObservationCreate.source_event_id


def mask_plate(text: str) -> str:
    """For console output: first two characters (state code) and the last two, the rest hidden."""
    if len(text) <= 4:
        return text[:2] + "*" * max(len(text) - 2, 0)
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def build_proposals(rows: list[dict], gate_id: str) -> list[dict]:
    tracks: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("kind") != "video":
            continue  # public still images are not observations of anything
        for b in r["boxes"]:
            if b.get("track_id") is not None:
                tracks[(r["video_id"], b["track_id"])].append({**b, "model": r.get("model") or {}})
    out = []
    for (video_id, track_id), boxes in sorted(tracks.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        consensus = (boxes[0].get("track") or {}).get("consensus") or ""
        same = [b for b in boxes if b["ocr"]["text"] == consensus]
        if not consensus or not same:
            continue
        best = max(same, key=lambda b: b["ocr"]["conf"])
        model = best["model"]
        event_id = f"hitl:{video_id}:{track_id}:{model.get('version') or model.get('weights_sha256', '')[:12]}"
        out.append({
            "gate_id": gate_id, "source": "OTHER", "source_event_id": event_id[:MAX_EVENT_ID_LEN],
            "raw_plate": consensus[:MAX_PLATE_LEN], "plate_confidence": round(float(best["ocr"]["conf"]), 4),
            "metadata_payload": {
                "proposal": True, "pipeline": "anpr_hitl", "model_version": model.get("version"),
                "weights_sha256": (model.get("weights_sha256") or "")[:16],
                "detector_conf": round(max(b["conf"] for b in boxes), 4), "ocr_engine": best["ocr"]["engine"],
                "regex_valid": best["check"]["regex_valid"], "format": best["check"]["format"],
                "flags": sorted({f for b in boxes for f in b["check"]["flags"]}),
                "track_reads": (best.get("track") or {}).get("reads"),
                "track_agreement": (best.get("track") or {}).get("agreement"),
            },
        })
    return out


def propose(store: Store, cfg: Config, round_id: str, gate_id: str, send: bool = False,
            api_url: str | None = None) -> dict:
    rows = read_jsonl(store.predictions_dir(round_id) / "predictions.jsonl")
    payloads = build_proposals(rows, gate_id)
    path = store.round_dir(round_id) / "proposals.jsonl"
    write_jsonl(path, payloads)
    report = {"round": round_id, "proposals": len(payloads), "written_to": str(path), "dry_run": not send,
              "examples": [{"plate": mask_plate(p["raw_plate"]), "confidence": p["plate_confidence"],
                            "regex_valid": p["metadata_payload"]["regex_valid"]} for p in payloads[:5]]}
    if not send:
        return report
    token = os.environ.get(TOKEN_ENV)
    if not api_url or not token:
        raise SystemExit(f"--send needs --api-url and ${TOKEN_ENV} (an admin bearer token)")
    statuses = defaultdict(int)
    for p in payloads:
        req = urllib.request.Request(f"{api_url.rstrip('/')}/observations", data=json.dumps(p).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                statuses[resp.status] += 1
        except urllib.error.HTTPError as exc:
            statuses[exc.code] += 1
    report["http_status_counts"] = dict(statuses)
    return report
