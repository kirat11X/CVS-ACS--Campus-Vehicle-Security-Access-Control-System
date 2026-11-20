"""
Visitor Management & Overstay Alert Service.
===========================================
Tracks campus visitor entries, allotted visiting hours, and automatically
generates Security Alerts when a visitor remains on campus beyond their
allotted duration.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.app.models.base import utc_now
from backend.app.models.enums import AlertSeverity, AlertStatus, GateDirection, ObservationSource
from backend.app.models.gate import EntryExitLog, SecurityAlert
from backend.app.models.observation import ObservationEvent

logger = logging.getLogger("campus_security.visitor_service")


def check_and_trigger_visitor_overstay_alerts(db: Session) -> List[Dict[str, Any]]:
    """
    Scans for visitor observations that have exceeded their allotted visitor hours
    without a recorded EXIT movement, and raises High-Severity SecurityAlerts.
    """
    now = utc_now()
    alerts_created: List[Dict[str, Any]] = []

    try:
        # Fetch observations with visitor_info in metadata
        visitor_observations = (
            db.query(ObservationEvent)
            .filter(ObservationEvent.metadata_payload.isnot(None))
            .order_by(ObservationEvent.observed_at.desc())
            .limit(200)
            .all()
        )

        for obs in visitor_observations:
            meta = dict(obs.metadata_payload or {})
            v_info = meta.get("visitor_info")
            if not isinstance(v_info, dict) or not v_info.get("is_visitor"):
                continue

            exp_str = v_info.get("expected_exit_time")
            if not exp_str:
                continue

            try:
                exp_dt = datetime.fromisoformat(exp_str)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            # Check if overdue
            if now <= exp_dt:
                continue

            # Check if vehicle has already exited
            plate = obs.normalized_plate
            exit_logged = (
                db.query(EntryExitLog)
                .filter(
                    EntryExitLog.normalized_plate == plate,
                    EntryExitLog.direction == GateDirection.EXIT,
                    EntryExitLog.timestamp >= obs.observed_at,
                )
                .first()
            )
            if exit_logged:
                # Already exited campus
                continue

            # Check if a pending alert already exists
            alert_title = f"Visitor Overstay Alert: {plate} ({v_info.get('visitor_name', 'Visitor')})"
            existing_alert = (
                db.query(SecurityAlert)
                .filter(
                    SecurityAlert.title == alert_title,
                    SecurityAlert.status == AlertStatus.PENDING,
                )
                .first()
            )
            if existing_alert:
                continue

            overstay_mins = int((now - exp_dt).total_seconds() / 60)
            overstay_desc = (
                f"Visitor '{v_info.get('visitor_name', 'Visitor')}' "
                f"(Mobile: {v_info.get('visitor_phone', 'Not provided')}) "
                f"visiting '{v_info.get('place_of_visit', 'Campus')}' "
                f"[Reference: {v_info.get('reference_person') or 'None'}] "
                f"entered at {obs.gate_id} with {v_info.get('allowed_duration_hours', 2)} hours allotted. "
                f"Expected exit was {exp_dt.strftime('%H:%M %d-%b')}. "
                f"Vehicle has overstayed by {overstay_mins} minutes and is still inside campus perimeter."
            )

            # Find matching movement log if possible
            matching_log = (
                db.query(EntryExitLog)
                .filter(EntryExitLog.observation_id == obs.id)
                .first()
            )

            new_alert = SecurityAlert(
                gate_id=obs.gate_id,
                log_id=matching_log.id if matching_log else None,
                severity=AlertSeverity.HIGH,
                status=AlertStatus.PENDING,
                title=alert_title,
                description=overstay_desc,
            )
            db.add(new_alert)

            # Mark alert in observation metadata
            v_info["overstay_alert"] = True
            v_info["alert_raised_at"] = now.isoformat()
            meta["visitor_info"] = v_info
            obs.metadata_payload = meta
            flag_modified(obs, "metadata_payload")

            alerts_created.append({
                "observation_id": str(obs.id),
                "plate": plate,
                "visitor_name": v_info.get("visitor_name"),
                "expected_exit_time": exp_str,
                "overstay_minutes": overstay_mins,
            })

        if alerts_created:
            db.commit()
            logger.warning("Created %d visitor overstay alerts: %s", len(alerts_created), alerts_created)

    except Exception as exc:
        logger.error("Failed checking visitor overstay alerts: %s", exc)

    return alerts_created


def get_active_campus_visitors(db: Session) -> List[Dict[str, Any]]:
    """Returns active visitor passes and their remaining/overstay duration."""
    now = utc_now()
    results: List[Dict[str, Any]] = []

    try:
        visitor_observations = (
            db.query(ObservationEvent)
            .filter(ObservationEvent.metadata_payload.isnot(None))
            .order_by(ObservationEvent.observed_at.desc())
            .limit(100)
            .all()
        )

        for obs in visitor_observations:
            meta = dict(obs.metadata_payload or {})
            v_info = meta.get("visitor_info")
            if not isinstance(v_info, dict) or not v_info.get("is_visitor"):
                continue

            plate = obs.normalized_plate
            exit_logged = (
                db.query(EntryExitLog)
                .filter(
                    EntryExitLog.normalized_plate == plate,
                    EntryExitLog.direction == GateDirection.EXIT,
                    EntryExitLog.timestamp >= obs.observed_at,
                )
                .first()
            )
            if exit_logged:
                continue

            exp_str = v_info.get("expected_exit_time")
            is_overstay = False
            remaining_mins = 0
            if exp_str:
                try:
                    exp_dt = datetime.fromisoformat(exp_str)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    diff = (exp_dt - now).total_seconds() / 60
                    if diff < 0:
                        is_overstay = True
                        remaining_mins = int(abs(diff))
                    else:
                        remaining_mins = int(diff)
                except Exception:
                    pass

            results.append({
                "observation_id": str(obs.id),
                "plate": plate,
                "gate_id": obs.gate_id,
                "observed_at": obs.observed_at.isoformat(),
                "vehicle_type": obs.vehicle_type.value,
                "visitor_name": v_info.get("visitor_name"),
                "visitor_phone": v_info.get("visitor_phone"),
                "place_of_visit": v_info.get("place_of_visit"),
                "reference_person": v_info.get("reference_person"),
                "allowed_duration_hours": v_info.get("allowed_duration_hours"),
                "expected_exit_time": exp_str,
                "is_overstay": is_overstay,
                "minutes_relative": remaining_mins,
            })
    except Exception as exc:
        logger.error("Failed fetching active campus visitors: %s", exc)

    return results
