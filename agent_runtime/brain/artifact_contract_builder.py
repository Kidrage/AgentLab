"""Artifact contract builder — builds expected artifact lists per project type and phase."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_artifact_contracts(config_path: Path | None = None) -> dict[str, Any]:
    if config_path is None:
        config_path = _default_config_path()
    if not config_path.exists():
        return {}
    import yaml

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("phase_artifacts", {}) if isinstance(data, dict) else {}


def build_artifact_contracts(
    project_type: str,
    phases: list[dict[str, Any]],
    artifact_contracts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build artifact contracts for each phase in a project workflow.

    Returns a list of {phase_id, expected_outputs, evidence_required, evidence_types}.
    """
    if artifact_contracts is None:
        artifact_contracts = load_artifact_contracts()
    result: list[dict[str, Any]] = []
    for phase in phases:
        phase_id = str(phase.get("phase_id") or phase.get("title", ""))
        contract = artifact_contracts.get(phase_id, {})
        if not isinstance(contract, dict):
            contract = {}
        result.append({
            "phase_id": phase_id,
            "expected_outputs": list(contract.get("outputs", [])),
            "evidence_required": bool(contract.get("evidence_required", False)),
            "evidence_types": list(contract.get("evidence_types", [])),
        })
    return result


def build_artifact_target_summary(
    project_type: str,
    project_types: dict[str, Any] | None = None,
) -> list[str]:
    """Return the top-level artifact targets for a project type."""
    if project_types is None:
        from agent_runtime.brain.project_type_classifier import load_project_types
        project_types = load_project_types()
    typedef = project_types.get(project_type, project_types.get("unknown_project", {}))
    return list(typedef.get("artifact_targets", []))


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "project_artifact_contracts.yml"
