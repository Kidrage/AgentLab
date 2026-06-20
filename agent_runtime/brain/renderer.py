"""Renderer — writes mission contract outputs as YAML and Markdown files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


def render_mission_contract_outputs(contract: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    """Write all mission contract outputs to out_dir.

    Creates:
      - mission_contract.yml
      - intent_summary.md
      - required_capabilities.yml
      - artifact_contracts.yml
      - acceptance_gates.yml
      - risk_flags.yml
      - decision_cards/

    Returns a dict mapping artifact name to path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    # 1. mission_contract.yml
    contract_path = out_dir / "mission_contract.yml"
    atomic_write_yaml(contract_path, contract)
    written["mission_contract"] = contract_path

    # 2. intent_summary.md
    intent_path = out_dir / "intent_summary.md"
    intent_md = _render_intent_summary_md(contract)
    atomic_write_text(intent_path, intent_md)
    written["intent_summary"] = intent_path

    # 3. required_capabilities.yml
    caps_path = out_dir / "required_capabilities.yml"
    atomic_write_yaml(caps_path, {
        "required": contract.get("required_capabilities", []),
        "project_type": contract.get("project_type"),
        "is_long_project": contract.get("is_long_project"),
    })
    written["required_capabilities"] = caps_path

    # 4. artifact_contracts.yml
    artifacts_path = out_dir / "artifact_contracts.yml"
    atomic_write_yaml(artifacts_path, {
        "targets": contract.get("required_artifacts", []),
        "project_type": contract.get("project_type"),
    })
    written["artifact_contracts"] = artifacts_path

    # 5. acceptance_gates.yml
    gates_path = out_dir / "acceptance_gates.yml"
    atomic_write_yaml(gates_path, {
        "gates": contract.get("acceptance_gates", []),
        "project_type": contract.get("project_type"),
    })
    written["acceptance_gates"] = gates_path

    # 6. risk_flags.yml
    risks_path = out_dir / "risk_flags.yml"
    atomic_write_yaml(risks_path, {
        "risk_flags": contract.get("risk_flags", []),
        "non_goals": contract.get("non_goals", []),
        "hard_constraints": contract.get("hard_constraints", []),
        "unknowns": contract.get("unknowns", []),
        "assumptions": contract.get("assumptions", []),
    })
    written["risk_flags"] = risks_path

    # 7. decision_cards/ directory
    dc_dir = out_dir / "decision_cards"
    dc_dir.mkdir(exist_ok=True)
    written["decision_cards_dir"] = dc_dir

    return written


def _render_intent_summary_md(contract: dict[str, Any]) -> str:
    lines = [
        f"# Intent Summary",
        "",
        f"- **Task type:** {contract.get('task_type', 'unknown')}",
        f"- **Project type:** {contract.get('project_type', 'unknown')}",
        f"- **Long project:** {contract.get('is_long_project', False)}",
        f"- **Estimated scale:** {contract.get('estimated_scale', 'unknown')}",
        f"- **User goal:** {contract.get('user_goal', '')}",
        "",
        "## Summary",
        "",
        str(contract.get("intent_summary", "")),
        "",
        "## Required Capabilities",
        "",
    ]
    for cap in contract.get("required_capabilities", []):
        lines.append(f"- {cap}")
    lines.append("")
    lines.append("## Risk Flags")
    lines.append("")
    for flag in contract.get("risk_flags", []):
        lines.append(f"- {flag}")
    if contract.get("non_goals"):
        lines.append("")
        lines.append("## Non-Goal Patterns Detected")
        for ng in contract["non_goals"]:
            lines.append(f"- {ng}")
    lines.append("")
    lines.append("## Decision Cards")
    for dc in contract.get("decision_cards", []):
        lines.append(f"- {dc}")
    lines.append("")
    return "\n".join(lines) + "\n"
