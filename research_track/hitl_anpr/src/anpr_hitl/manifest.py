"""Canonical JSONL manifests and their content hash (the "data hash" in model cards and the registry)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from anpr_hitl.store import atomic_write_text


def canonical_line(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


def manifest_hash(rows: list[dict]) -> str:
    """Order-independent: rows are hashed in sorted canonical form."""
    digest = hashlib.sha256()
    for line in sorted(canonical_line(r) for r in rows):
        digest.update(line.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def write_manifest(path: Path, rows: list[dict]) -> str:
    lines = sorted(canonical_line(r) for r in rows)
    atomic_write_text(Path(path), "".join(line + "\n" for line in lines))
    return manifest_hash(rows)


def read_manifest(path: Path) -> list[dict]:
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []
