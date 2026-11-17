"""On-disk layout of the private data root, plus atomic and lock-protected file writes."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory and rename, so readers never see half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def read_json(path: Path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else default


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    atomic_write_text(path, "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows))


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Exclusive advisory lock on `<path>.lock`, held for the duration of the block (process- and thread-safe)."""
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class Store:
    """Paths under the data root. Everything here is private (raw frames, plate text) and stays out of git."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser()

    def _dir(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def videos_registry(self) -> Path:
        return self._dir("splits") / "videos.json"

    def frames_dir(self, video_id: str) -> Path:
        return self._dir("frames", video_id)

    @property
    def frames_manifest(self) -> Path:
        return self._dir("manifests") / "frames.jsonl"

    def round_dir(self, round_id: str) -> Path:
        return self._dir("rounds", round_id)

    def predictions_dir(self, round_id: str) -> Path:
        return self._dir("rounds", round_id, "predictions")

    def crops_dir(self, round_id: str) -> Path:
        return self._dir("rounds", round_id, "crops")

    def queue_path(self, round_id: str) -> Path:
        return self.round_dir(round_id) / "queue.jsonl"

    @property
    def audit_log(self) -> Path:
        return self._dir("reviews") / "audit_log.jsonl"

    @property
    def approved_dir(self) -> Path:
        return self._dir("approved")

    def dataset_dir(self, round_id: str) -> Path:
        return self._dir("datasets", round_id)

    def runs_dir(self, round_id: str) -> Path:
        return self._dir("runs", round_id)

    @property
    def registry(self) -> Path:
        return self._dir("registry") / "registry.jsonl"

    @property
    def models_dir(self) -> Path:
        return self._dir("registry", "models")

    @property
    def gold_dir(self) -> Path:
        return self._dir("gold")

    @property
    def bootstrap_dir(self) -> Path:
        return self._dir("bootstrap")

    @property
    def exports_dir(self) -> Path:
        return self._dir("exports")
