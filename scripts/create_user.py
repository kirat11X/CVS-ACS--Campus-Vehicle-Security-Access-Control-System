"""
Creates or updates a dashboard user (ADMIN / SUPERVISOR / GUARD).

    PYTHONPATH=. .venv/bin/python scripts/create_user.py --username guard1 \
        --full-name "Gate 1 Guard" --email guard1@campus.edu --role GUARD

The password is prompted for (or read from the USER_PASSWORD environment variable).
"""
import argparse
import getpass
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models import User, UserRole
from backend.app.services.auth_service import hash_password

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=[r.value for r in UserRole])
    args = parser.parse_args()

    password = os.getenv("USER_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == args.username).first()
        action = "Updated" if user else "Created"
        if not user:
            user = User(username=args.username)
            db.add(user)
        user.full_name = args.full_name
        user.email = args.email
        user.role = args.role
        user.hashed_password = hash_password(password)
        user.is_active = True
        db.commit()
        print(f"{action} {args.role} user '{args.username}'.")

if __name__ == "__main__":
    main()
