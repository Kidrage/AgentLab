"""Project routing and initialization helpers for AgentLab ProjectOps."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

import yaml


SELF_DEVELOPMENT_SIGNALS = {
    "agentlab",
    "projectops",
    "repo hygiene",
    "repository hygiene",
    "mainline",
    "修 agentlab",
    "修改这个仓库",
    "检查 agentlab 仓库",
    "修 projectops",
    "修 mainline",
}

TASK_TYPE_PREFIX = {
    "creative_longform": "creative",
    "research": "research",
    "research_investigation": "research",
    "business": "business",
    "business_strategy": "business",
    "document_processing": "document",
    "audio_music": "audio",
    "multimodal": "multimodal",
    "data_analysis": "data",
    "coding": "coding",
    "debugging": "coding",
    "local_ops": "ops",
    "education": "education",
}

NEW_PROJECT_TYPES = {
    "creative_longform",
    "research",
    "research_investigation",
    "business",
    "business_strategy",
    "document_processing",
    "audio_music",
    "multimodal",
    "data_analysis",
    "education",
}


@dataclass(frozen=True)
class ProjectRoute:
    action: str
    project_id: str | None
    project_type: str
    title: str
    reason: str
    confidence: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "project_id": self.project_id,
            "project_type": self.project_type,
            "title": self.title,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def _slug(text: str, *, max_length: int = 48) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-+", "-", text)
    return (text or "project")[:max_length].strip("-") or "project"


def _read_contract(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("mission contract must be a YAML mapping")
    return data


def route_invocation_to_project(contract: dict[str, Any], *, existing_projects: set[str] | None = None) -> ProjectRoute:
    existing_projects = existing_projects or set()
    explicit_project = str(
        contract.get("project_id")
        or contract.get("project")
        or contract.get("target_project")
        or ""
    ).strip()
    task_type = str(contract.get("task_type") or "unknown").strip()
    goal = str(contract.get("user_goal") or contract.get("intent_summary") or contract.get("title") or "").strip()
    title = str(contract.get("title") or contract.get("intent_summary") or goal[:80] or "Untitled Project").strip()
    goal_lower = " ".join([goal, title, task_type]).lower()

    if explicit_project:
        if explicit_project == "AgentLab" or explicit_project in existing_projects:
            return ProjectRoute(
                "attach_existing_project",
                explicit_project,
                task_type,
                title,
                "mission contract explicitly named an existing project",
                "high",
            )
        return ProjectRoute(
            "ambiguous_requires_user_decision",
            None,
            task_type,
            title,
            f"mission contract named unknown project {explicit_project!r}",
            "low",
        )

    if any(signal in goal_lower for signal in SELF_DEVELOPMENT_SIGNALS):
        return ProjectRoute(
            "self_development_project",
            "AgentLab",
            "self_development",
            title,
            "self-development signal detected",
            "high",
        )

    if task_type in NEW_PROJECT_TYPES:
        prefix = TASK_TYPE_PREFIX.get(task_type, task_type)
        return ProjectRoute(
            "create_new_project",
            f"{prefix}_{_slug(title or goal)}",
            task_type,
            title,
            f"{task_type} should not default to the AgentLab self-development project",
            "high",
        )

    if task_type in {"coding", "debugging", "local_ops"}:
        return ProjectRoute(
            "ambiguous_requires_user_decision",
            None,
            task_type,
            title,
            "coding/local-ops request lacks an explicit target repository or project",
            "medium",
        )

    return ProjectRoute(
        "ambiguous_requires_user_decision",
        None,
        task_type,
        title,
        "mission lacks enough project ownership evidence",
        "low",
    )


def route_mission_contract(path: Path, *, agentlab_root: Path) -> dict[str, Any]:
    projects_root = agentlab_root / "projects"
    existing = {item.name for item in projects_root.iterdir() if item.is_dir()} if projects_root.exists() else set()
    route = route_invocation_to_project(_read_contract(path), existing_projects=existing)
    return {
        "status": "ok",
        "mission_contract": str(path),
        "route": route.as_dict(),
    }


def init_project(agentlab_root: Path, project_id: str, project_type: str, title: str) -> dict[str, Any]:
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,80}$", project_id):
        raise ValueError(f"unsafe project_id: {project_id}")
    project_root = agentlab_root / "projects" / project_id
    project_root.mkdir(parents=True, exist_ok=True)
    for child in ["agent_docs", "runs", "artifacts"]:
        (project_root / child).mkdir(exist_ok=True)
    manifest_path = project_root / "project_manifest.yml"
    manifest = {
        "project_id": project_id,
        "project_type": project_type,
        "title": title,
        "status": "active",
        "task_lifecycle": ["active", "closed", "compacted", "archived"],
        "default_read_order": [
            "project_manifest.yml",
            "agent_docs/PROJECT_BRIEF.md",
            "agent_docs/02_TASK_LEDGER.yml",
            "runs/<task_id>/task_compact/task_summary.md",
        ],
    }
    if not manifest_path.exists():
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    brief_path = project_root / "agent_docs" / "PROJECT_BRIEF.md"
    if not brief_path.exists():
        brief_path.write_text(
            f"# {title}\n\nProject type: `{project_type}`.\n\nKeep durable facts here; keep raw task work under `runs/`.\n",
            encoding="utf-8",
        )
    ledger_path = project_root / "agent_docs" / "02_TASK_LEDGER.yml"
    if not ledger_path.exists():
        ledger_path.write_text("tasks: []\n", encoding="utf-8")
    return {
        "project_root": str(project_root),
        "manifest": str(manifest_path),
        "created": True,
    }
