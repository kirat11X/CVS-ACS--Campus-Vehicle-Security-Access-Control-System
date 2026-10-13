from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from backend.app.models.enums import ObservationSource, ObservedVehicleType, ObservationDirection

class GateSummary(BaseModel):
    id: str
    name: str

class PlateObservation(BaseModel):
    raw: Optional[str] = None
    normalized: Optional[str] = None
    confidence: Optional[float] = None

class VehicleTypeObservation(BaseModel):
    type: ObservedVehicleType
    confidence: Optional[float] = None

class ObservationCreate(BaseModel):
    gate_id: str = Field(..., description="Gate where observation occurred")
    camera_id: Optional[str] = Field(None, description="Camera identifier")
    observed_at: Optional[datetime] = Field(None, description="Timestamp of observation")
    source: ObservationSource = Field(default=ObservationSource.FRIGATE, description="Sensor/ingestion source")
    source_event_id: Optional[str] = Field(None, description="Source event or tracked object ID")
    raw_plate: Optional[str] = Field(None, description="Raw plate string detected by OCR/LPR")
    plate_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="LPR detection confidence")
    vehicle_type: ObservedVehicleType = Field(default=ObservedVehicleType.UNKNOWN, description="Observed physical vehicle type")
    vehicle_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Vehicle classification confidence")
    direction: ObservationDirection = Field(default=ObservationDirection.UNKNOWN, description="Observed travel direction")
    metadata_payload: Optional[Dict[str, Any]] = Field(None, description="Raw metadata payload or snapshot info")

class ObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gate: GateSummary
    camera_id: Optional[str]
    observed_at: datetime
    source: ObservationSource
    source_event_id: Optional[str]
    plate: PlateObservation
    vehicle_observation: VehicleTypeObservation
    direction: ObservationDirection
    metadata_payload: Optional[Dict[str, Any]] = None
    created_at: datetime

    @classmethod
    def from_orm_model(cls, obs) -> "ObservationResponse":
        return cls(
            id=obs.id,
            gate=GateSummary(
                id=obs.gate_id,
                name=obs.gate.name if obs.gate else obs.gate_id
            ),
            camera_id=obs.camera_id,
            observed_at=obs.observed_at,
            source=obs.source,
            source_event_id=obs.source_event_id,
            plate=PlateObservation(
                raw=obs.raw_plate,
                normalized=obs.normalized_plate,
                confidence=obs.plate_confidence
            ),
            vehicle_observation=VehicleTypeObservation(
                type=obs.vehicle_type,
                confidence=obs.vehicle_confidence
            ),
            direction=obs.direction,
            metadata_payload=obs.metadata_payload,
            created_at=obs.created_at
        )
