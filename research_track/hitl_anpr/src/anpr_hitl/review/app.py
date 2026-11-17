"""Streamlit review app. Start it with `anpr review-app --round <id>` (binds to 127.0.0.1 only, no telemetry).

One queued frame at a time: the model's proposals are drawn in yellow and listed with their plate crops. The
reviewer keeps or drops each box, fixes coordinates and plate text, adds missed plates, confirms that every plate
in the frame is boxed, and then accepts, saves corrections, rejects the frame or skips it. Every submission goes
through ReviewService into the hash-chained audit log. Audit items look exactly like the others.
"""

from __future__ import annotations

import argparse
import os
import time

import cv2
import streamlit as st

from anpr_hitl.config import load_config
from anpr_hitl.plates import normalize_plate
from anpr_hitl.review.service import ReviewedBox, ReviewError, ReviewService
from anpr_hitl.store import Store

YELLOW, GREEN = (0, 215, 255), (60, 200, 60)


def _args():
    p = argparse.ArgumentParser()
    p.add_argument("--round", default=os.environ.get("ANPR_REVIEW_ROUND"))
    p.add_argument("--config", default=os.environ.get("ANPR_CONFIG"))
    p.add_argument("--data-root", default=os.environ.get("ANPR_DATA_ROOT"))
    args, _ = p.parse_known_args()
    if not args.round:
        raise SystemExit("--round (or ANPR_REVIEW_ROUND) is required")
    return args


def _marked_text(text: str, low: list[int]) -> str:
    """Plate text with low-confidence characters wrapped in [ ] for the reviewer."""
    return "".join(f"[{c}]" if i in low else c for i, c in enumerate(text)) or "(no read)"


def _draw(img, boxes):
    out = img.copy()
    scale = max(1, round(max(img.shape[:2]) / 1000))
    for b in boxes:
        if not b["keep"]:
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in b["xyxy"])
        colour = YELLOW if b["origin"] == "model" else GREEN
        cv2.rectangle(out, (x1, y1), (x2, y2), colour, 2 * scale)
        cv2.putText(out, b["label"], (x1, max(0, y1 - 6 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, colour,
                    2 * scale)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def main():
    args = _args()
    cfg = load_config(args.config, data_root=args.data_root)
    store = Store(cfg.data_root)
    svc = ReviewService(store, cfg)
    st.set_page_config(page_title=f"ANPR review {args.round}", layout="wide")

    reviewer = st.sidebar.text_input("Reviewer name", value=os.environ.get(cfg.review.reviewer_env, ""))
    summary = svc.summary(args.round)
    done = summary["queued"] - summary["pending"]
    st.sidebar.progress(done / max(summary["queued"], 1), text=f"{done} of {summary['queued']} reviewed")
    st.sidebar.write({k: summary[k] for k in ("accept", "correct", "reject", "skip", "incomplete_frames")})
    st.sidebar.caption("Plates are personal data: do not screenshot or share frames outside this tool.")

    pending = svc.pending(args.round)
    if not pending:
        st.success("Queue complete. Run `anpr run-round --round %s` to continue the round." % args.round)
        return
    position = st.sidebar.number_input("Item", 1, len(pending), 1) - 1
    item = pending[position]
    item_id = item["item_id"]
    pred = svc.predictions(args.round)[item["frame_id"]]
    started = st.session_state.setdefault(f"t:{item_id}", time.time())
    key = f"boxes:{item_id}"
    if key not in st.session_state:
        st.session_state[key] = [
            {"label": p["box_id"], "origin": "model", "keep": True, "xyxy": list(p["xyxy"]), "text": p["ocr"]["text"],
             "status": "read", "proposal": p}
            for p in pred["boxes"]]
    boxes = st.session_state[key]

    img = cv2.imread(str(store.root / item["path"]))
    h, w = img.shape[:2]
    st.subheader(f"{item['frame_id']}  ({w}x{h})")
    st.caption("Why this frame: " + (", ".join(item["reasons"]) or "random sample")
               + f" | frame flags: {', '.join(pred['flags']) or 'none'}")
    st.image(_draw(img, boxes), width="stretch")

    for i, b in enumerate(boxes):
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 3, 3])
            p = b.get("proposal")
            crop = store.round_dir(args.round) / p["crop"] if p and p.get("crop") else None
            if crop and crop.is_file():
                c1.image(str(crop), width="stretch")
            b["keep"] = c1.checkbox(f"keep {b['label']}", value=b["keep"], key=f"keep:{item_id}:{i}")
            if p:
                ocr = p["ocr"]
                c2.markdown(f"**model read** `{_marked_text(ocr['text'], p['check']['low_conf_positions'])}`  "
                            f"(OCR conf {ocr['conf']:.2f}, box conf {p['conf']:.2f})")
                if p["check"]["suggestions"]:
                    c2.caption("possible confusions (hint only, never applied): "
                               + ", ".join(p["check"]["suggestions"][:4]))
                if p.get("track", {}).get("disagreement"):
                    c2.caption(f"track reads disagree; most common: {p['track']['consensus']}")
                if not p["check"]["regex_valid"]:
                    c2.caption("read does not match SS NN X(XX) NNNN or NN BH NNNN XX")
            b["text"] = c2.text_input("plate text", value=b["text"], key=f"text:{item_id}:{i}").upper()
            b["status"] = c2.radio("text", ["read", "unreadable"], index=0 if b["status"] == "read" else 1,
                                   key=f"status:{item_id}:{i}", horizontal=True, label_visibility="collapsed")
            with c3.expander("box coordinates (pixels)"):
                cols = st.columns(4)
                for j, name in enumerate(("x1", "y1", "x2", "y2")):
                    limit = float(w if j % 2 == 0 else h)
                    b["xyxy"][j] = cols[j].number_input(name, 0.0, limit, float(b["xyxy"][j]), 1.0,
                                                        key=f"{name}:{item_id}:{i}")

    with st.expander("Add a plate the model missed"):
        cols = st.columns(5)
        new = [cols[j].number_input(n, 0.0, float(w if j % 2 == 0 else h), 0.0, 1.0, key=f"new{n}:{item_id}")
               for j, n in enumerate(("x1", "y1", "x2", "y2"))]
        new_text = cols[4].text_input("text", key=f"newtext:{item_id}").upper()
        if st.button("Add box"):
            boxes.append({"label": f"n{len(boxes)}", "origin": "human", "keep": True, "xyxy": new, "text": new_text,
                          "status": "read" if new_text else "unreadable", "proposal": None})
            st.rerun()

    complete = st.checkbox("Every plate visible in this frame is boxed (required for the frame to be used in training)",
                           key=f"complete:{item_id}")
    kept = [b for b in boxes if b["keep"]]
    unchanged = all(b["origin"] == "model" for b in kept) and len(kept) == len(pred["boxes"]) and all(
        b["xyxy"] == list(b["proposal"]["xyxy"]) and normalize_plate(b["text"]) == b["proposal"]["ocr"]["text"]
        and b["status"] == "read" for b in kept)
    notes = st.text_input("notes (optional, no plate text)", key=f"notes:{item_id}")
    a, c, r, s = st.columns(4)
    decision = None
    if a.button("Accept as proposed", disabled=not unchanged, type="primary", width="stretch"):
        decision = "accept"
    if c.button("Save corrections", disabled=unchanged, width="stretch"):
        decision = "correct"
    if r.button("Reject frame (unusable)", width="stretch"):
        decision = "reject"
    if s.button("Skip for now", width="stretch"):
        decision = "skip"
    if decision:
        try:
            svc.submit(args.round, item_id, decision,
                       [ReviewedBox(tuple(b["xyxy"]), b["text"], b["status"]) for b in kept],
                       all_plates_boxed=complete, reviewer=svc.reviewer_name(reviewer), source="human",
                       seconds=round(time.time() - started, 1), notes=notes)
        except ReviewError as exc:
            st.error(str(exc))
        else:
            for k in [k for k in st.session_state if str(k).endswith(item_id) or f":{item_id}:" in str(k)]:
                del st.session_state[k]
            st.rerun()


if __name__ == "__main__":
    main()
