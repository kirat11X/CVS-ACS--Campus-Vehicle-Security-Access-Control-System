import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Optional
import uuid
import cv2
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.config import BASE_DIR, MEDIA_ROOT
from backend.app.dependencies import CurrentUser, get_db, require_admin, require_staff
from backend.app.models.enums import GateStatus
from backend.app.models.gate import Gate
from backend.app.models.stream_setting import GateStreamSetting
from backend.app.schemas.stream_setting import (
    GateStreamConfigItem,
    GateStreamSettingsResponse,
    GateStreamSettingsUpdate,
    StreamTestRequest,
    StreamTestResponse,
)
from backend.app.workers.camera_stream_runner import camera_stream_manager

router = APIRouter(tags=["Gate Cameras & Stream Settings"])


@router.get("/gates/stream-settings", response_model=GateStreamSettingsResponse)
@router.get("/api/gates/stream-settings", response_model=GateStreamSettingsResponse)
def get_gate_stream_settings(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
) -> GateStreamSettingsResponse:
    """
    Returns current multi-gate stream configurations, effective adaptive FPS,
    and live camera worker telemetry.
    """
    telemetry = camera_stream_manager.get_telemetry()
    return GateStreamSettingsResponse(**telemetry)


@router.put("/gates/stream-settings", response_model=GateStreamSettingsResponse)
@router.put("/api/gates/stream-settings", response_model=GateStreamSettingsResponse)
def update_gate_stream_settings(
    payload: GateStreamSettingsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> GateStreamSettingsResponse:
    """
    Updates adaptive FPS budget and gate stream configurations (ADMIN only).
    Automatically seeds gate record if new gate ID is registered.
    """
    now = datetime.now(timezone.utc)

    # 1. Update total_fps_budget
    if payload.total_fps_budget is not None:
        db.query(GateStreamSetting).update({"total_fps_budget": payload.total_fps_budget})

    # 2. Update gate stream configs
    raw_updates = []
    if payload.gates:
        for item in payload.gates:
            gid = item.gate_id.strip().upper()
            if not gid:
                continue

            # Ensure Gate exists in database
            gate = db.get(Gate, gid)
            if not gate:
                gate_name = item.gate_name or f"Campus Gate {gid.replace('GATE_', '')}"
                gate = Gate(
                    id=gid,
                    name=gate_name,
                    location="Campus Perimeter Gate",
                    status=GateStatus.ACTIVE,
                    direction_capability="BIDIRECTIONAL",
                )
                db.add(gate)
                db.flush()

            stream_row = db.get(GateStreamSetting, gid)
            if not stream_row:
                stream_row = GateStreamSetting(
                    gate_id=gid,
                    enabled=item.enabled if item.enabled is not None else False,
                    ip_address=item.ip_address or "192.168.1.100",
                    port=item.port or 8080,
                    protocol=item.protocol or "http",
                    stream_path=item.stream_path or "/video",
                    custom_url=item.custom_url,
                    total_fps_budget=payload.total_fps_budget or camera_stream_manager.total_fps_budget,
                    created_at=now,
                    updated_at=now,
                )
                db.add(stream_row)
            else:
                if item.enabled is not None:
                    stream_row.enabled = item.enabled
                if item.ip_address is not None:
                    stream_row.ip_address = item.ip_address
                if item.port is not None:
                    stream_row.port = item.port
                if item.protocol is not None:
                    stream_row.protocol = item.protocol
                if item.stream_path is not None:
                    stream_row.stream_path = item.stream_path
                if item.custom_url is not None:
                    stream_row.custom_url = item.custom_url
                if payload.total_fps_budget is not None:
                    stream_row.total_fps_budget = payload.total_fps_budget
                stream_row.updated_at = now

            raw_updates.append({
                "gate_id": gid,
                "gate_name": gate.name,
                "enabled": stream_row.enabled,
                "ip_address": stream_row.ip_address,
                "port": stream_row.port,
                "protocol": stream_row.protocol,
                "stream_path": stream_row.stream_path,
                "custom_url": stream_row.custom_url,
            })

    db.commit()

    # Synchronize worker manager
    camera_stream_manager.update_settings(
        total_fps_budget=payload.total_fps_budget,
        gates_update=raw_updates,
    )

    telemetry = camera_stream_manager.get_telemetry()
    return GateStreamSettingsResponse(**telemetry)


@router.post("/gates/stream-settings/{gate_id}/test", response_model=StreamTestResponse)
@router.post("/api/gates/stream-settings/{gate_id}/test", response_model=StreamTestResponse)
def test_gate_stream_connection(
    gate_id: str,
    payload: Optional[StreamTestRequest] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> StreamTestResponse:
    """
    Tests TCP socket reachability and stream frame acquisition within 3 seconds (ADMIN only).
    """
    gid = gate_id.strip().upper()
    stream_row = db.get(GateStreamSetting, gid)

    host = (payload.ip_address if payload and payload.ip_address else None) or (stream_row.ip_address if stream_row else "192.168.1.100")
    port = (payload.port if payload and payload.port else None) or (stream_row.port if stream_row else 8080)
    protocol = (payload.protocol if payload and payload.protocol else None) or (stream_row.protocol if stream_row else "http")
    path = (payload.stream_path if payload and payload.stream_path else None) or (stream_row.stream_path if stream_row else "/video")
    custom_url = (payload.custom_url if payload and payload.custom_url is not None else None) or (stream_row.custom_url if stream_row else None)

    res = camera_stream_manager.test_connection(
        host=host,
        port=port,
        protocol=protocol,
        path=path,
        custom_url=custom_url,
    )
    res["gate_id"] = gid
    return StreamTestResponse(**res)


@router.post("/gates/stream-settings/{gate_id}/start", response_model=GateStreamSettingsResponse)
@router.post("/api/gates/stream-settings/{gate_id}/start", response_model=GateStreamSettingsResponse)
def start_gate_camera_stream(
    gate_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> GateStreamSettingsResponse:
    """
    Enables live stream worker for this gate and dynamically re-balances FPS budget (ADMIN only).
    """
    gid = gate_id.strip().upper()
    stream_row = db.get(GateStreamSetting, gid)
    if not stream_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate stream configuration for '{gid}' not found.",
        )
    stream_row.enabled = True
    stream_row.updated_at = datetime.now(timezone.utc)
    db.commit()

    camera_stream_manager.set_gate_enabled(gid, True)
    telemetry = camera_stream_manager.get_telemetry()
    return GateStreamSettingsResponse(**telemetry)


@router.post("/gates/stream-settings/{gate_id}/stop", response_model=GateStreamSettingsResponse)
@router.post("/api/gates/stream-settings/{gate_id}/stop", response_model=GateStreamSettingsResponse)
def stop_gate_camera_stream(
    gate_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> GateStreamSettingsResponse:
    """
    Disables live stream worker for this gate and re-allocates budget to remaining gates (ADMIN only).
    """
    gid = gate_id.strip().upper()
    stream_row = db.get(GateStreamSetting, gid)
    if not stream_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate stream configuration for '{gid}' not found.",
        )
    stream_row.enabled = False
    stream_row.updated_at = datetime.now(timezone.utc)
    db.commit()

    camera_stream_manager.set_gate_enabled(gid, False)
    telemetry = camera_stream_manager.get_telemetry()
    return GateStreamSettingsResponse(**telemetry)


@router.get("/gates/stream-settings/{gate_id}/live-frame")
@router.get("/api/gates/stream-settings/{gate_id}/live-frame")
def get_gate_live_frame(
    gate_id: str,
    user: CurrentUser = Depends(require_staff),
):
    """
    Returns the most recent live frame captured from the gate's camera stream as a JPEG image.
    Allows staff, guards, and admins to inspect the camera feed in real time.
    """
    gid = gate_id.strip().upper()
    frame = camera_stream_manager.get_latest_frame(gid)
    if frame is None or frame.size == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No live frame available for gate '{gid}'. The stream may be offline or initializing.",
        )
    ret, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to encode live frame.")
    return Response(
        content=buffer.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.post("/gates/stream-settings/{gate_id}/snapshot")
@router.post("/api/gates/stream-settings/{gate_id}/snapshot")
def capture_gate_snapshot(
    gate_id: str,
    user: CurrentUser = Depends(require_staff),
):
    """
    Captures and permanently stores a live camera snapshot from the specified gate.
    Saves to media/snapshots/ and data/rl_dataset/images/ for active learning and auditing.
    """
    gid = gate_id.strip().upper()
    frame = camera_stream_manager.get_latest_frame(gid)
    if frame is None or frame.size == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No live frame available for gate '{gid}'. Camera stream may be offline or initializing.",
        )

    now_ts = int(time.time())
    snap_id = f"manual_snap_{gid}_{now_ts}_{uuid.uuid4().hex[:6]}"
    filename = f"{snap_id}.jpg"

    # 1. Save to media/snapshots
    snap_dir = Path(MEDIA_ROOT) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / filename
    cv2.imwrite(str(snap_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

    # 2. Save to RL dataset storage (never purged)
    rl_dir = Path(BASE_DIR) / "data" / "rl_dataset" / "images"
    rl_dir.mkdir(parents=True, exist_ok=True)
    rl_path = rl_dir / filename
    cv2.imwrite(str(rl_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

    # 3. Log to manifest
    manifest_path = Path(BASE_DIR) / "data" / "rl_dataset" / "manifest.jsonl"
    record = {
        "id": snap_id,
        "gate_id": gid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "MANUAL_LIVE_SNAPSHOT",
        "captured_by": str(user.full_name),
        "image_path": f"data/rl_dataset/images/{filename}",
        "media_snapshot_url": f"/media/snapshots/{filename}",
    }
    try:
        with open(manifest_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return {
        "success": True,
        "gate_id": gid,
        "snapshot_id": snap_id,
        "filename": filename,
        "path": f"/media/snapshots/{filename}",
        "timestamp": record["timestamp"],
    }


@router.get("/gates/stream-settings/{gate_id}/mjpeg")
@router.get("/api/gates/stream-settings/{gate_id}/mjpeg")
async def stream_gate_mjpeg(
    gate_id: str,
    fps: float = Query(5.0, ge=1.0, le=15.0),
    user: CurrentUser = Depends(require_staff),
):
    """
    Streams live video from the gate camera as standard Motion-JPEG (MJPEG) over HTTP.
    Renders continuously in standard <img> elements without buffering.
    """
    gid = gate_id.strip().upper()

    async def mjpeg_generator():
        interval = 1.0 / max(1.0, fps)
        while True:
            frame = camera_stream_manager.get_latest_frame(gid)
            if frame is not None and frame.size > 0:
                ret, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ret:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                    )
            await asyncio.sleep(interval)

    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
