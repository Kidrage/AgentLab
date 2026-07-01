"""Normalized read model for M3 Operator OS surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.operator_os.stage_scope import active_stage_scope

REQUIRED_PROJECT_BRAIN_FILES = [
    "PROJECT_HANDOFF.md",
    "project_artifact_index.yml",
    "project_fact_snapshot.yml",
    "acceptance_history.yml",
    "next_actions.yml",
]


def build_operator_state(root: Path, project: str = "AgentLab") -> dict[str, Any]:
    """Build the single read model consumed by M3 UI, TUI, CLI, and assistant modes."""
    root = root.resolve()
    project_root = root / "projects" / project
    brain_dir = project_root / "project_brain"
    acceptance_history = _load_yaml(brain_dir / "acceptance_history.yml", {"entries": []})
    history_entries = acceptance_history.get("entries") if isinstance(acceptance_history, dict) else []
    history_entries = history_entries if isinstance(history_entries, list) else []
    accepted_phase_ids = [
        str(entry.get("phase_id"))
        for entry in history_entries
        if isinstance(entry, dict) and entry.get("accepted") and entry.get("phase_id")
    ]
    latest_acceptance = next(
        (entry for entry in reversed(history_entries) if isinstance(entry, dict)),
        None,
    )
    next_action = _load_yaml(brain_dir / "next_actions.yml", {})
    fact_snapshot = _load_yaml(brain_dir / "project_fact_snapshot.yml", {})
    artifact_index = _load_yaml(project_root / "project_artifact_index.yml", {})
    missing_brain_files = [
        name
        for name in REQUIRED_PROJECT_BRAIN_FILES
        if not _brain_file_path(project_root, brain_dir, name).exists()
    ]

    return {
        "schema_version": 1,
        "stage": "M3_OPERATOR_OS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage_scope": active_stage_scope(),
        "project": {
            "id": project,
            "root": _relative_or_name(root, project_root),
            "status": _derive_project_status(brain_dir.exists(), missing_brain_files, latest_acceptance),
        },
        "source_policy": {
            "single_read_model": True,
            "progress_source": "project_brain/acceptance_history.yml + project_brain/next_actions.yml",
            "canonical_fact_source": "project_brain/project_fact_snapshot.yml",
            "artifact_current_source": "project_artifact_index.yml",
            "directory_layout_is_not_truth": True,
        },
        "project_brain": {
            "present": brain_dir.exists(),
            "path": _relative_or_name(root, brain_dir),
            "required_files": list(REQUIRED_PROJECT_BRAIN_FILES),
            "missing_files": missing_brain_files,
            "healthy": brain_dir.exists() and not missing_brain_files,
        },
        "phase_progress": {
            "accepted_phase_ids": accepted_phase_ids,
            "latest_acceptance": _compact_acceptance(latest_acceptance),
            "history_entry_count": len(history_entries),
        },
        "next_action": {
            "source": _relative_or_name(root, brain_dir / "next_actions.yml"),
            "data": next_action if isinstance(next_action, dict) else {},
        },
        "facts": {
            "source": _relative_or_name(root, brain_dir / "project_fact_snapshot.yml"),
            "event_count": fact_snapshot.get("event_count") if isinstance(fact_snapshot, dict) else None,
            "project": fact_snapshot.get("project") if isinstance(fact_snapshot, dict) else None,
        },
        "artifacts": {
            "source": _relative_or_name(root, project_root / "project_artifact_index.yml"),
            "index_present": bool(artifact_index),
        },
        "timeline": _acceptance_timeline(history_entries),
        "safety": {
            "ui_may_infer_progress_from_directories": False,
            "ui_may_write_production_content": False,
            "mutations_require_operator_action_contract": True,
        },
    }


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else default


def _brain_file_path(project_root: Path, brain_dir: Path, name: str) -> Path:
    if name == "PROJECT_HANDOFF.md":
        return project_root / name
    if name == "project_artifact_index.yml":
        return project_root / name
    return brain_dir / name


def _derive_project_status(brain_present: bool, missing_brain_files: list[str], latest_acceptance: dict[str, Any] | None) -> str:
    if not brain_present:
        return "needs_project_brain"
    if missing_brain_files:
        return "needs_operator_state_inputs"
    if latest_acceptance and not latest_acceptance.get("accepted"):
        return str(latest_acceptance.get("verdict") or "needs_attention").lower()
    return "ready"


def _compact_acceptance(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    return {
        "phase_id": entry.get("phase_id"),
        "accepted": bool(entry.get("accepted")),
        "verdict": entry.get("verdict"),
        "recommended_next_action": entry.get("recommended_next_action"),
        "evidence_files": entry.get("evidence_files") or [],
        "recorded_at": entry.get("recorded_at"),
    }


def _acceptance_timeline(entries: list[Any]) -> list[dict[str, Any]]:
    timeline = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        timeline.append(
            {
                "event_type": "phase_acceptance_recorded",
                "time": entry.get("recorded_at") or "",
                "phase_id": entry.get("phase_id"),
                "verdict": entry.get("verdict"),
                "accepted": bool(entry.get("accepted")),
                "source": "project_brain/acceptance_history.yml",
            }
        )
    return timeline


def _relative_or_name(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name
