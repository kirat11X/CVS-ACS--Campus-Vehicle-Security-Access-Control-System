"""Model registry on the hash-chained log. The champion is derived by replaying events, never stored.

Events: register (weights copied into registry/models/<version>/ with SHA-256, data manifest hash, config
hash, git SHA, GOLD metrics), promote, reject, rollback. `champion()` re-verifies the weights hash.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from anpr_hitl.chainlog import ChainLog
from anpr_hitl.config import PACKAGE_ROOT, Config
from anpr_hitl.hashing import sha256_file
from anpr_hitl.store import Store


class RegistryError(RuntimeError):
    pass


def git_sha(path: Path = PACKAGE_ROOT) -> str:
    """HEAD SHA of the repository holding the code, suffixed with +dirty if the package has local edits."""
    try:
        sha = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=10, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--", "."], capture_output=True,
                               text=True, timeout=10).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except Exception:  # noqa: BLE001 - outside a git checkout
        return "unknown"


class Registry:
    def __init__(self, store: Store):
        self.store = store
        self.log = ChainLog(store.registry)

    def _records(self) -> list[dict]:
        return self.log.entries()

    def models(self) -> dict[str, dict]:
        return {e["version"]: e for e in self._records() if e["event"] == "register"}

    def register(self, weights: Path, cfg: Config, data_sha256: str, round_id: str, metrics: dict,
                 gold_sha256: str | None = None, parent: str | None = None, notes: str = "",
                 train_args: Path | None = None) -> dict:
        """Copy the weights (and the exact training arguments, Ultralytics' args.yaml) into the registry."""
        version = f"v{len(self.models()) + 1:04d}"
        folder = self.store.models_dir / version
        dest = folder / "best.pt"
        if dest.exists():
            raise RegistryError(f"{dest} already exists")
        folder.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        shutil.copyfile(weights, tmp)
        tmp.replace(dest)
        args_sha = None
        if train_args is not None and Path(train_args).is_file():
            shutil.copyfile(train_args, folder / "train_args.yaml")
            args_sha = sha256_file(folder / "train_args.yaml")
        (folder / "config.json").write_text(cfg.model_dump_json(indent=2))
        return self.log.append({
            "event": "register", "version": version, "weights": str(dest.relative_to(self.store.root)),
            "weights_sha256": sha256_file(dest), "data_manifest_sha256": data_sha256, "config_sha256": cfg.sha256(),
            "train_args_sha256": args_sha, "gold_manifest_sha256": gold_sha256, "git_sha": git_sha(),
            "round": round_id, "parent": parent, "metrics": metrics, "notes": notes,
        })

    def _require(self, version: str) -> dict:
        models = self.models()
        if version not in models:
            raise RegistryError(f"unknown model version {version!r}")
        return models[version]

    def promote(self, version: str, gate: dict, actor: str) -> dict:
        self._require(version)
        return self.log.append({"event": "promote", "version": version, "gate": gate, "actor": actor})

    def reject(self, version: str, gate: dict, actor: str) -> dict:
        self._require(version)
        return self.log.append({"event": "reject", "version": version, "gate": gate, "actor": actor})

    def rollback(self, to_version: str, reason: str, actor: str) -> dict:
        """Make an earlier champion the champion again (only versions that have been champion)."""
        self._require(to_version)
        former = {e["version"] for e in self._records() if e["event"] in ("promote", "rollback")}
        if to_version not in former:
            raise RegistryError(f"{to_version} was never champion; only former champions can be restored")
        current = self.champion_version()
        if current == to_version:
            raise RegistryError(f"{to_version} is already the champion")
        return self.log.append({"event": "rollback", "version": to_version, "from": current, "reason": reason,
                                "actor": actor})

    def champion_version(self) -> str | None:
        version = None
        for e in self._records():
            if e["event"] in ("promote", "rollback"):
                version = e["version"]
        return version

    def champion(self) -> dict | None:
        version = self.champion_version()
        if version is None:
            return None
        record = self.models()[version]
        weights = self.store.root / record["weights"]
        if not weights.is_file() or sha256_file(weights) != record["weights_sha256"]:
            raise RegistryError(f"champion {version} weights are missing or modified ({weights})")
        return {**record, "weights_path": str(weights)}

    def verify(self) -> list[str]:
        problems = self.log.verify()
        if problems:
            return problems
        for version, record in self.models().items():
            weights = self.store.root / record["weights"]
            if not weights.is_file():
                problems.append(f"{version}: weights file missing")
            elif sha256_file(weights) != record["weights_sha256"]:
                problems.append(f"{version}: weights file modified")
        return problems
