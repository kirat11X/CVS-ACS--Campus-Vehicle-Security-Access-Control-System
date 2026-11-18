from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

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
