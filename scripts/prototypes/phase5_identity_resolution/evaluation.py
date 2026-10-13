from typing import List, Dict, Any
from scripts.prototypes.phase5_identity_resolution.models import ResolutionStatus, ResolutionResult

def compute_metrics(evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes rigorous evaluation metrics comparing Ground Truth to Resolution Result:
    - Total evaluated
    - Exact matches
    - Correct matches (exact + correct fuzzy)
    - False identity matches (critical error: matched to wrong person)
    - Unknown rate
    - Ambiguity rate
    - Precision, Recall, Accuracy
    """
    total = len(evaluations)
    if total == 0:
        return {"total": 0}

    exact_matches = 0
    correct_fuzzy_matches = 0
    false_identities = 0
    unknowns = 0
    ambiguities = 0
    invalids = 0

    for item in evaluations:
        ground_truth = item.get("ground_truth_plate")
        result: ResolutionResult = item["result"]

        res_status = result.identity_status
        matched_plate = result.vehicle.get("plate") if result.vehicle else None

        if res_status == ResolutionStatus.INVALID:
            invalids += 1
        elif res_status == ResolutionStatus.UNKNOWN:
            unknowns += 1
        elif res_status == ResolutionStatus.AMBIGUOUS:
            ambiguities += 1
        elif res_status == ResolutionStatus.KNOWN:
            if ground_truth and matched_plate == ground_truth:
                if result.match_method.value == "EXACT_NORMALIZED":
                    exact_matches += 1
                else:
                    correct_fuzzy_matches += 1
            else:
                false_identities += 1

    total_correct = exact_matches + correct_fuzzy_matches
    recall = round(total_correct / total, 4) if total > 0 else 0.0
    precision = round(total_correct / (total_correct + false_identities), 4) if (total_correct + false_identities) > 0 else 0.0
    false_identity_rate = round(false_identities / total, 4) if total > 0 else 0.0
    unknown_rate = round(unknowns / total, 4) if total > 0 else 0.0
    ambiguity_rate = round(ambiguities / total, 4) if total > 0 else 0.0

    return {
        "total_evaluations": total,
        "exact_matches": exact_matches,
        "correct_fuzzy_matches": correct_fuzzy_matches,
        "total_correct": total_correct,
        "false_identities": false_identities,
        "unknowns": unknowns,
        "ambiguities": ambiguities,
        "invalids": invalids,
        "precision": precision,
        "recall": recall,
        "false_identity_rate": false_identity_rate,
        "unknown_rate": unknown_rate,
        "ambiguity_rate": ambiguity_rate
    }
