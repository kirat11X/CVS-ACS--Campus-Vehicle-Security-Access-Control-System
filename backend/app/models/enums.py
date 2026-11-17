import enum

class PersonType(str, enum.Enum):
    STUDENT = "STUDENT"
    FACULTY = "FACULTY"
    STAFF = "STAFF"
    RESIDENT = "RESIDENT"

class ResidenceType(str, enum.Enum):
    HOSTELLER = "HOSTELLER"
    DAY_SCHOLAR = "DAY_SCHOLAR"
    OFF_CAMPUS = "OFF_CAMPUS"
    UNKNOWN = "UNKNOWN"

class VehicleCategory(str, enum.Enum):
    STUDENT = "STUDENT"
    FACULTY = "FACULTY"
    STAFF = "STAFF"
    RESIDENT = "RESIDENT"
    VISITOR = "VISITOR"
    DELIVERY = "DELIVERY"
    RIDE_HAILING = "RIDE_HAILING"
    UNKNOWN = "UNKNOWN"

class VehicleStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    BLACKLISTED = "BLACKLISTED"

class AccessState(str, enum.Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    REVIEW = "REVIEW"
    EXPIRED = "EXPIRED"

class GateDirection(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"

class GateStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    LOCKED = "LOCKED"
    OFFLINE = "OFFLINE"
    INACTIVE = "INACTIVE"

class ObservationSource(str, enum.Enum):
    FRIGATE = "FRIGATE"
    MANUAL = "MANUAL"
    OTHER = "OTHER"

class ObservedVehicleType(str, enum.Enum):
    CAR = "CAR"
    MOTORCYCLE = "MOTORCYCLE"
    BUS = "BUS"
    TRUCK = "TRUCK"
    BICYCLE = "BICYCLE"
    UNKNOWN = "UNKNOWN"

class ObservationDirection(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    UNKNOWN = "UNKNOWN"

class PlatformType(str, enum.Enum):
    ZOMATO = "ZOMATO"
    SWIGGY = "SWIGGY"
    UBER_EATS = "UBER_EATS"
    AMAZON = "AMAZON"
    UBER = "UBER"
    BLINKIT = "BLINKIT"
    ZEPTO = "ZEPTO"
    INSTAMART = "INSTAMART"
    RELIANCE = "RELIANCE"
    OTHER = "OTHER"

class OrderStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    OCR_PROCESSED = "OCR_PROCESSED"
    VERIFIED = "VERIFIED"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    REVIEW = "REVIEW"

class AlertSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class AlertStatus(str, enum.Enum):
    PENDING = "PENDING"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"

class ReasonCode(str, enum.Enum):
    # Phase 5 Policy Engine Reason Codes
    ALLOW_REGISTERED_VEHICLE = "ALLOW_REGISTERED_VEHICLE"
    REVIEW_LOW_CONFIDENCE_PLATE = "REVIEW_LOW_CONFIDENCE_PLATE"
    REVIEW_UNREADABLE_PLATE = "REVIEW_UNREADABLE_PLATE"
    REVIEW_UNKNOWN_VEHICLE = "REVIEW_UNKNOWN_VEHICLE"
    ALERT_RESTRICTED_ITEM = "ALERT_RESTRICTED_ITEM"
    REVIEW_CARGO_SCREENING_UNCERTAIN = "REVIEW_CARGO_SCREENING_UNCERTAIN"
    ALERT_BLACKLISTED_VEHICLE = "ALERT_BLACKLISTED_VEHICLE"
    ALLOW_VISITOR = "ALLOW_VISITOR"
    REVIEW_EXPIRED_VEHICLE = "REVIEW_EXPIRED_VEHICLE"

    # Canonical registry & access codes
    VEHICLE_REGISTERED = "VEHICLE_REGISTERED"
    VEHICLE_NOT_REGISTERED = "VEHICLE_NOT_REGISTERED"
    VEHICLE_EXPIRED = "VEHICLE_EXPIRED"
    VEHICLE_SUSPENDED = "VEHICLE_SUSPENDED"
    VEHICLE_BLACKLISTED = "VEHICLE_BLACKLISTED"
    VISITOR_VALID = "VISITOR_VALID"
    VISITOR_EXPIRED = "VISITOR_EXPIRED"
    VISITOR_GATE_NOT_ALLOWED = "VISITOR_GATE_NOT_ALLOWED"
    ORDER_VERIFIED = "ORDER_VERIFIED"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ORDER_ALREADY_USED = "ORDER_ALREADY_USED"
    PLATE_MISMATCH = "PLATE_MISMATCH"
    LOW_LPR_CONFIDENCE = "LOW_LPR_CONFIDENCE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    SUSPICIOUS_BEHAVIOR = "SUSPICIOUS_BEHAVIOR"

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    GUARD = "GUARD"

class ResolutionOutcome(str, enum.Enum):
    VEHICLE_CONFIRMED = "VEHICLE_CONFIRMED"
    NONE_OF_THESE = "NONE_OF_THESE"

class FeedEventKind(str, enum.Enum):
    OBSERVATION_CREATED = "OBSERVATION_CREATED"
    OBSERVATION_UPDATED = "OBSERVATION_UPDATED"
    RESOLUTION_ADDED = "RESOLUTION_ADDED"
    REGISTRY_UPDATED = "REGISTRY_UPDATED"
    MOVEMENT_UPDATED = "MOVEMENT_UPDATED"

class LinkStatus(str, enum.Enum):
    """Computed registry linkage of an observation (not persisted)."""
    LINKED = "LINKED"
    LINKED_INACTIVE = "LINKED_INACTIVE"
    NOT_LINKED = "NOT_LINKED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NO_PLATE = "NO_PLATE"

class LinkBasis(str, enum.Enum):
    """How a LINKED / LINKED_INACTIVE observation was associated (not persisted)."""
    EXACT_PLATE = "EXACT_PLATE"
    GUARD_CONFIRMED = "GUARD_CONFIRMED"

class LaneRole(str, enum.Enum):
    """Declared by an administrator per camera. Configuration, not inference."""
    ENTRY_LANE = "ENTRY_LANE"
    EXIT_LANE = "EXIT_LANE"
    BIDIRECTIONAL = "BIDIRECTIONAL"

class DirectionMethod(str, enum.Enum):
    CAMERA_ROLE = "CAMERA_ROLE"
    ZONE_ORDER = "ZONE_ORDER"
    GUARD_CONFIRMED = "GUARD_CONFIRMED"
    NONE = "NONE"

class LogPlateSource(str, enum.Enum):
    """Where a movement log row's plate came from."""
    OBSERVATION = "OBSERVATION"
    GUARD_CORRECTION = "GUARD_CORRECTION"

class LinkMethod(str, enum.Enum):
    GUARD_VERIFIED_ID = "GUARD_VERIFIED_ID"
    ADMIN = "ADMIN"

class PresenceStatus(str, enum.Enum):
    """Derived on read from the movement log (not persisted)."""
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    UNKNOWN = "UNKNOWN"

class ScreeningVerdict(str, enum.Enum):
    """Deterministic policy-table outcome for an invoice line (Phase 7). Never a gate action."""
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    ALERT = "ALERT"

class GuardDecision(str, enum.Enum):
    """What the guard decided about a screened delivery. The guard decides; software never blocks."""
    CLEARED = "CLEARED"
    HELD = "HELD"
    ESCALATED = "ESCALATED"

class DeliverySource(str, enum.Enum):
    """How an invoice reached the server."""
    LOCAL_INTAKE = "LOCAL_INTAKE"
    WHATSAPP = "WHATSAPP"
    CONSOLE = "CONSOLE"
