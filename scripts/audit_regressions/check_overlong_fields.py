"""
Finding: ObservationCreate and VehicleCreate had no length limits although the columns are
VARCHAR(30/50/100). An over-long plate, event id, make/model or colour passed validation and failed in
PostgreSQL (StringDataRightTruncation), so the API answered 500 instead of a 422 validation error.
"""
import uuid

from scripts.audit_regressions.common import auth, client, ensure_gates, make_user


def overlong_input_is_a_validation_error():
    ensure_gates()
    _, admin = make_user("ADMIN")
    long = "A" * 120
    cases = {
        "observation raw_plate": ("/observations", {"gate_id": "GATE_1", "source": "OTHER", "raw_plate": long,
                                                    "source_event_id": f"audit-{uuid.uuid4().hex[:6]}"}),
        "observation source_event_id": ("/observations", {"gate_id": "GATE_1", "source": "OTHER", "source_event_id": long}),
        "observation camera_id": ("/observations", {"gate_id": "GATE_1", "source": "OTHER", "camera_id": long}),
        "vehicle plate": ("/vehicles", {"plate": long, "vehicle_category": "STUDENT"}),
        "vehicle make_model": ("/vehicles", {"plate": f"PB10{uuid.uuid4().hex[:6]}", "vehicle_category": "STUDENT", "make_model": long * 2}),
        "vehicle color": ("/vehicles", {"plate": f"PB10{uuid.uuid4().hex[:6]}", "vehicle_category": "STUDENT", "color": long}),
    }
    wrong = {}
    for name, (path, body) in cases.items():
        resp = client().post(path, json=body, headers=auth(admin))
        if resp.status_code != 422:
            wrong[name] = resp.status_code
    assert not wrong, f"over-long input not rejected with 422: {wrong}"


SCENARIOS = [
    ("overlong_input_is_a_validation_error", overlong_input_is_a_validation_error),
]
