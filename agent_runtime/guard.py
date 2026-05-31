"""AgentLab Guard — file locks, heartbeats, and crash recovery.

Provides safe concurrent access control so that the same project/task
cannot be written by two agents simultaneously, and so that stale locks
from crashed processes can be detected and recovered.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from atomic_io import atomic_write_text, atomic_write_yaml

# ── defaults ──────────────────────────────────────────────────────────────

LOCK_TIMEOUT_SECONDS = 120       # stale if no heartbeat for this long
HEARTBEAT_INTERVAL_SECONDS = 15  # how often to write heartbeat


def _runtime_dir(agentlab_root: Path) -> Path:
    return agentlab_root / ".agentlab_runtime"


def _locks_dir(agentlab_root: Path) -> Path:
    return _runtime_dir(agentlab_root) / "locks"


def _heartbeat_dir(agentlab_root: Path) -> Path:
    return _runtime_dir(agentlab_root) / "heartbeats"


def _tx_dir(agentlab_root: Path) -> Path:
    return _runtime_dir(agentlab_root) / "transactions"


def _lock_path(agentlab_root: Path, project: str, task_id: str) -> Path:
    key = f"{project}__{task_id}"
    return _locks_dir(agentlab_root) / f"{key}.lock"


def _heartbeat_path(agentlab_root: Path, project: str, task_id: str) -> Path:
    key = f"{project}__{task_id}"
    return _heartbeat_dir(agentlab_root) / f"{key}.heartbeat"


def _tx_path(agentlab_root: Path, tx_id: str) -> Path:
    return _tx_dir(agentlab_root) / f"{tx_id}.json"


# ── lock primitives ───────────────────────────────────────────────────────


def acquire_lock(
    agentlab_root: Path,
    project: str,
    task_id: str,
    *,
    timeout: int = LOCK_TIMEOUT_SECONDS,
) -> str:
    """Acquire exclusive lock. Returns transaction id. Raises RuntimeError if locked."""
    lock_p = _lock_path(agentlab_root, project, task_id)
    lock_p.parent.mkdir(parents=True, exist_ok=True)

    if lock_p.exists():
        # check if stale
        data = json.loads(lock_p.read_text(encoding="utf-8"))
        hb_p = Path(data["heartbeat_path"])
        if hb_p.exists():
            hb = json.loads(hb_p.read_text(encoding="utf-8"))
            age = time.time() - hb.get("ts", 0)
            if age < timeout:
                raise RuntimeError(
                    f"Lock held by tx={data['tx_id']} (heartbeat age={int(age)}s < timeout={timeout}s). "
                    f"Stale locks older than {timeout}s are auto-cleared."
                )

    tx_id = uuid4().hex[:12]
    _heartbeat_dir(agentlab_root).mkdir(parents=True, exist_ok=True)
    hb_p = _heartbeat_path(agentlab_root, project, task_id)
    hb_p.write_text(json.dumps({"tx_id": tx_id, "ts": time.time()}), encoding="utf-8")

    lock_data = {
        "tx_id": tx_id,
        "heartbeat_path": str(hb_p),
        "locked_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_p.write_text(json.dumps(lock_data), encoding="utf-8")

    # create transaction record
    _tx_dir(agentlab_root).mkdir(parents=True, exist_ok=True)
    tx_p = _tx_path(agentlab_root, tx_id)
    tx_p.write_text(
        json.dumps(
            {
                "tx_id": tx_id,
                "project": project,
                "task_id": task_id,
                "status": "active",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return tx_id


def update_heartbeat(agentlab_root: Path, project: str, task_id: str) -> None:
    """Write a heartbeat timestamp (non-blocking, no lock needed)."""
    hb_p = _heartbeat_path(agentlab_root, project, task_id)
    hb_p.parent.mkdir(parents=True, exist_ok=True)
    hb_p.write_text(
        json.dumps({"ts": time.time(), "at": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )


def release_lock(agentlab_root: Path, project: str, task_id: str) -> None:
    """Release the lock and mark transaction as completed."""
    lock_p = _lock_path(agentlab_root, project, task_id)
    if lock_p.exists():
        data = json.loads(lock_p.read_text(encoding="utf-8"))
        tx_id = data.get("tx_id", "")
        tx_p = _tx_path(agentlab_root, tx_id)
        if tx_p.exists():
            tx_data = json.loads(tx_p.read_text(encoding="utf-8"))
            tx_data["status"] = "completed"
            tx_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            tx_p.write_text(json.dumps(tx_data), encoding="utf-8")
        lock_p.unlink(missing_ok=True)


# ── recovery scanning ─────────────────────────────────────────────────────


def scan_stale_locks(agentlab_root: Path, *, timeout: int = LOCK_TIMEOUT_SECONDS) -> list[dict]:
    """Scan for stale locks and return recovery info for each."""
    locks_d = _locks_dir(agentlab_root)
    results: list[dict] = []
    if not locks_d.exists():
        return results

    for lock_f in sorted(locks_d.glob("*.lock")):
        try:
            data = json.loads(lock_f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            results.append(
                {
                    "lock_file": str(lock_f),
                    "state": "corrupt_lock",
                    "recommended_action": "remove_lock_manually",
                }
            )
            continue

        hb_p = Path(data.get("heartbeat_path", ""))
        hb_age = -1
        if hb_p.exists():
            try:
                hb = json.loads(hb_p.read_text(encoding="utf-8"))
                hb_age = int(time.time() - hb.get("ts", 0))
            except (json.JSONDecodeError, OSError):
                pass

        tx_id = data.get("tx_id", "unknown")
        tx_p = _tx_path(agentlab_root, tx_id)
        tx_status = "unknown"
        if tx_p.exists():
            try:
                tx = json.loads(tx_p.read_text(encoding="utf-8"))
                tx_status = tx.get("status", "unknown")
            except (json.JSONDecodeError, OSError):
                pass

        is_stale = hb_age < 0 or hb_age >= timeout

        result = {
            "lock_file": str(lock_f),
            "tx_id": tx_id,
            "tx_status": tx_status,
            "heartbeat_age_seconds": hb_age if hb_age >= 0 else None,
            "is_stale": is_stale,
            "state": "stale" if is_stale else "active",
            "recommended_action": (
                "recover_possible" if is_stale else "wait_or_force_clear"
            ),
        }
        results.append(result)

    return results


def clear_stale_lock(agentlab_root: Path, project: str, task_id: str) -> bool:
    """Remove a stale lock file. Returns True if lock was cleared."""
    lock_p = _lock_path(agentlab_root, project, task_id)
    if lock_p.exists():
        lock_p.unlink()
        return True
    return False