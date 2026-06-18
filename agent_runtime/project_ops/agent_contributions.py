"""Agent contribution summaries for ProjectOps observability."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


def contribution_path(project_root: Path, task_id: str) -> Path:
    return project_root / "agents" / f"{task_id}_agent_contributions.yml"


def load_agent_contributions(project_root: Path, task_id: str) -> dict[str, Any]:
    path = contribution_path(project_root, task_id)
    if not path.exists():
        return {"project_id": project_root.name, "task_id": task_id, "agents": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"project_id": project_root.name, "task_id": task_id, "agents": []}


def record_agent_contribution(project_root: Path, task_id: str, contribution: dict[str, Any]) -> dict[str, Any]:
    path = contribution_path(project_root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_agent_contributions(project_root, task_id)
    existing = [entry for entry in data.get("agents", []) if entry.get("agent_id") != contribution.get("agent_id")]
    existing.append(contribution)
    data["project_id"] = project_root.name
    data["task_id"] = task_id
    data["agents"] = existing
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return data


def summarize_agent_contributions(project_root: Path, task_id: str) -> dict[str, Any]:
    data = load_agent_contributions(project_root, task_id)
    by_role: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    total_input = 0
    total_output = 0
    total_cost = 0.0
    cost_known = False
    for entry in data.get("agents", []):
        by_role[str(entry.get("role", "unknown"))] += 1
        by_status[str(entry.get("status", "unknown"))] += 1
        cost = entry.get("cost", {}) or {}
        total_input += int(cost.get("estimated_input_tokens") or 0)
        total_output += int(cost.get("estimated_output_tokens") or 0)
        if cost.get("estimated_cost_usd") is not None:
            cost_known = True
            total_cost += float(cost.get("estimated_cost_usd") or 0.0)
    return {
        "project_id": data.get("project_id", project_root.name),
        "task_id": task_id,
        "agent_count": len(data.get("agents", [])),
        "by_role": dict(by_role),
        "by_status": dict(by_status),
        "estimated_input_tokens": total_input,
        "estimated_output_tokens": total_output,
        "estimated_cost_usd": total_cost if cost_known else None,
    }


def render_agent_contribution_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Agent Contribution Summary",
        "",
        f"- Project: `{summary.get('project_id')}`",
        f"- Task: `{summary.get('task_id')}`",
        f"- Agent count: {summary.get('agent_count')}",
        f"- Estimated input tokens: {summary.get('estimated_input_tokens')}",
        f"- Estimated output tokens: {summary.get('estimated_output_tokens')}",
        f"- Estimated cost USD: {summary.get('estimated_cost_usd')}",
        "",
        "## By Role",
        "",
    ]
    lines.extend(f"- {role}: {count}" for role, count in summary.get("by_role", {}).items())
    lines.extend(["", "## By Status", ""])
    lines.extend(f"- {status}: {count}" for status, count in summary.get("by_status", {}).items())
    lines.append("")
    return "\n".join(lines)
