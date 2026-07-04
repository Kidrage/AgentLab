"""Revision governance commands for long-running projects."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import fnmatch
import re

import typer
import yaml
from rich.console import Console


FORMAL_FACT_ROOTS = {"production", "project_brain"}


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _content_policy(root: Path) -> dict[str, Any]:
    data = _read_yaml(root / "config" / "content_project_governance.yml", {}) or {}
    return data if isinstance(data, dict) else {}


def _issue(severity: str, check: str, message: str, path: str = "") -> dict[str, str]:
    return {"severity": severity, "check": check, "message": message, "path": path}


def _revision_keywords(text: str) -> bool:
    return bool(re.search(
        r"(change|revise|modify|rewrite|adjust|\u89d2\u8272|\u8bbe\u5b9a|\u5927\u7eb2|\u6587\u98ce|\u4fee\u6539|\u91cd\u5199|\u8c03\u6574)",
        text,
        re.I,
    ))


def run_governance_doctor(root: Path, project: str) -> dict[str, Any]:
    root = Path(root)
    policy = _content_policy(root)
    project_root = root / "projects" / project
    active = project in {str(item) for item in policy.get("active_projects") or []}
    legacy_patterns = [str(item) for item in policy.get("legacy_fact_dir_patterns") or ["*_rebuild", "*legacy*"]]
    formal_roots = {str(item) for item in policy.get("formal_fact_roots") or FORMAL_FACT_ROOTS}
    issues: list[dict[str, str]] = []

    if not project_root.exists():
        issues.append(_issue("error", "project_exists", f"project does not exist: {project}", str(project_root)))
        return {"status": "fail", "project": project, "active_content_project": active, "issue_count": len(issues), "issues": issues}

    if not active:
        issues.append(_issue("warning", "active_content_project", "project is not listed as active content governance project"))

    policy_path = project_root / "project_brain" / "artifact_version_policy.yml"
    version_policy = _read_yaml(policy_path, {}) or {}
    registered_legacy = {
        str(item.get("path") or item.get("dir") if isinstance(item, dict) else item).strip("/")
        for key in ("legacy_dirs", "archive_dirs", "candidate_dirs")
        for item in (version_policy.get(key) or [])
    }
    for child in sorted(project_root.iterdir()):
        if not child.is_dir():
            continue
        if any(fnmatch.fnmatch(child.name, pattern) for pattern in legacy_patterns) and child.name not in registered_legacy:
            issues.append(_issue("warning", "legacy_fact_dir", f"unregistered legacy/rebuild directory: {child.name}", str(child.relative_to(root))))

    index_path = project_root / "project_artifact_index.yml"
    index = _read_yaml(index_path, {}) or {}
    if not index_path.exists():
        issues.append(_issue("warning", "artifact_index_present", "project_artifact_index.yml is missing", str(index_path.relative_to(root))))

    current_by_id: dict[str, list[dict[str, Any]]] = {}
    for record in index.get("artifacts") or []:
        if not isinstance(record, dict) or record.get("status") != "current":
            continue
        artifact_id = str(record.get("artifact_id") or "")
        current_by_id.setdefault(artifact_id, []).append(record)
        production_path = str(record.get("production_path") or "")
        first_part = Path(production_path).parts[:1]
        if first_part and first_part[0] not in formal_roots:
            issues.append(_issue("error", "current_formal_fact_root", f"current artifact points outside formal fact roots: {artifact_id}", production_path))
        if any(fnmatch.fnmatch(part, pattern) for part in Path(production_path).parts for pattern in legacy_patterns):
            issues.append(_issue("error", "current_legacy_fact_root", f"current artifact points at legacy/rebuild path: {artifact_id}", production_path))
    for artifact_id, records in current_by_id.items():
        if len(records) > 1:
            issues.append(_issue("error", "single_current_artifact", f"artifact has multiple current versions: {artifact_id}"))

    brain = project_root / "project_brain"
    for filename in ("project_fact_events.jsonl", "project_fact_snapshot.yml"):
        if not (brain / filename).exists():
            issues.append(_issue("warning", "fact_state_present", f"missing project_brain/{filename}", str((brain / filename).relative_to(root))))

    runs_dir = project_root / "runs"
    if runs_dir.exists():
        for run_dir in sorted([path for path in runs_dir.iterdir() if path.is_dir()])[-20:]:
            prompt_path = run_dir / "user_request.md"
            prompt = prompt_path.read_text(encoding="utf-8", errors="replace") if prompt_path.exists() else ""
            if _revision_keywords(prompt) and not (run_dir / "change_request.yml").exists():
                issues.append(_issue("warning", "revision_change_request", "revision-like prompt has no change_request.yml", str(run_dir.relative_to(root))))
            if (run_dir / "change_request.yml").exists() and not (run_dir / "state_transition_proposal.yml").exists():
                issues.append(_issue("warning", "state_transition_proposal", "change_request.yml has no state_transition_proposal.yml", str(run_dir.relative_to(root))))

    status = "fail" if any(issue["severity"] == "error" for issue in issues) else "pass"
    return {"status": status, "project": project, "active_content_project": active, "issue_count": len(issues), "issues": issues}


def build_revision_intake(project: str, task_id: str, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    lines = [line.strip("- *\t ") for line in prompt.splitlines() if line.strip()]
    items = [{"id": f"change_{idx:03d}", "text": line, "status": "proposed"} for idx, line in enumerate(lines or [prompt.strip()], start=1)]
    change_request = {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "created_at": now,
        "source": "user_prompt",
        "raw_prompt": prompt,
        "change_items": items,
    }
    transition = {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "created_at": now,
        "status": "proposed",
        "source_change_request": "change_request.yml",
        "events": [
            {
                "event_id": item["id"],
                "op": "propose",
                "path": "pending.user_change",
                "value": item["text"],
            }
            for item in items
        ],
        "requires_conflict_check": True,
        "requires_acceptance_before_merge": True,
    }
    return change_request, transition


def register_governance_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    governance_app = typer.Typer(help="Long-project revision governance commands.", no_args_is_help=True)

    @governance_app.command("doctor")
    def doctor(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
    ) -> None:
        """Audit long-project revision and fact-source governance."""
        result = run_governance_doctor(project_root, project)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @governance_app.command("revision-intake")
    def revision_intake(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
        prompt: str | None = typer.Option(None, "--prompt", help="Raw user revision prompt."),
        prompt_file: Path | None = typer.Option(None, "--prompt-file", exists=True, dir_okay=False, resolve_path=True),
        write: bool = typer.Option(False, "--write", help="Write change_request.yml and state_transition_proposal.yml."),
    ) -> None:
        """Convert a user revision prompt into governance lane proposal artifacts."""
        if prompt_file:
            prompt_text = prompt_file.read_text(encoding="utf-8")
        else:
            prompt_text = prompt or ""
        if not prompt_text.strip():
            console.print("[red]Provide --prompt or --prompt-file[/red]")
            raise typer.Exit(code=1)
        change_request, transition = build_revision_intake(project, task_id, prompt_text)
        if write:
            run_dir = project_root / "projects" / project / "runs" / task_id
            _write_yaml(run_dir / "change_request.yml", change_request)
            _write_yaml(run_dir / "state_transition_proposal.yml", transition)
        console.print(yaml.safe_dump({"change_request": change_request, "state_transition_proposal": transition}, sort_keys=False, allow_unicode=True).rstrip())

    app.add_typer(governance_app, name="governance")
