"""Project manifest and invocation routing helpers."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .models import ProjectInitResult, ProjectRouteDecision

DEFAULT_PROJECT_BRAIN_FILES = {
    "product_vision.md": "# Product Vision\n\nTBD\n",
    "roadmap.yml": "milestones: []\n",
    "decision_log.yml": "decisions: []\n",
    "acceptance_history.yml": "entries: []\n",
    "unresolved_questions.yml": "questions: []\n",
    "known_risks.yml": "risks: []\n",
    "architecture_state.yml": "modules: []\n",
    "next_actions.yml": "actions: []\n",
    "memory_index.yml": "memories: []\n",
}

PROJECT_DIRS = [
    "project_brain",
    "tasks/active",
    "tasks/closed",
    "tasks/compacted",
    "tasks/archived",
    "agents",
    "artifacts",
    "acceptance",
    "cost",
]


def slugify_project_id(text: str, prefix: str = "project") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        return prefix
    if len(slug) > 48:
        slug = slug[:48].rstrip("-")
    return f"{prefix}_{slug}" if not slug.startswith(prefix) else slug


def load_project_routing_policy(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "config" / "project_routing.yml"
    if not path.exists():
        return {
            "routing": {
                "reserved_self_projects": ["AgentLab"],
                "self_development_signals": ["AgentLab", "this repo", "这个仓库", "修仓库", "mainline", "主线修复"],
                "create_new_project_by_default_for": [
                    "creative_longform",
                    "research_investigation",
                    "business_strategy",
                    "product_design",
                    "document_processing",
                    "audio_music",
                    "multimodal_vision",
                ],
                "require_confirmation_when_ambiguous": True,
            }
        }
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _goal_text(mission_contract: dict[str, Any]) -> str:
    parts = [
        str(mission_contract.get("user_goal") or ""),
        str(mission_contract.get("intent_summary") or ""),
        str(mission_contract.get("task_type") or ""),
        str(mission_contract.get("domain") or ""),
    ]
    return " ".join(parts)


def route_invocation_to_project(
    mission_contract: dict[str, Any],
    existing_projects: list[dict[str, Any]] | None,
    policy: dict[str, Any],
) -> ProjectRouteDecision:
    """Deterministically route a mission contract to a project boundary."""

    routing = policy.get("routing", {})
    existing_projects = existing_projects or []
    explicit_project = mission_contract.get("project_id") or mission_contract.get("project")
    if explicit_project:
        for project in existing_projects:
            if project.get("project_id") == explicit_project:
                return ProjectRouteDecision(
                    outcome="attach_existing_project",
                    project_id=str(explicit_project),
                    project_type=str(project.get("project_type", "user_project")),
                    reason="Mission contract explicitly names an existing project.",
                )
        return ProjectRouteDecision(
            outcome="create_new_project",
            project_id=str(explicit_project),
            project_type=str(mission_contract.get("project_type", "user_project")),
            reason="Mission contract explicitly names a project that does not exist yet.",
            suggested_project_id=str(explicit_project),
        )

    text = _goal_text(mission_contract)
    for signal in routing.get("self_development_signals", []):
        if signal and signal.lower() in text.lower():
            return ProjectRouteDecision(
                outcome="self_development_project",
                project_id="AgentLab",
                project_type="self_development",
                reason=f"Matched self-development signal: {signal}",
            )

    task_type = str(mission_contract.get("task_type") or mission_contract.get("domain") or "unknown")
    create_new_types = set(routing.get("create_new_project_by_default_for", []))
    if task_type in create_new_types:
        suggested = slugify_project_id(str(mission_contract.get("user_goal") or task_type), prefix=task_type.split("_")[0])
        return ProjectRouteDecision(
            outcome="create_new_project",
            project_id=suggested,
            project_type="user_project",
            reason=f"Task type `{task_type}` should not be attached to AgentLab self-development by default.",
            suggested_project_id=suggested,
        )

    if routing.get("require_confirmation_when_ambiguous", True):
        return ProjectRouteDecision(
            outcome="ambiguous_requires_user_decision",
            project_id=None,
            project_type="unknown",
            reason="No explicit project or deterministic routing signal was found.",
            requires_user_decision=True,
        )

    return ProjectRouteDecision(
        outcome="create_new_project",
        project_id=slugify_project_id(text or "unknown", prefix="project"),
        project_type="user_project",
        reason="Safe default created a new user project.",
    )


def init_project(repo_root: Path, project_id: str, project_type: str, title: str) -> ProjectInitResult:
    """Create the standard S2.5 project directory tree."""

    project_root = repo_root / "projects" / project_id
    created: list[str] = []
    existing: list[str] = []
    for rel in PROJECT_DIRS:
        path = project_root / rel
        if path.exists():
            existing.append(str(path))
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))

    manifest = {
        "project_id": project_id,
        "display_name": title,
        "project_type": project_type,
        "status": "active",
        "root_path": f"projects/{project_id}",
        "created_at": None,
        "updated_at": None,
        "mission_summary": "",
        "owner": "user",
        "memory_policy": {
            "compaction_enabled": True,
            "promote_decisions_to_project_brain": True,
        },
        "task_policy": {
            "default_task_state": "active",
            "auto_compact_on_close": True,
        },
    }
    manifest_path = project_root / "project.yml"
    if manifest_path.exists():
        existing.append(str(manifest_path))
    else:
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
        created.append(str(manifest_path))

    brain_root = project_root / "project_brain"
    for name, content in DEFAULT_PROJECT_BRAIN_FILES.items():
        path = brain_root / name
        if path.exists():
            existing.append(str(path))
        else:
            path.write_text(content, encoding="utf-8")
            created.append(str(path))

    return ProjectInitResult(project_id=project_id, root_path=str(project_root), created_paths=created, existing_paths=existing)


def load_project_manifest(repo_root: Path, project_id: str) -> dict[str, Any]:
    path = repo_root / "projects" / project_id / "project.yml"
    if not path.exists():
        raise FileNotFoundError(f"Project manifest not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def project_status(repo_root: Path, project_id: str) -> dict[str, Any]:
    project_root = repo_root / "projects" / project_id
    manifest = load_project_manifest(repo_root, project_id)
    tasks_root = project_root / "tasks"
    counts = {}
    for state in ["active", "closed", "compacted", "archived"]:
        state_dir = tasks_root / state
        counts[state] = len([p for p in state_dir.iterdir() if p.is_dir()]) if state_dir.exists() else 0

    brain_root = project_root / "project_brain"

    def read_yaml_list(name: str, key: str) -> list[Any]:
        path = brain_root / name
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get(key, []))

    return {
        "project": manifest,
        "task_counts": counts,
        "unresolved_questions": read_yaml_list("unresolved_questions.yml", "questions"),
        "known_risks": read_yaml_list("known_risks.yml", "risks"),
        "next_actions": read_yaml_list("next_actions.yml", "actions"),
    }


def render_project_status(status: dict[str, Any]) -> str:
    project = status.get("project", {})
    lines = [
        "# Project Status",
        "",
        f"- Project: `{project.get('project_id', '')}`",
        f"- Display name: {project.get('display_name', '')}",
        f"- Type: `{project.get('project_type', '')}`",
        f"- Status: `{project.get('status', '')}`",
        "",
        "## Task Counts",
        "",
    ]
    for state, count in status.get("task_counts", {}).items():
        lines.append(f"- {state}: {count}")
    lines.extend(["", "## Known Risks", ""])
    risks = status.get("known_risks", [])
    lines.extend([f"- {risk}" for risk in risks] or ["No known risks recorded."])
    lines.extend(["", "## Next Actions", ""])
    actions = status.get("next_actions", [])
    lines.extend([f"- {action}" for action in actions] or ["No next actions recorded."])
    lines.append("")
    return "\n".join(lines)


def route_decision_to_dict(decision: ProjectRouteDecision) -> dict[str, Any]:
    return asdict(decision)
