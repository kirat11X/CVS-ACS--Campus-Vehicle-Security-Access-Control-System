from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

def get_test_fixtures() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=180)
    past = now - timedelta(days=30)

    return [
        # 1. Student Hosteller
        {
            "plate": "PB65AB0902",
            "raw_plate": "PB 65 AB 0902",
            "category": "STUDENT",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "11111111-1111-1111-1111-111111111111",
                "identifier": "STUDENT-2026-H0902",
                "full_name": "Kirat Singh",
                "person_type": "STUDENT",
                "residence_type": "HOSTELLER",
                "residence": "BH-4, Room 312",
                "department": "Computer Science & Engineering",
                "email": "kirat@pec.edu.in",
                "phone": "+919876543210"
            }
        },
        # 2. Student Day Scholar
        {
            "plate": "PB65AB1111",
            "raw_plate": "PB 65 AB 1111",
            "category": "STUDENT",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "22222222-2222-2222-2222-222222222222",
                "identifier": "STUDENT-2026-D1111",
                "full_name": "Rohan Verma",
                "person_type": "STUDENT",
                "residence_type": "DAY_SCHOLAR",
                "residence": "Sector 15, Chandigarh",
                "department": "Mechanical Engineering",
                "email": "rohan@pec.edu.in",
                "phone": "+919876543211"
            }
        },
        # 3. Faculty Member
        {
            "plate": "CH01AB2222",
            "raw_plate": "CH 01 AB 2222",
            "category": "FACULTY",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "33333333-3333-3333-3333-333333333333",
                "identifier": "FACULTY-CSE-222",
                "full_name": "Dr. Rajesh Sharma",
                "person_type": "FACULTY",
                "residence_type": "OFF_CAMPUS",
                "residence": "Sector 11, Chandigarh",
                "department": "Computer Science & Engineering",
                "email": "rsharma@pec.edu.in",
                "phone": "+919876543212"
            }
        },
        # 4. Staff Member
        {
            "plate": "CH01AB3333",
            "raw_plate": "CH 01 AB 3333",
            "category": "STAFF",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "44444444-4444-4444-4444-444444444444",
                "identifier": "STAFF-ADM-333",
                "full_name": "Sunita Devi",
                "person_type": "STAFF",
                "residence_type": "RESIDENT",
                "residence": "Campus Quarter 45",
                "department": "Academic Administration",
                "email": "sunita@pec.edu.in",
                "phone": "+919876543213"
            }
        },
        # 5. Campus Resident
        {
            "plate": "CH01AB4444",
            "raw_plate": "CH 01 AB 4444",
            "category": "RESIDENT",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "55555555-5555-5555-5555-555555555555",
                "identifier": "RESIDENT-DIR-444",
                "full_name": "Col. H. S. Dhillon",
                "person_type": "RESIDENT",
                "residence_type": "RESIDENT",
                "residence": "Director Residence, PEC Campus",
                "department": "Campus Administration",
                "email": "hsdhillon@pec.edu.in",
                "phone": "+919876543214"
            }
        },
        # 6. Registered Visitor
        {
            "plate": "DL03XY5555",
            "raw_plate": "DL 03 XY 5555",
            "category": "VISITOR",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "visitor": {
                "id": "66666666-6666-6666-6666-666666666666",
                "visitor_name": "Guest Speaker Dr. Gupta",
                "phone": "+919876543215",
                "purpose": "Invited Lecture on Distributed Systems",
                "host_name": "Dr. Rajesh Sharma",
                "valid_from": past,
                "valid_until": future,
                "status": "ACTIVE"
            }
        },
        # 7. Delivery Fleet Vehicle
        {
            "plate": "PB65DL6666",
            "raw_plate": "PB 65 DL 6666",
            "category": "DELIVERY",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "delivery": {
                "id": "77777777-7777-7777-7777-777777777777",
                "platform": "ZOMATO",
                "driver_name": "Ramesh Courier",
                "driver_phone": "+919876543216",
                "is_verified": True
            }
        },
        # 8. Inactive Vehicle
        {
            "plate": "PB65AB7777",
            "raw_plate": "PB 65 AB 7777",
            "category": "STUDENT",
            "status": "INACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "88888888-8888-8888-8888-888888888888",
                "identifier": "STUDENT-ALUM-777",
                "full_name": "Alumnus Jaspreet Singh",
                "person_type": "STUDENT",
                "residence_type": "OFF_CAMPUS",
                "residence": "Mohali Phase 7",
                "department": "Civil Engineering",
                "email": "jaspreet@pec.edu.in",
                "phone": "+919876543217"
            }
        },
        # 9. Expired Vehicle
        {
            "plate": "HR26EX8888",
            "raw_plate": "HR 26 EX 8888",
            "category": "VISITOR",
            "status": "EXPIRED",
            "valid_from": past - timedelta(days=60),
            "valid_until": past,
            "owner": None
        },
        # 10. Suspended Vehicle
        {
            "plate": "PB65SU9999",
            "raw_plate": "PB 65 SU 9999",
            "category": "STUDENT",
            "status": "SUSPENDED",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "99999999-9999-9999-9999-999999999999",
                "identifier": "STUDENT-SUSP-999",
                "full_name": "Harpreet Singh",
                "person_type": "STUDENT",
                "residence_type": "HOSTELLER",
                "residence": "BH-2, Room 101",
                "department": "Electrical Engineering",
                "email": "harpreet@pec.edu.in",
                "phone": "+919876543218"
            }
        },
        # 11. Near-Duplicate Cluster (for ambiguity testing)
        # PB65AB0902 already above
        {
            "plate": "PB65AB0903",
            "raw_plate": "PB 65 AB 0903",
            "category": "STAFF",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "identifier": "STAFF-ADM-0903",
                "full_name": "Amit Kumar",
                "person_type": "STAFF",
                "residence_type": "OFF_CAMPUS",
                "residence": "Panchkula Sector 4",
                "department": "Administration",
                "email": "amit@pec.edu.in",
                "phone": "+919876543219"
            }
        },
        {
            "plate": "PB65AC0902",
            "raw_plate": "PB 65 AC 0902",
            "category": "FACULTY",
            "status": "ACTIVE",
            "valid_from": past,
            "valid_until": future,
            "owner": {
                "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "identifier": "FACULTY-ECE-0902",
                "full_name": "Dr. Meenakshi Saini",
                "person_type": "FACULTY",
                "residence_type": "RESIDENT",
                "residence": "Faculty Enclave Qtr 14",
                "department": "Electronics & Communication Engineering",
                "email": "meenakshi@pec.edu.in",
                "phone": "+919876543220"
            }
        }
    ]
