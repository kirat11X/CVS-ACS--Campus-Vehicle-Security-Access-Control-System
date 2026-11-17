"""Simulated reviewer for the public pool (demo of the loop without a person).

For each selected public-pool frame it reveals the dataset's own human labels (kept apart in oracle_labels/) and
submits them through the review service, so the decision lands in the same audit log, marked source="oracle".
The model's boxes are never copied into labels: the approved boxes are the dataset's human boxes. These labels
carry no plate text, so text_status is "not_reviewed" and the frames never feed OCR training. The public labels
are assumed complete ("every plate boxed"); a frame they missed plates on would teach false negatives.
"""

from __future__ import annotations

from pathlib import Path

from anpr_hitl.labels import clip_xyxy, read_yolo_labels, yolo_to_xyxy
from anpr_hitl.review.service import ReviewedBox, ReviewService
from anpr_hitl.store import Store

ORACLE_REVIEWER = "oracle:public-dataset-labels"


def oracle_label_path(store: Store, frame_id: str) -> Path:
    if not frame_id.startswith("public/"):
        raise ValueError(f"{frame_id} is not a public-pool frame")
    return store.bootstrap_dir / "detector" / "pool" / "oracle_labels" / f"{frame_id.removeprefix('public/')}.txt"


def oracle_review(service: ReviewService, round_id: str) -> dict:
    store = service.store
    preds = service.predictions(round_id)
    counts = {"reviewed": 0, "model_correct": 0, "skipped_not_public": 0, "boxes": 0}
    for item in service.pending(round_id):
        if not item.get("oracle"):
            counts["skipped_not_public"] += 1
            continue
        pred = preds[item["frame_id"]]
        w, h = pred["width"], pred["height"]
        boxes = []
        for _, cx, cy, bw, bh in read_yolo_labels(oracle_label_path(store, item["frame_id"])):
            x1, y1, x2, y2 = clip_xyxy(yolo_to_xyxy(cx, cy, bw, bh, w, h), w, h)
            if x2 - x1 >= 1 and y2 - y1 >= 1:
                boxes.append(ReviewedBox((x1, y1, x2, y2), "", "not_reviewed"))
        entry = service.submit(round_id, item["item_id"], "correct", boxes, all_plates_boxed=True,
                               reviewer=ORACLE_REVIEWER, source="oracle", notes="simulated reviewer (public labels)")
        counts["reviewed"] += 1
        counts["model_correct"] += bool(entry["model_correct"])
        counts["boxes"] += len(boxes)
    return counts
