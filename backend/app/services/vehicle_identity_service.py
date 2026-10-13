from typing import Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.app.models.vehicle import Vehicle
from backend.app.models.identity import VehicleOwner
from backend.app.models.enums import VehicleStatus
from backend.app.services.plate_normalizer import normalize_plate

class VehicleIdentityService:
    """
    Authoritative intelligence service for resolving vehicles to their institutional
    identities and campus residence contexts.
    """

    def normalize(self, plate: str) -> str:
        return normalize_plate(plate)

    def find_vehicle(self, plate: str, db: Session) -> Optional[Vehicle]:
        norm_plate = self.normalize(plate)
        return db.query(Vehicle).filter(Vehicle.normalized_plate == norm_plate).first()

    def get_owner_for_vehicle(self, plate: str, db: Session) -> Optional[VehicleOwner]:
        vehicle = self.find_vehicle(plate, db)
        if vehicle and vehicle.owner:
            return vehicle.owner
        return None

    def is_vehicle_active(self, vehicle: Vehicle) -> bool:
        if not vehicle or vehicle.status != VehicleStatus.ACTIVE:
            return False
        
        now = datetime.now(timezone.utc)
        if vehicle.valid_from and now < vehicle.valid_from:
            return False
        if vehicle.valid_until and now > vehicle.valid_until:
            return False
        return True

    def get_residence_context(self, owner: Optional[VehicleOwner]) -> Dict[str, Any]:
        if not owner:
            return {
                "person_type": None,
                "residence_type": None,
                "residence": None,
                "department": None
            }
        return {
            "person_type": owner.person_type.value if owner.person_type else None,
            "residence_type": owner.residence_type.value if owner.residence_type else None,
            "residence": owner.residence,
            "department": owner.department
        }

    def build_owner_context(self, owner: VehicleOwner) -> Dict[str, Any]:
        return {
            "id": str(owner.id),
            "institutional_id": owner.identifier,
            "name": owner.full_name,
            "email": owner.email,
            "phone": owner.phone,
            "person_type": owner.person_type.value if owner.person_type else None,
            "residence_type": owner.residence_type.value if owner.residence_type else None,
            "residence": owner.residence,
            "department": owner.department,
            "status": owner.status
        }

    def resolve(self, plate: str, db: Session) -> Optional[Dict[str, Any]]:
        """
        Executes PLATE → VEHICLE → OWNER → RESIDENCE CONTEXT resolution.
        Returns None if vehicle is not registered.
        """
        vehicle = self.find_vehicle(plate, db)
        if not vehicle:
            return None
        return self.build_context(vehicle)

    def build_context(self, vehicle: Vehicle) -> Dict[str, Any]:
        """Builds the vehicle / owner / residence context for an already-loaded vehicle."""
        is_active = self.is_vehicle_active(vehicle)
        owner_info = None
        residence_ctx = self.get_residence_context(vehicle.owner)

        if vehicle.owner:
            owner_info = self.build_owner_context(vehicle.owner)
        elif vehicle.visitor:
            visitor = vehicle.visitor
            owner_info = {
                "id": str(visitor.id),
                "institutional_id": f"VISITOR-{visitor.id.hex[:6].upper()}",
                "name": visitor.visitor_name,
                "email": None,
                "phone": visitor.phone,
                "person_type": "VISITOR",
                "residence_type": "OFF_CAMPUS",
                "residence": None,
                "department": None,
                "status": visitor.status,
                "purpose": visitor.purpose,
                "valid_until": visitor.valid_until.isoformat() if visitor.valid_until else None
            }
            residence_ctx = {
                "person_type": "VISITOR",
                "residence_type": "OFF_CAMPUS",
                "residence": None,
                "department": None
            }

        return {
            "vehicle": {
                "id": str(vehicle.id),
                "plate": vehicle.normalized_plate,
                "raw_plate": vehicle.raw_plate,
                "category": vehicle.vehicle_category.value,
                "status": vehicle.status.value,
                "is_active": is_active,
                "make_model": vehicle.make_model,
                "color": vehicle.color,
                "valid_from": vehicle.valid_from.isoformat() if vehicle.valid_from else None,
                "valid_until": vehicle.valid_until.isoformat() if vehicle.valid_until else None,
                "notes": vehicle.notes
            },
            "owner": owner_info,
            "context": {
                **residence_ctx,
                "is_active": is_active,
                "vehicle_status": vehicle.status.value
            }
        }

vehicle_identity_service = VehicleIdentityService()
