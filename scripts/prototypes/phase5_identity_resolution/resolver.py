import uuid
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from backend.app.services.plate_normalizer import normalize_plate
from scripts.prototypes.phase5_identity_resolution.models import (
    ResolutionStatus,
    MatchMethod,
    ResolutionCandidate,
    ResolutionResult
)
from scripts.prototypes.phase5_identity_resolution.fuzzy_matcher import FuzzyMatcher
from scripts.prototypes.phase5_identity_resolution.fixtures import get_test_fixtures

class IdentityResolver:
    """
    Isolated Phase 5A identity and context resolution engine.
    Associates vehicle observations with institutional identities and residence context.
    Adheres strictly to the principle:
        UNKNOWN over WRONG IDENTITY, and AMBIGUOUS over FALSE CERTAINTY.
    """

    def __init__(
        self,
        registry: Optional[List[Dict[str, Any]]] = None,
        fuzzy_matcher: Optional[FuzzyMatcher] = None
    ):
        self.registry = registry if registry is not None else get_test_fixtures()
        self.fuzzy_matcher = fuzzy_matcher or FuzzyMatcher(
            min_similarity=0.85,
            ambiguity_margin=0.08,
            ocr_confusion_penalty=0.25
        )
        self._plate_index = {item["plate"]: item for item in self.registry}

    def _find_in_registry(self, plate: str) -> Optional[Dict[str, Any]]:
        return self._plate_index.get(plate)

    def _get_candidate_plates(self) -> List[str]:
        return list(self._plate_index.keys())

    def _build_context_from_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        owner = item.get("owner")
        visitor = item.get("visitor")
        delivery = item.get("delivery")

        residence_ctx = None
        owner_ctx = None
        visitor_ctx = None
        delivery_ctx = None

        if owner:
            owner_ctx = {
                "id": str(owner.get("id")),
                "institutional_id": owner.get("identifier"),
                "name": owner.get("full_name"),
                "person_type": owner.get("person_type"),
                "department": owner.get("department"),
                "email": owner.get("email"),
                "phone": owner.get("phone")
            }
            residence_ctx = {
                "type": owner.get("residence_type"),
                "value": owner.get("residence")
            }
        elif visitor:
            visitor_ctx = {
                "visitor_id": str(visitor.get("id")),
                "visitor_name": visitor.get("visitor_name"),
                "phone": visitor.get("phone"),
                "purpose": visitor.get("purpose"),
                "host_name": visitor.get("host_name"),
                "valid_until": visitor.get("valid_until").isoformat() if visitor.get("valid_until") else None
            }
            residence_ctx = {
                "type": "OFF_CAMPUS",
                "value": None
            }

        if delivery:
            delivery_ctx = {
                "platform": delivery.get("platform"),
                "driver_name": delivery.get("driver_name"),
                "driver_phone": delivery.get("driver_phone"),
                "is_verified": delivery.get("is_verified", True)
            }

        vehicle_ctx = {
            "id": str(item.get("id", uuid.uuid4())),
            "plate": item["plate"],
            "raw_plate": item.get("raw_plate", item["plate"]),
            "category": item.get("category", "UNKNOWN"),
            "status": item.get("status", "ACTIVE"),
            "is_active": (item.get("status") == "ACTIVE")
        }

        return {
            "vehicle": vehicle_ctx,
            "owner": owner_ctx,
            "residence": residence_ctx,
            "visitor": visitor_ctx,
            "delivery": delivery_ctx
        }

    def resolve(
        self,
        observation: Any,
        db: Optional[Session] = None
    ) -> ResolutionResult:
        """
        Executes hierarchical identity resolution:
        Input validation -> Level 2 (No Plate) -> Level 1 (Exact Normalized) -> Level 3 (Fuzzy Matching).
        """
        # 1. Validation
        if not isinstance(observation, dict):
            return ResolutionResult(
                identity_status=ResolutionStatus.INVALID,
                match_method=MatchMethod.INVALID_INPUT,
                notes="Observation payload must be a dictionary"
            )

        obs_id = observation.get("id") or observation.get("observation_id")
        raw_plate = observation.get("plate") or observation.get("raw_plate")
        perception_confidence = observation.get("plate_confidence")
        if perception_confidence is not None:
            try:
                perception_confidence = float(perception_confidence)
            except (ValueError, TypeError):
                perception_confidence = None

        # 2. Level 2: No Plate
        if raw_plate is None or (isinstance(raw_plate, str) and not raw_plate.strip()):
            return ResolutionResult(
                observation_id=obs_id,
                identity_status=ResolutionStatus.UNKNOWN,
                match_method=MatchMethod.NO_PLATE,
                perception_confidence=perception_confidence,
                notes="No license plate was detected in observation"
            )

        # 3. Level 1: Exact Normalized Match
        norm_plate = normalize_plate(str(raw_plate))
        matched_item = self._find_in_registry(norm_plate)

        if matched_item:
            ctx = self._build_context_from_item(matched_item)
            return ResolutionResult(
                observation_id=obs_id,
                identity_status=ResolutionStatus.KNOWN,
                match_method=MatchMethod.EXACT_NORMALIZED,
                vehicle=ctx["vehicle"],
                owner=ctx["owner"],
                residence=ctx["residence"],
                visitor=ctx["visitor"],
                delivery=ctx["delivery"],
                perception_confidence=perception_confidence,
                match_similarity=1.0,
                notes="Exact normalized plate match confirmed"
            )

        # 4. Level 3: Fuzzy Candidate Resolution
        all_candidates = self._get_candidate_plates()
        best_plate, best_score, qualifying, is_ambiguous = self.fuzzy_matcher.evaluate_match(
            norm_plate, all_candidates
        )

        candidate_models = []
        for cand_plate, sim in qualifying:
            c_item = self._find_in_registry(cand_plate)
            owner_name = None
            if c_item and c_item.get("owner"):
                owner_name = c_item["owner"].get("full_name")
            elif c_item and c_item.get("visitor"):
                owner_name = c_item["visitor"].get("visitor_name")

            candidate_models.append(
                ResolutionCandidate(
                    vehicle_id=str(c_item.get("id", cand_plate)),
                    plate=cand_plate,
                    similarity_score=sim,
                    owner_name=owner_name,
                    vehicle_status=c_item.get("status", "ACTIVE") if c_item else "ACTIVE",
                    category=c_item.get("category", "UNKNOWN") if c_item else "UNKNOWN"
                )
            )

        # Handle Ambiguity
        if is_ambiguous:
            return ResolutionResult(
                observation_id=obs_id,
                identity_status=ResolutionStatus.AMBIGUOUS,
                match_method=MatchMethod.AMBIGUOUS_CANDIDATES,
                perception_confidence=perception_confidence,
                match_similarity=best_score,
                candidates=candidate_models,
                notes=f"Ambiguous candidates detected within margin {self.fuzzy_matcher.ambiguity_margin}"
            )

        # Handle Confident Fuzzy Match
        if best_plate and not is_ambiguous:
            matched_item = self._find_in_registry(best_plate)
            ctx = self._build_context_from_item(matched_item)
            return ResolutionResult(
                observation_id=obs_id,
                identity_status=ResolutionStatus.KNOWN,
                match_method=MatchMethod.FUZZY_CONFIDENT,
                vehicle=ctx["vehicle"],
                owner=ctx["owner"],
                residence=ctx["residence"],
                visitor=ctx["visitor"],
                delivery=ctx["delivery"],
                perception_confidence=perception_confidence,
                match_similarity=best_score,
                candidates=candidate_models,
                notes=f"Confident fuzzy match resolved to '{best_plate}' with similarity {best_score}"
            )

        # Handle No Matching Candidate
        return ResolutionResult(
            observation_id=obs_id,
            identity_status=ResolutionStatus.UNKNOWN,
            match_method=MatchMethod.NO_CANDIDATE,
            perception_confidence=perception_confidence,
            match_similarity=best_score,
            notes="No registered vehicle matched above similarity threshold"
        )
