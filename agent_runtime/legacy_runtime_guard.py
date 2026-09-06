"""Authority guard for legacy ``projects/*/runs`` mutations.

Runtime v2 uses ``projects/<project>/runtime/tasks/<task_id>`` as the canonical
Task identity. Once that identity exists, a same-named legacy run may remain on
disk for migration provenance or compatibility reads, but it must not receive
new mutable state, progress, event, decision, or watchdog activity.

This module intentionally has no Runtime imports so low-level legacy writers can
use it without creating dependency cycles.
"""

from __future__ import annotations

from pathlib import Path


class LegacyRuntimeAuthorityError(RuntimeError):
    """Raised when a legacy writer would compete with an existing v2 Task."""


def runtime_v2_identity_path(run_dir: Path) -> Path | None:
    """Return the sibling Runtime v2 identity path for a canonical legacy run.

    Non-canonical fixture/work directories are outside this authority rule and
    return ``None``. The check is deliberately lexical: a damaged or incomplete
    v2 directory is still an existing identity and therefore remains
    authoritative rather than falling back to a legacy writer.
    """

    candidate = Path(run_dir)
    runs_root = candidate.parent
    if runs_root.name != "runs":
        return None
    project_root = runs_root.parent
    if project_root.parent.name != "projects":
        return None
    task_id = candidate.name
    if not task_id:
        return None
    return project_root / "runtime" / "tasks" / task_id


def legacy_run_shadowed_by_v2(run_dir: Path) -> bool:
    """Return true when the legacy run is shadowed by an existing v2 identity."""

    v2_path = runtime_v2_identity_path(run_dir)
    return bool(v2_path is not None and v2_path.exists())


def assert_legacy_run_write_allowed(run_dir: Path, *, operation: str) -> None:
    """Fail closed if a same-named Runtime v2 Task already exists."""

    v2_path = runtime_v2_identity_path(run_dir)
    if v2_path is None or not v2_path.exists():
        return
    raise LegacyRuntimeAuthorityError(
        "legacy runtime write blocked because Task Runtime v2 is authoritative: "
        f"operation={operation}; task_id={Path(run_dir).name}"
    )
