"""
Regression scenarios for the 2026-10-13 adversarial audit.

Each module in scripts/audit_regressions/ reproduces one finding: its scenarios failed on the
code as found and pass once that finding's fix is in. Scenarios call the app in-process with
FastAPI's TestClient (no uvicorn, no MQTT), so nothing listens on :8000.

Run against a scratch database: scenarios append rows to append-only tables that cannot be
removed afterwards.

    DATABASE_URL=<scratch db> PYTHONPATH=. .venv/bin/python scripts/test_audit_regressions.py
    DATABASE_URL=<scratch db> PYTHONPATH=. .venv/bin/python scripts/test_audit_regressions.py -k truncate
"""
import argparse
import importlib
import os
import pkgutil
import sys
import traceback

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import scripts.audit_regressions as suite  # noqa: E402


def collect():
    for info in sorted(pkgutil.iter_modules(suite.__path__), key=lambda m: m.name):
        if info.name.startswith("check_"):
            module = importlib.import_module(f"{suite.__name__}.{info.name}")
            for name, func in module.SCENARIOS:
                yield f"{info.name}::{name}", func


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-k", dest="pattern", default="", help="run scenarios whose id contains this text")
    args = parser.parse_args()

    results = []
    for scenario_id, func in collect():
        if args.pattern and args.pattern not in scenario_id:
            continue
        try:
            func()
            results.append((scenario_id, "PASS", ""))
        except AssertionError as exc:
            results.append((scenario_id, "FAIL", str(exc)))
        except Exception:  # noqa: BLE001 - an unexpected error is reported, not hidden
            results.append((scenario_id, "ERROR", traceback.format_exc(limit=3)))

    print("========================================================")
    print("AUDIT REGRESSION SCENARIOS")
    print("========================================================")
    for scenario_id, outcome, detail in results:
        print(f"[{outcome}] {scenario_id}")
        if detail:
            print("        " + detail.strip().replace("\n", "\n        "))
    failed = [r for r in results if r[1] != "PASS"]
    print(f"\n{len(results) - len(failed)}/{len(results)} scenarios passed")
    return 1 if failed or not results else 0


if __name__ == "__main__":
    sys.exit(main())
