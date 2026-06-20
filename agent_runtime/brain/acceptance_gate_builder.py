"""Acceptance gate builder — builds acceptance criteria per project type."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_acceptance_gates(config_path: Path | None = None) -> dict[str, Any]:
    if config_path is None:
        config_path = _default_config_path()
    if not config_path.exists():
        return {}
    import yaml

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def build_acceptance_gates(
    project_type: str,
    acceptance_gates_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the list of acceptance gates for a project type.

    Merges global_gates (applied to all) + project_type specific gates.
    """
    if acceptance_gates_config is None:
        acceptance_gates_config = load_acceptance_gates()
    gates: list[dict[str, Any]] = []
    # global gates first
    for gate in acceptance_gates_config.get("global_gates", []):
        if isinstance(gate, dict):
            gates.append(dict(gate))
    # project-type-specific gates
    pt_gates = acceptance_gates_config.get("project_type_gates", {})
    if isinstance(pt_gates, dict):
        for gate in pt_gates.get(project_type, []):
            if isinstance(gate, dict):
                gates.append(dict(gate))
    return gates


def validate_acceptance_gates_present(gates: list[dict[str, Any]]) -> list[str]:
    """Check that critical gates are configured. Returns list of issues."""
    issues: list[str] = []
    gate_ids = {gate.get("gate_id", "") for gate in gates}
    required_global = {"no_placeholder_artifacts", "evidence_exists", "human_approval"}
    missing = required_global - gate_ids
    if missing:
        issues.append(f"missing critical acceptance gates: {', '.join(sorted(missing))}")
    return issues


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "project_acceptance_gates.yml"
