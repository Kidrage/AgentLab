"""Lossless, hash-gated retention for Task Runtime v2 attempt logs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from agent_runtime.atomic_io import atomic_write_yaml

from .runtime import TaskRuntime, TaskRuntimeError


class RetentionPlanChanged(TaskRuntimeError):
    """Attempt logs changed after the operator previewed compaction."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AttemptLogRetention:
    """Replace old raw logs with verified gzip equivalents; never purge evidence."""

    def __init__(self, agentlab_root: Path, *, project: str) -> None:
        self.root = Path(agentlab_root).resolve(strict=False)
        self.runtime = TaskRuntime(self.root, project=project)
        self.project = self.runtime.project

    def plan(
        self,
        *,
        now: datetime | None = None,
        older_than_days: int = 7,
    ) -> dict[str, Any]:
        if older_than_days < 1:
            raise ValueError("older_than_days must be at least 1")
        observed_at = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        cutoff = observed_at - timedelta(days=older_than_days)
        candidates: list[dict[str, Any]] = []
        if self.runtime.tasks_root.is_dir():
            for task_dir in sorted(
                path for path in self.runtime.tasks_root.iterdir() if path.is_dir()
            ):
                logs_root = task_dir / "attempt_logs"
                if not logs_root.is_dir():
                    continue
                for path in sorted(logs_root.rglob("*")):
                    if (
                        not path.is_file()
                        or path.is_symlink()
                        or path.suffix == ".gz"
                        or path.suffix not in {".log", ".txt", ".stdout", ".stderr"}
                    ):
                        continue
                    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                    if modified > cutoff:
                        continue
                    target = path.with_name(path.name + ".gz")
                    candidates.append(
                        {
                            "path": path.relative_to(self.root).as_posix(),
                            "target": target.relative_to(self.root).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "size_bytes": path.stat().st_size,
                            "modified_at": modified.isoformat(),
                            "target_exists": target.exists(),
                        }
                    )
        hash_basis = {
            "schema_version": "task-runtime-log-compaction-plan/v2",
            "project": self.project,
            "older_than_days": older_than_days,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
        return {
            **hash_basis,
            "observed_at": observed_at.isoformat(),
            "cutoff": cutoff.isoformat(),
            "plan_hash": hashlib.sha256(
                _canonical(hash_basis).encode("utf-8")
            ).hexdigest(),
        }

    def apply(
        self,
        *,
        expected_plan_hash: str,
        now: datetime | None = None,
        older_than_days: int = 7,
    ) -> dict[str, Any]:
        plan = self.plan(now=now, older_than_days=older_than_days)
        if plan["plan_hash"] != expected_plan_hash:
            raise RetentionPlanChanged(
                "attempt log compaction preview changed; approve a new plan"
            )
        if any(item["target_exists"] for item in plan["candidates"]):
            raise RetentionPlanChanged("a gzip target already exists; refusing to overwrite it")
        compressed_entries: list[dict[str, Any]] = []
        for item in plan["candidates"]:
            source = self.root / item["path"]
            target = self.root / item["target"]
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise RetentionPlanChanged(f"source changed during apply: {item['path']}")
            compressed = gzip.compress(raw, mtime=0)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            temp = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(compressed)
                    handle.flush()
                    os.fsync(handle.fileno())
                if gzip.decompress(temp.read_bytes()) != raw:
                    raise TaskRuntimeError(f"gzip verification failed: {item['path']}")
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            source.unlink()
            compressed_entries.append(
                {
                    **item,
                    "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
                    "compressed_size_bytes": len(compressed),
                }
            )
        receipt_root = (
            self.runtime.tasks_root.parent / "retention" / "receipts"
        )
        receipt_path = receipt_root / f"{plan['plan_hash']}.yml"
        receipt = {
            "schema_version": "task-runtime-log-compaction-receipt/v2",
            "project": self.project,
            "plan_hash": plan["plan_hash"],
            "compressed_count": len(compressed_entries),
            "compressed": compressed_entries,
            "deleted_without_replacement": [],
            "retention": "permanent-compressed-log",
        }
        atomic_write_yaml(receipt_path, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}
