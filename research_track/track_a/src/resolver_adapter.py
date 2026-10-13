"""
Track A: Phase 5A IdentityResolver Compatibility Adapter.

Documents the inspected Phase 5A resolver contract and provides bidirectional
compatibility mapping between Track A's multi-candidate OCR pipeline and the
Phase 5A resolver schema, without modifying any existing production files.

Discovered Phase 5A Contract:
-----------------------------
Location: scripts/prototypes/phase5_identity_resolution/resolver.py
Input: Dict[str, Any] with keys:
  - 'id' or 'observation_id': Optional[str]
  - 'plate' or 'raw_plate': Optional[str] (single string only)
  - 'plate_confidence': Optional[float]
Normalization: backend/app/services/plate_normalizer.py (re.sub(r'[^A-Za-z0-9]', '', plate).strip().upper())
Output: ResolutionResult dataclass / pydantic model with:
  - identity_status: ResolutionStatus (KNOWN, UNKNOWN, AMBIGUOUS, INVALID)
  - match_method: MatchMethod (EXACT_NORMALIZED, FUZZY_CONFIDENT, NO_PLATE, NO_CANDIDATE, AMBIGUOUS_CANDIDATES, INVALID_INPUT)
  - vehicle: Dict[str, Any] (id, plate, category, status)
  - owner, residence, visitor, delivery: Context dictionaries
  - match_similarity: Optional[float]
  - candidates: List[ResolutionCandidate] (plate, similarity_score, etc.)

Architectural Differences in Track A:
-------------------------------------
1. Multi-Candidate Ingestion: Track A accepts N candidates from multiple OCR engines.
2. Invariant Decoupling: Track A decouples plate registration lookup from human owner identity.
3. Explicit Margins: Track A outputs explicit score margins and non-destructive confusion variants.
"""

from typing import Any, Dict, List, Optional
from .candidate_ranking import RankedCandidate
from .registry_matcher import MatchStatus, RegistryMatchResult, RegistryRecord, MatchCandidate


class Phase5AResolverAdapter:
    """
    Adapter bridging Track A research outputs and the Phase 5A resolver contract.
    """

    @staticmethod
    def to_phase5a_observation(
        ranked_candidates: List[RankedCandidate],
        observation_id: str = "obs-research-01"
    ) -> Dict[str, Any]:
        """
        Maps Track A's ranked candidates into the Phase 5A observation dictionary contract.
        Selects the top-ranked OCR candidate as the primary plate observation.
        """
        if not ranked_candidates:
            return {
                "observation_id": observation_id,
                "plate": None,
                "plate_confidence": None
            }

        top = ranked_candidates[0]
        return {
            "observation_id": observation_id,
            "plate": top.candidate.raw_text,
            "plate_confidence": top.candidate.confidence
        }

    @staticmethod
    def from_phase5a_result(
        result_obj: Any,
        threshold_used: float = 0.85,
        ambiguity_margin_used: float = 0.08
    ) -> RegistryMatchResult:
        """
        Translates a Phase 5A ResolutionResult object/dict back into Track A's RegistryMatchResult.
        """
        # Read from dictionary or pydantic model attributes
        if isinstance(result_obj, dict):
            status_str = str(result_obj.get("identity_status", "UNKNOWN"))
            method_str = str(result_obj.get("match_method", "NO_CANDIDATE"))
            vehicle = result_obj.get("vehicle") or {}
            match_sim = float(result_obj.get("match_similarity") or 0.0)
            candidates_raw = result_obj.get("candidates") or []
            notes = result_obj.get("notes", "")
        else:
            status_str = getattr(result_obj.identity_status, "value", str(result_obj.identity_status))
            method_str = getattr(result_obj.match_method, "value", str(result_obj.match_method))
            vehicle = getattr(result_obj, "vehicle", {}) or {}
            match_sim = float(getattr(result_obj, "match_similarity", 0.0) or 0.0)
            candidates_raw = getattr(result_obj, "candidates", []) or []
            notes = getattr(result_obj, "notes", "")

        matched_plate = vehicle.get("plate") if vehicle else None
        record = None
        if matched_plate:
            record = RegistryRecord(
                registry_id=str(vehicle.get("id", matched_plate)),
                plate=matched_plate,
                raw_plate=vehicle.get("raw_plate", matched_plate),
                vehicle_type=vehicle.get("category", "CAR"),
                status=vehicle.get("status", "ACTIVE")
            )

        # Map Phase 5A status to Track A MatchStatus
        if method_str == "EXACT_NORMALIZED":
            track_a_status = MatchStatus.EXACT_MATCH
        elif method_str == "FUZZY_CONFIDENT":
            track_a_status = MatchStatus.FUZZY_CONFIDENT
        elif status_str == "AMBIGUOUS" or method_str == "AMBIGUOUS_CANDIDATES":
            track_a_status = MatchStatus.AMBIGUOUS
            record = None
            matched_plate = None
        elif status_str == "INVALID" or method_str == "INVALID_INPUT":
            track_a_status = MatchStatus.INVALID_INPUT
        else:
            track_a_status = MatchStatus.NO_MATCH
            record = None
            matched_plate = None

        # Build candidates list
        qualifying: List[MatchCandidate] = []
        for c in candidates_raw:
            c_dict = c if isinstance(c, dict) else (c.model_dump() if hasattr(c, "model_dump") else c.__dict__)
            p = c_dict.get("plate", "")
            s = float(c_dict.get("similarity_score", 0.0))
            cand_rec = RegistryRecord(
                registry_id=str(c_dict.get("vehicle_id", p)),
                plate=p,
                vehicle_type=c_dict.get("category", "UNKNOWN"),
                status=c_dict.get("vehicle_status", "ACTIVE")
            )
            qualifying.append(MatchCandidate(
                record=cand_rec,
                similarity_score=s,
                method="PHASE_5A",
                details=f"Similarity: {s:.4f}"
            ))

        return RegistryMatchResult(
            status=track_a_status,
            matched_record=record,
            matched_plate=matched_plate,
            similarity_score=match_sim,
            score_margin=0.0,  # Phase 5A does not expose margin
            qualifying_candidates=qualifying,
            is_ambiguous=(track_a_status == MatchStatus.AMBIGUOUS),
            threshold_used=threshold_used,
            ambiguity_margin_used=ambiguity_margin_used,
            algorithm_used="phase5a_weighted_levenshtein",
            explanation=f"Mapped from Phase 5A: {notes}"
        )
