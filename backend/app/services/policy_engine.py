"""
Access Control Policy Engine (Roadmap Phase 5).

Pure business logic function: evaluate_access_policy(...) -> AccessDecisionResult.
Determines whether a vehicle observation, visitor, or delivery crossing is granted
access (ALLOW), flagged for human security inspection (REVIEW), or triggers an immediate
security alarm (ALERT).

Adheres to the architectural mandate that ML and deterministic policy tables only assist;
guards make all final gate actions and overrides.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from backend.app.models.base import utc_now
from backend.app.models.enums import ReasonCode, VehicleStatus, ScreeningVerdict

POLICY_VERSION: str = "1.0"
MIN_PLATE_CONFIDENCE_THRESHOLD: float = 0.70


@dataclass(frozen=True)
class AccessDecisionResult:
    """Immutable access policy evaluation outcome."""
    decision: str  # "ALLOW", "REVIEW", "ALERT"
    reason_code: str
    confidence: float
    policy_version: str = POLICY_VERSION
    timestamp: datetime = field(default_factory=utc_now)
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
            "policy_version": self.policy_version,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


def _is_truthy_owner(owner_status: Any) -> bool:
    if owner_status is None:
        return False
    if isinstance(owner_status, bool):
        return owner_status
    if isinstance(owner_status, str):
        return owner_status.strip().upper() in ("ACTIVE", "REGISTERED", "KNOWN", "TRUE", "1")
    if isinstance(owner_status, dict):
        return bool(owner_status.get("id") or owner_status.get("name") or owner_status.get("identifier"))
    return True


def _is_valid_visitor(visitor_status: Any) -> bool:
    if visitor_status is None:
        return False
    if isinstance(visitor_status, bool):
        return visitor_status
    if isinstance(visitor_status, str):
        return visitor_status.strip().upper() in ("ACTIVE", "VALID", "APPROVED", "TRUE", "1")
    if isinstance(visitor_status, dict):
        status = str(visitor_status.get("status") or "").upper()
        return status in ("ACTIVE", "VALID", "APPROVED") or bool(visitor_status.get("id"))
    return False


def evaluate_access_policy(
    vehicle_registration_status: Optional[Union[str, VehicleStatus]] = None,
    owner_status: Optional[Union[str, bool, Dict[str, Any]]] = None,
    plate_confidence: Optional[float] = None,
    visitor_status: Optional[Union[str, bool, Dict[str, Any]]] = None,
    delivery_item_screening_status: Optional[Union[str, ScreeningVerdict, Dict[str, Any], List[Any]]] = None,
    plate: Optional[str] = None,
    is_blacklisted: bool = False,
    is_stolen: bool = False,
    cargo_alerts: Optional[List[str]] = None,
    is_cargo_uncertain: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> AccessDecisionResult:
    """
    Pure deterministic access policy evaluation function.

    Rules Precedence:
    1. Blacklisted or stolen vehicle -> ALERT (ALERT_BLACKLISTED_VEHICLE)
    2. Cargo screening with restricted items -> ALERT (ALERT_RESTRICTED_ITEM)
    3. Cargo screening uncertain -> REVIEW (REVIEW_CARGO_SCREENING_UNCERTAIN)
    4. Unreadable plate or confidence < 0.70 -> REVIEW (REVIEW_UNREADABLE_PLATE / REVIEW_LOW_CONFIDENCE_PLATE)
    5. Unknown vehicle -> REVIEW (REVIEW_UNKNOWN_VEHICLE)
    6. Registered vehicle with known owner + confidence >= 0.70 + no cargo alerts -> ALLOW (ALLOW_REGISTERED_VEHICLE)
    7. Valid visitor pass + confidence >= 0.70 + no cargo alerts -> ALLOW (ALLOW_VISITOR)
    8. Expired registration -> REVIEW (REVIEW_EXPIRED_VEHICLE)
    """
    ctx: Dict[str, Any] = dict(context or {})
    ctx["plate"] = plate

    # Normalize vehicle registration status
    reg_str: Optional[str] = None
    if vehicle_registration_status is not None:
        if isinstance(vehicle_registration_status, VehicleStatus):
            reg_str = vehicle_registration_status.value
        else:
            reg_str = str(vehicle_registration_status).strip().upper()

    # Rule 1: Stolen or blacklisted vehicle -> ALERT
    if (
        is_blacklisted
        or is_stolen
        or reg_str in ("BLACKLISTED", "STOLEN", "SUSPENDED")
    ):
        return AccessDecisionResult(
            decision="ALERT",
            reason_code=ReasonCode.ALERT_BLACKLISTED_VEHICLE.value,
            confidence=1.0,
            policy_version=POLICY_VERSION,
            details={**ctx, "reg_status": reg_str, "is_blacklisted": is_blacklisted, "is_stolen": is_stolen},
        )

    # Inspect delivery / cargo status
    has_cargo_alert = bool(cargo_alerts)
    cargo_uncertain = is_cargo_uncertain

    if delivery_item_screening_status is not None:
        if isinstance(delivery_item_screening_status, ScreeningVerdict):
            if delivery_item_screening_status == ScreeningVerdict.ALERT:
                has_cargo_alert = True
            elif delivery_item_screening_status == ScreeningVerdict.REVIEW:
                cargo_uncertain = True
        elif isinstance(delivery_item_screening_status, str):
            status_upper = delivery_item_screening_status.strip().upper()
            if status_upper in ("ALERT", "RESTRICTED", "PROHIBITED"):
                has_cargo_alert = True
            elif status_upper in ("REVIEW", "UNCERTAIN", "AMBIGUOUS"):
                cargo_uncertain = True
        elif isinstance(delivery_item_screening_status, dict):
            verdict = str(delivery_item_screening_status.get("verdict") or "").upper()
            if verdict == "ALERT" or delivery_item_screening_status.get("has_alerts"):
                has_cargo_alert = True
            elif verdict == "REVIEW" or delivery_item_screening_status.get("is_uncertain"):
                cargo_uncertain = True
        elif isinstance(delivery_item_screening_status, list):
            for item in delivery_item_screening_status:
                v = item.get("verdict") if isinstance(item, dict) else str(item)
                if str(v).upper() == "ALERT":
                    has_cargo_alert = True
                elif str(v).upper() == "REVIEW":
                    cargo_uncertain = True

    # Rule 2: Cargo screening with restricted items -> ALERT
    if has_cargo_alert:
        return AccessDecisionResult(
            decision="ALERT",
            reason_code=ReasonCode.ALERT_RESTRICTED_ITEM.value,
            confidence=1.0,
            policy_version=POLICY_VERSION,
            details={**ctx, "cargo_alerts": cargo_alerts or ["RESTRICTED_ITEM"]},
        )

    # Rule 3: Cargo screening uncertain -> REVIEW
    if cargo_uncertain:
        return AccessDecisionResult(
            decision="REVIEW",
            reason_code=ReasonCode.REVIEW_CARGO_SCREENING_UNCERTAIN.value,
            confidence=plate_confidence if plate_confidence is not None else 0.5,
            policy_version=POLICY_VERSION,
            details={**ctx, "cargo_status": "UNCERTAIN"},
        )

    # Rule 4: Plate read with confidence < 0.70 or unreadable plate -> REVIEW
    if plate is None or str(plate).strip().upper() in ("", "UNKNOWN", "UNREADABLE", "NONE"):
        return AccessDecisionResult(
            decision="REVIEW",
            reason_code=ReasonCode.REVIEW_UNREADABLE_PLATE.value,
            confidence=0.0,
            policy_version=POLICY_VERSION,
            details={**ctx, "plate_confidence": plate_confidence},
        )

    if plate_confidence is None or plate_confidence < MIN_PLATE_CONFIDENCE_THRESHOLD:
        return AccessDecisionResult(
            decision="REVIEW",
            reason_code=ReasonCode.REVIEW_LOW_CONFIDENCE_PLATE.value,
            confidence=float(plate_confidence) if plate_confidence is not None else 0.0,
            policy_version=POLICY_VERSION,
            details={**ctx, "plate_confidence": plate_confidence, "threshold": MIN_PLATE_CONFIDENCE_THRESHOLD},
        )

    # Check expired status
    if reg_str == "EXPIRED":
        return AccessDecisionResult(
            decision="REVIEW",
            reason_code=ReasonCode.REVIEW_EXPIRED_VEHICLE.value,
            confidence=float(plate_confidence),
            policy_version=POLICY_VERSION,
            details={**ctx, "reg_status": reg_str},
        )

    # Rule 5 & 6: Vehicle Registration & Owner Status
    is_registered = reg_str in ("ACTIVE", "REGISTERED")
    has_known_owner = _is_truthy_owner(owner_status)

    if is_registered and has_known_owner:
        return AccessDecisionResult(
            decision="ALLOW",
            reason_code=ReasonCode.ALLOW_REGISTERED_VEHICLE.value,
            confidence=float(plate_confidence),
            policy_version=POLICY_VERSION,
            details={**ctx, "reg_status": reg_str, "owner": owner_status},
        )

    # Rule 7: Visitor pass check
    if _is_valid_visitor(visitor_status):
        return AccessDecisionResult(
            decision="ALLOW",
            reason_code=ReasonCode.ALLOW_VISITOR.value,
            confidence=float(plate_confidence),
            policy_version=POLICY_VERSION,
            details={**ctx, "visitor_status": visitor_status},
        )

    # Rule 5: Unknown vehicle -> REVIEW
    return AccessDecisionResult(
        decision="REVIEW",
        reason_code=ReasonCode.REVIEW_UNKNOWN_VEHICLE.value,
        confidence=float(plate_confidence),
        policy_version=POLICY_VERSION,
        details={**ctx, "reg_status": reg_str, "owner": owner_status},
    )
