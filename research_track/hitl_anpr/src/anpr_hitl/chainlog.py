"""Append-only JSONL log with a SHA-256 hash chain (review audit log and model registry).

Each entry stores the previous entry's hash; editing, deleting or reordering any line breaks the chain,
which verify() reports. Appends hold an exclusive file lock, so concurrent writers serialise. This is
tamper-evident, not tamper-proof: anchor head() somewhere else (model card, git) to detect a full rewrite.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from anpr_hitl.store import file_lock

GENESIS = "0" * 64


def _entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class ChainError(RuntimeError):
    pass


class ChainLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read_lines(self) -> list[str]:
        return self.path.read_text().splitlines() if self.path.is_file() else []

    def append(self, record: dict) -> dict:
        """Append a record; returns the stored entry (with seq, ts, prev_hash, hash)."""
        if {"seq", "prev_hash", "hash"} & record.keys():
            raise ValueError("seq, prev_hash and hash are assigned by the log")
        record = dict(record)
        with file_lock(self.path):
            entries, problems = self._parse_and_verify()
            if problems:
                raise ChainError(f"refusing to append to a broken log: {problems[0]}")
            prev = entries[-1] if entries else None
            entry = {
                "seq": prev["seq"] + 1 if prev else 0,
                "ts": record.pop("ts", None) or datetime.now(timezone.utc).isoformat(),
                **record,
                "prev_hash": prev["hash"] if prev else GENESIS,
            }
            entry["hash"] = _entry_hash(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as fh:
                fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return entry

    def _parse_and_verify(self) -> tuple[list[dict], list[str]]:
        entries, problems = [], []
        prev_hash, expected_seq = GENESIS, 0
        for n, line in enumerate(self._read_lines(), 1):
            if not line.strip():
                problems.append(f"line {n}: blank line")
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"line {n}: not JSON")
                continue
            if entry.get("seq") != expected_seq:
                problems.append(f"line {n}: seq {entry.get('seq')} != expected {expected_seq}")
            if entry.get("prev_hash") != prev_hash:
                problems.append(f"line {n}: prev_hash does not match the previous entry")
            if entry.get("hash") != _entry_hash(entry):
                problems.append(f"line {n}: content does not match its hash")
            entries.append(entry)
            prev_hash, expected_seq = entry.get("hash"), expected_seq + 1
        return entries, problems

    def verify(self) -> list[str]:
        """Problems found (empty list = intact chain)."""
        return self._parse_and_verify()[1]

    def entries(self) -> list[dict]:
        """All entries; raises ChainError if the chain is broken."""
        entries, problems = self._parse_and_verify()
        if problems:
            raise ChainError("; ".join(problems[:3]))
        return entries

    def head(self) -> str:
        entries = self.entries()
        return entries[-1]["hash"] if entries else GENESIS
