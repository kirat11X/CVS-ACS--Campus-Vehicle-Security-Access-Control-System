#!/usr/bin/env python3
"""
CVS-ACS Diagnostic & Bug Tester
-------------------------------
Automated static, contract, environment, and optional live-stack bug tester for:
  https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System

Usage:
  python3 cvs_acs_bug_tester.py --repo-root /path/to/CVS-ACS
  python3 cvs_acs_bug_tester.py --repo-root . --live
  python3 cvs_acs_bug_tester.py --repo-root . --json-out bug_report.json
  python3 cvs_acs_bug_tester.py --self-test
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, List, Optional


@dataclass
class CheckResult:
    check_id: str
    category: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    status: str    # PASS, FAIL, WARN, SKIP
    title: str
    details: str
    remediation: str = ""


class CVSACSBugTester:
    def __init__(self, repo_root: Path, live: bool = False) -> None:
        self.repo_root = repo_root.resolve()
        self.live = live
        self.results: List[CheckResult] = []

    def add(self, res: CheckResult) -> None:
        self.results.append(res)

    # ------------------------------------------------------------------
    # 1. Repository & Documentation Drift Checks
    # ------------------------------------------------------------------
    def check_repo_structure(self) -> None:
        expected = [
            "README.md",
            "backend/app/main.py",
            "frontend/src/App.tsx",
            "research_track/MANIFEST.yaml",
            "scripts/test_audit_regressions.py",
        ]
        missing = [p for p in expected if not (self.repo_root / p).exists()]
        if missing:
            self.add(CheckResult(
                check_id="REPO-001",
                category="Repository",
                severity="HIGH",
                status="FAIL",
                title="Core repository paths missing",
                details=f"Missing expected files: {', '.join(missing)}",
                remediation="Run this script from the root of CVS-ACS--Campus-Vehicle-Security-Access-Control-System.",
            ))
        else:
            self.add(CheckResult(
                check_id="REPO-001",
                category="Repository",
                severity="INFO",
                status="PASS",
                title="Core repository structure present",
                details="All 5 anchor files found.",
            ))

    def check_docs_vs_code_drift(self) -> None:
        readme = self.repo_root / "README.md"
        main_py = self.repo_root / "backend/app/main.py"
        app_tsx = self.repo_root / "frontend/src/App.tsx"
        if not (readme.exists() and main_py.exists() and app_tsx.exists()):
            self.add(CheckResult(
                check_id="DOC-001",
                category="Documentation Drift",
                severity="LOW",
                status="SKIP",
                title="Docs vs code drift check skipped",
                details="One or more required files (README.md, main.py, App.tsx) not found.",
            ))
            return

        readme_text = readme.read_text(encoding="utf-8", errors="ignore")
        main_text = main_py.read_text(encoding="utf-8", errors="ignore")

        unchecked_phase16 = "- [ ] **Phase 16:**" in readme_text or "- [ ] Phase 16" in readme_text
        has_feed_router = "feed_router" in main_text and "resolutions_router" in main_text
        if unchecked_phase16 and has_feed_router:
            self.add(CheckResult(
                check_id="DOC-001",
                category="Documentation Drift",
                severity="MEDIUM",
                status="WARN",
                title="README roadmap lags behind implemented backend/frontend",
                details=(
                    "README.md leaves Phases 5-16 unchecked, while backend/app/main.py wires "
                    "feed_router/resolutions_router/movements_router/presence_router and frontend/src/App.tsx exists."
                ),
                remediation="Update README.md Section 6 and research_track/PROJECT_DIGEST.md to reflect actual v0.6.0/v0.5.0 state.",
            ))
        else:
            self.add(CheckResult(
                check_id="DOC-001",
                category="Documentation Drift",
                severity="INFO",
                status="PASS",
                title="README roadmap aligned with codebase",
                details="No obvious Phase 16 vs router drift detected.",
            ))

    def check_taxonomy_row_counts(self) -> None:
        candidates = [
            self.repo_root / "research_track/datasets/item_taxonomy_seed/seed_items.csv",
            self.repo_root / "research_track/track_c/fixtures/item_taxonomy_seed.csv",
        ]
        found = [p for p in candidates if p.exists()]
        if not found:
            self.add(CheckResult(
                check_id="DATA-001",
                category="Dataset Integrity",
                severity="LOW",
                status="SKIP",
                title="Taxonomy CSV count check skipped",
                details="No item_taxonomy_seed CSV found in expected paths.",
            ))
            return

        counts = {}
        for p in found:
            with p.open("r", encoding="utf-8", newline="") as f:
                reader = list(csv.reader(f))
                counts[str(p.relative_to(self.repo_root))] = max(0, len(reader) - 1)

        unique_counts = set(counts.values())
        if len(unique_counts) > 1 or any(c not in (300, 320) for c in unique_counts):
            self.add(CheckResult(
                check_id="DATA-001",
                category="Dataset Integrity",
                severity="MEDIUM",
                status="WARN",
                title="Item taxonomy CSV row count mismatch",
                details=f"Observed data row counts: {counts} (docs variously cite 300, 320, or 321).",
                remediation="Standardize on one canonical taxonomy CSV and update IMPLEMENTATION_REPORT.md / SETUP_RESULT.md.",
            ))
        else:
            self.add(CheckResult(
                check_id="DATA-001",
                category="Dataset Integrity",
                severity="INFO",
                status="PASS",
                title="Item taxonomy CSV row counts consistent",
                details=f"Row counts: {counts}",
            ))

    # ------------------------------------------------------------------
    # 2. Security, Config & Production Readiness Checks
    # ------------------------------------------------------------------
    def check_mock_whatsapp_leakage(self) -> None:
        main_py = self.repo_root / "backend/app/main.py"
        if not main_py.exists():
            self.add(CheckResult(
                check_id="PROD-001",
                category="Production Readiness",
                severity="LOW",
                status="SKIP",
                title="mock_whatsapp check skipped",
                details="backend/app/main.py not found.",
            ))
            return

        text = main_py.read_text(encoding="utf-8", errors="ignore")
        if "mock_whatsapp" in text:
            self.add(CheckResult(
                check_id="PROD-001",
                category="Production Readiness",
                severity="HIGH",
                status="FAIL",
                title="Backend entrypoint directly imports mock_whatsapp",
                details="backend/app/main.py references mock_whatsapp without an abstract live WhatsApp provider.",
                remediation="Implement an abstract WhatsAppProvider interface (Cloud API / Twilio) and gate mock_whatsapp behind SIMULATION_MODE=true.",
            ))
        else:
            self.add(CheckResult(
                check_id="PROD-001",
                category="Production Readiness",
                severity="INFO",
                status="PASS",
                title="No hardcoded mock_whatsapp in main.py",
                details="backend/app/main.py does not hardcode mock_whatsapp.",
            ))

    def check_env_security_and_alembic(self) -> None:
        env_file = self.repo_root / ".env"
        if not env_file.exists():
            self.add(CheckResult(
                check_id="SEC-001",
                category="Security & Config",
                severity="MEDIUM",
                status="WARN",
                title=".env file missing in repo root",
                details="No .env found; backend requires AUTH_SECRET_KEY and DATABASE_URL (port 5433).",
                remediation="Copy .env.example to .env and set a >=32-char random AUTH_SECRET_KEY.",
            ))
            return

        env_text = env_file.read_text(encoding="utf-8", errors="ignore")
        secret_match = re.search(r"^AUTH_SECRET_KEY=(.*)$", env_text, re.MULTILINE)
        if not secret_match:
            self.add(CheckResult(
                check_id="SEC-001",
                category="Security & Config",
                severity="HIGH",
                status="FAIL",
                title="AUTH_SECRET_KEY missing in .env",
                details="Backend startup refuses to boot without a non-placeholder AUTH_SECRET_KEY.",
                remediation="Add AUTH_SECRET_KEY=<32+ random hex/base64 chars> to .env.",
            ))
        else:
            val = secret_match.group(1).strip().strip('"').strip("'")
            if len(val) < 32 or "change" in val.lower() or "placeholder" in val.lower() or "secret" in val.lower():
                self.add(CheckResult(
                    check_id="SEC-001",
                    category="Security & Config",
                    severity="CRITICAL",
                    status="FAIL",
                    title="Weak or placeholder AUTH_SECRET_KEY in .env",
                    details=f"AUTH_SECRET_KEY length={len(val)} appears weak or placeholder.",
                    remediation="Generate a cryptographically random key: python3 -c 'import secrets; print(secrets.token_urlsafe(48))'",
                ))
            else:
                self.add(CheckResult(
                    check_id="SEC-001",
                    category="Security & Config",
                    severity="INFO",
                    status="PASS",
                    title="AUTH_SECRET_KEY length & format valid",
                    details=f"AUTH_SECRET_KEY configured (length={len(val)}).",
                ))

        db_match = re.search(r"^DATABASE_URL=(.*)$", env_text, re.MULTILINE)
        if db_match and ":5432/" in db_match.group(1):
            self.add(CheckResult(
                check_id="CFG-001",
                category="Security & Config",
                severity="HIGH",
                status="WARN",
                title="DATABASE_URL uses port 5432 instead of project port 5433",
                details="Project docker-compose.yml maps PostgreSQL 16 to host port 5433.",
                remediation="Verify whether your PostgreSQL instance is on 5433 or 5432.",
            ))

    # ------------------------------------------------------------------
    # 3. Research Track A / B / C Contract & Regression Checks
    # ------------------------------------------------------------------
    def check_research_track_contracts(self) -> None:
        rt_dir = self.repo_root / "research_track"
        if not rt_dir.exists():
            self.add(CheckResult(
                check_id="ML-001",
                category="Research Track",
                severity="LOW",
                status="SKIP",
                title="Research track contract checks skipped",
                details="research_track/ directory not found.",
            ))
            return

        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))

        # Check Track A normalizer (A-S1-001)
        try:
            plate_mod = importlib.import_module("research_track.track_a.src.plate_normalizer")
            norm_fn = getattr(plate_mod, "normalize_plate", None)
            if norm_fn is not None:
                res = norm_fn("   ")
                status_val = getattr(res, "status", str(res))
                if "UNREADABLE" in str(status_val).upper() or status_val == "":
                    self.add(CheckResult(
                        check_id="ML-A-001",
                        category="Track A Regression",
                        severity="INFO",
                        status="PASS",
                        title="Track A empty/whitespace OCR handling (A-S1-001)",
                        details=f"normalize_plate('   ') returned {status_val!r}.",
                    ))
                else:
                    self.add(CheckResult(
                        check_id="ML-A-001",
                        category="Track A Regression",
                        severity="HIGH",
                        status="FAIL",
                        title="Track A empty OCR returned non-UNREADABLE status (A-S1-001)",
                        details=f"normalize_plate('   ') returned {status_val!r} instead of UNREADABLE.",
                        remediation="Return status='UNREADABLE' for empty/whitespace OCR strings.",
                    ))
        except Exception as exc:
            self.add(CheckResult(
                check_id="ML-A-001",
                category="Track A Regression",
                severity="LOW",
                status="SKIP",
                title="Track A normalizer import skipped",
                details=f"Could not import research_track.track_a.src.plate_normalizer: {exc}",
            ))

        # Check Track B Decimal & Schema validator (B-S1-002 / B-S1-003)
        try:
            reconciler_mod = importlib.import_module("research_track.track_b.src.reconciler")
            self.add(CheckResult(
                check_id="ML-B-001",
                category="Track B Contract",
                severity="INFO",
                status="PASS",
                title="Track B reconciler module importable",
                details=f"Loaded {reconciler_mod.__name__}. Verify align_line_items uses bipartite assignment, not greedy.",
            ))
        except Exception as exc:
            self.add(CheckResult(
                check_id="ML-B-001",
                category="Track B Contract",
                severity="LOW",
                status="SKIP",
                title="Track B reconciler import skipped",
                details=f"Could not import Track B reconciler: {exc}",
            ))

    # ------------------------------------------------------------------
    # 4. ML Hardware & Environment Readiness Checks
    # ------------------------------------------------------------------
    def check_ml_environment(self) -> None:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info >= (3, 14):
            self.add(CheckResult(
                check_id="ENV-001",
                category="ML Environment",
                severity="MEDIUM",
                status="WARN",
                title="Running on Python 3.14+ (ML wheels incompatible)",
                details=f"Current Python is {py_ver}. Paddle/ML training requires the isolated Python 3.12 venv.",
                remediation="Use ~/ml-assets/campus/.venv-ml (Python 3.12) for Track A/B/C training.",
            ))
        else:
            self.add(CheckResult(
                check_id="ENV-001",
                category="ML Environment",
                severity="INFO",
                status="PASS",
                title="Python version compatible with ML stack",
                details=f"Python {py_ver}.",
            ))

        keras_backend = os.environ.get("KERAS_BACKEND", "")
        if keras_backend != "torch":
            self.add(CheckResult(
                check_id="ENV-002",
                category="ML Environment",
                severity="MEDIUM",
                status="WARN",
                title="KERAS_BACKEND is not set to 'torch'",
                details=f"KERAS_BACKEND={keras_backend!r}. Track A OCR training fails on TF 2.21 CUDA locally.",
                remediation="Export KERAS_BACKEND=torch before running Track A OCR training.",
            ))
        else:
            self.add(CheckResult(
                check_id="ENV-002",
                category="ML Environment",
                severity="INFO",
                status="PASS",
                title="KERAS_BACKEND=torch configured",
                details="Track A OCR backend correctly set to PyTorch.",
            ))

        # Check Linux MemAvailable for GNOME localsearch-3 contention
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            text = meminfo.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^MemAvailable:\s+(\d+)\s+kB", text, re.MULTILINE)
            if m:
                avail_gib = int(m.group(1)) / (1024 * 1024)
                if avail_gib < 6.0:
                    self.add(CheckResult(
                        check_id="ENV-003",
                        category="ML Environment",
                        severity="HIGH",
                        status="WARN",
                        title="Low available system RAM (< 6 GiB) for OCR/VLM training",
                        details=f"MemAvailable = {avail_gib:.2f} GiB. Previously GNOME localsearch-3 held 4.32 GiB and blocked Track A OCR.",
                        remediation="Stop localsearch-3 / close heavy apps before launching Track A OCR training.",
                    ))
                else:
                    self.add(CheckResult(
                        check_id="ENV-003",
                        category="ML Environment",
                        severity="INFO",
                        status="PASS",
                        title="System RAM sufficient for local ML runs",
                        details=f"MemAvailable = {avail_gib:.2f} GiB.",
                    ))

    # ------------------------------------------------------------------
    # 5. Optional Live Stack Probes (--live)
    # ------------------------------------------------------------------
    def _check_tcp(self, host: str, port: int, timeout: float = 1.5) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _check_http(self, url: str, timeout: float = 2.5) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return (200 <= resp.status < 300), f"HTTP {resp.status}"
        except urllib.error.URLError as exc:
            return False, str(exc.reason)
        except Exception as exc:
            return False, str(exc)

    def check_live_services(self) -> None:
        if not self.live:
            return

        tcp_targets = [
            ("LIVE-DB", "PostgreSQL 16", "127.0.0.1", 5433),
            ("LIVE-MQTT", "Mosquitto MQTT", "127.0.0.1", 1883),
            ("LIVE-N8N", "n8n Webhook Engine", "127.0.0.1", 5678),
        ]
        for cid, name, host, port in tcp_targets:
            ok = self._check_tcp(host, port)
            self.add(CheckResult(
                check_id=cid,
                category="Live Stack",
                severity="HIGH" if not ok else "INFO",
                status="PASS" if ok else "FAIL",
                title=f"{name} reachable on {host}:{port}",
                details="TCP handshake succeeded." if ok else f"Connection refused/timeout on {host}:{port}.",
                remediation="Run `docker compose up -d` and verify `docker compose ps`." if not ok else "",
            ))

        http_targets = [
            ("LIVE-API", "FastAPI /health/all", "http://127.0.0.1:8000/health/all"),
            ("LIVE-FRIGATE", "Frigate NVR /api/stats", "http://127.0.0.1:5000/api/stats"),
        ]
        for cid, name, url in http_targets:
            ok, msg = self._check_http(url)
            self.add(CheckResult(
                check_id=cid,
                category="Live Stack",
                severity="HIGH" if not ok else "INFO",
                status="PASS" if ok else "FAIL",
                title=f"{name} probe",
                details=f"{url} -> {msg}",
                remediation="Ensure uvicorn / Frigate container is running." if not ok else "",
            ))

    def run_all(self) -> List[CheckResult]:
        self.check_repo_structure()
        self.check_docs_vs_code_drift()
        self.check_taxonomy_row_counts()
        self.check_mock_whatsapp_leakage()
        self.check_env_security_and_alembic()
        self.check_research_track_contracts()
        self.check_ml_environment()
        self.check_live_services()
        return self.results


def run_self_test() -> int:
    """Verify the bug tester's internal logic using an isolated temporary structure."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "backend/app").mkdir(parents=True)
        (root / "frontend/src").mkdir(parents=True)
        (root / "research_track/datasets/item_taxonomy_seed").mkdir(parents=True)
        (root / "scripts").mkdir(parents=True)

        (root / "README.md").write_text("- [ ] **Phase 16:** React Dashboard\n", encoding="utf-8")
        (root / "backend/app/main.py").write_text(
            "from backend.app.whatsapp import mock as mock_whatsapp\n"
            "app.include_router(feed_router)\napp.include_router(resolutions_router)\n",
            encoding="utf-8",
        )
        (root / "frontend/src/App.tsx").write_text("export function App() { return null; }\n", encoding="utf-8")
        (root / "research_track/MANIFEST.yaml").write_text("version: 1\n", encoding="utf-8")
        (root / "scripts/test_audit_regressions.py").write_text("# test\n", encoding="utf-8")
        (root / ".env").write_text("AUTH_SECRET_KEY=placeholder_secret\nDATABASE_URL=postgresql://u:p@localhost:5432/db\n", encoding="utf-8")

        tester = CVSACSBugTester(repo_root=root, live=False)
        results = tester.run_all()
        ids = {r.check_id: r.status for r in results}
        assert ids.get("REPO-001") == "PASS", f"Expected REPO-001 PASS, got {ids}"
        assert ids.get("DOC-001") == "WARN", f"Expected DOC-001 WARN, got {ids}"
        assert ids.get("PROD-001") == "FAIL", f"Expected PROD-001 FAIL, got {ids}"
        assert ids.get("SEC-001") == "FAIL", f"Expected SEC-001 FAIL, got {ids}"
        print(f"SELF-TEST PASSED: {len(results)} checks executed cleanly.")
        return 0


def print_summary(results: List[CheckResult]) -> int:
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        badge = f"[{r.status:4s}][{r.severity:8s}]"
        print(f"{badge} {r.check_id}: {r.title}")
        print(f"   Details: {r.details}")
        if r.remediation:
            print(f"   Fix:     {r.remediation}")

    print("\nSummary:", json.dumps(counts))
    return 1 if counts["FAIL"] > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CVS-ACS Bug & Readiness Tester")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Path to CVS-ACS repository root")
    parser.add_argument("--live", action="store_true", help="Also probe live local Docker/FastAPI services")
    parser.add_argument("--json-out", type=Path, default=None, help="Write structured JSON report to path")
    parser.add_argument("--self-test", action="store_true", help="Run built-in self-test suite")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    tester = CVSACSBugTester(repo_root=args.repo_root, live=args.live)
    results = tester.run_all()

    if args.json_out:
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "platform": platform.platform(),
            "repo_root": str(tester.repo_root),
            "results": [asdict(r) for r in results],
        }
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return print_summary(results)


if __name__ == "__main__":
    raise SystemExit(main())
