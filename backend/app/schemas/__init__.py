from backend.app.schemas.vehicle import (
    VehicleCreate,
    VehicleUpdate,
    VehicleSimpleResponse,
    OwnerContextResponse,
    ResidenceContextResponse,
    VehicleDetailResponse
)
from backend.app.schemas.gate import (
    GateCreate,
    GateUpdate,
    GateResponse
)
from backend.app.schemas.observation import (
    ObservationCreate,
    ObservationResponse,
    PlateObservation,
    VehicleTypeObservation,
    GateSummary
)

__all__ = [
    "VehicleCreate",
    "VehicleUpdate",
    "VehicleSimpleResponse",
    "OwnerContextResponse",
    "ResidenceContextResponse",
    "VehicleDetailResponse",
    "GateCreate",
    "GateUpdate",
    "GateResponse",
    "ObservationCreate",
    "ObservationResponse",
    "PlateObservation",
    "VehicleTypeObservation",
    "GateSummary"
]
