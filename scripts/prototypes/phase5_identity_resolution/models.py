from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class ResolutionStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"

class MatchMethod(str, Enum):
    EXACT_NORMALIZED = "EXACT_NORMALIZED"
    FUZZY_CONFIDENT = "FUZZY_CONFIDENT"
    NO_PLATE = "NO_PLATE"
    NO_CANDIDATE = "NO_CANDIDATE"
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
    INVALID_INPUT = "INVALID_INPUT"

class ResolutionCandidate(BaseModel):
    vehicle_id: str
    plate: str
    similarity_score: float
    owner_name: Optional[str] = None
    vehicle_status: str = "ACTIVE"
    category: str = "UNKNOWN"

class ResolutionResult(BaseModel):
    observation_id: Optional[str] = None
    identity_status: ResolutionStatus
    match_method: MatchMethod
    vehicle: Optional[Dict[str, Any]] = None
    owner: Optional[Dict[str, Any]] = None
    residence: Optional[Dict[str, Any]] = None
    visitor: Optional[Dict[str, Any]] = None
    delivery: Optional[Dict[str, Any]] = None
    perception_confidence: Optional[float] = None
    match_similarity: Optional[float] = None
    candidates: List[ResolutionCandidate] = Field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
