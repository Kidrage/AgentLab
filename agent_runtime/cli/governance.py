"""Revision governance commands for long-running projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime, timezone
import fnmatch
import re

import typer
import yaml
from rich.console import Console

from agent_runtime.revision_governance import (
    apply_revision,
    build_revision_intake_artifacts,
    revision_dispatch_status,
    validate_revision,
    write_revision_intake,
)


FORMAL_FACT_ROOTS = {"production", "project_brain"}


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def _content_policy(root: Path) -> dict[str, Any]:
    data = _read_yaml(root / "config" / "content_project_governance.yml", {}) or {}
    return data if isinstance(data, dict) else {}


def _issue(
    severity: str,
    check: str,
    message: str,
    path: str = "",
    recommendation: str = "",
    command: str = "",
) -> dict[str, str]:
    issue = {"severity": severity, "check": check, "message": message, "path": path}
    if recommendation:
        issue["recommendation"] = recommendation
    if command:
        issue["command"] = command
    return issue


def _revision_keywords(text: str) -> bool:
    return bool(re.search(
        r"(change|revise|modify|rewrite|adjust|\u89d2\u8272|\u8bbe\u5b9a|\u5927\u7eb2|\u6587\u98ce|\u4fee\u6539|\u91cd\u5199|\u8c03\u6574)",
        text,
        re.I,
    ))


def _remediation_action(
    action_id: str,
    severity: str,
    target: str,
    reason: str,
    recommendation: str,
    command: str = "",
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "action_id": action_id,
        "severity": severity,
        "target": target,
        "reason": reason,
        "recommendation": recommendation,
        "requires_review": True,
        "destructive": False,
    }
    if command:
        action["command"] = command
    return action


def _write_governance_report(root: Path, project: str, result: dict[str, Any]) -> Path:
    report_path = root / "projects" / project / "project_brain" / "governance_migration_report.yml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return report_path


def _migration_proposal_dir(root: Path) -> Path:
    return root / ".agentlab" / "governance_migration_proposals"


def _migration_proposal_id(project: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", project).strip("_") or "project"
    return f"migration_{slug}_{stamp}"


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def propose_migration(root: Path, project: str) -> dict[str, Any]:
    """Create a review-first migration proposal from governance doctor findings."""
    root = Path(root)
    doctor = run_governance_doctor(root, project)
    proposal_id = _migration_proposal_id(project)
    actions = list(doctor.get("remediation_plan") or [])
    proposal = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "status": "pending",
        "project": project,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_doctor_status": doctor.get("status"),
        "source_issue_count": doctor.get("issue_count", 0),
        "destructive": False,
        "requires_accept": True,
        "actions": actions,
        "notes": [
            "Proposal creation does not edit production artifacts.",
            "Only apply with explicit --accept after reviewing actions.",
        ],
    }
    _write_yaml(_migration_proposal_dir(root) / f"{proposal_id}.yml", proposal)
    project_brain = root / "projects" / project / "project_brain"
    if project_brain.exists():
        _write_yaml(project_brain / "migration_proposal.yml", proposal)
    return proposal


def _task_id_from_action(action: dict[str, Any]) -> str | None:
    target = str(action.get("target") or "")
    if "/runs/" in target:
        return Path(target).name
    action_id = str(action.get("action_id") or "")
    prefix = "intake_revision_"
    if action_id.startswith(prefix):
        return action_id[len(prefix):]
    return None


def apply_migration_proposal(
    root: Path,
    proposal_id: str,
    *,
    accept: bool,
    accepted_by: str = "system",
) -> dict[str, Any]:
    root = Path(root)
    path = _migration_proposal_dir(root) / f"{proposal_id}.yml"
    proposal = _read_yaml(path, {}) or {}
    if not proposal or proposal.get("proposal_id") != proposal_id:
        return {"applied": False, "status": "unknown_proposal", "proposal_id": proposal_id}
    if not accept:
        return {"applied": False, "status": "needs_acceptance", "proposal_id": proposal_id}
    if proposal.get("status") != "pending":
        return {"applied": False, "status": "not_pending", "proposal_id": proposal_id}

    project = str(proposal.get("project") or "")
    applied_actions: list[dict[str, Any]] = []
    skipped_actions: list[dict[str, Any]] = []
    for action in proposal.get("actions") or []:
        if not isinstance(action, dict):
            continue
        if not str(action.get("action_id") or "").startswith("intake_revision_"):
            skipped_actions.append({"action_id": action.get("action_id"), "reason": "manual review action"})
            continue
        task_id = _task_id_from_action(action)
        prompt_path = root / "projects" / project / "runs" / str(task_id) / "user_request.md" if task_id else None
        if not task_id or prompt_path is None or not prompt_path.exists():
            skipped_actions.append({"action_id": action.get("action_id"), "reason": "missing user_request.md"})
            continue
        prompt = prompt_path.read_text(encoding="utf-8", errors="replace")
        result = write_revision_intake(root, project, task_id, prompt)
        applied_actions.append({"action_id": action.get("action_id"), "task_id": task_id, "result": result})

    proposal["status"] = "applied"
    proposal["applied_at"] = datetime.now(timezone.utc).isoformat()
    proposal["accepted_by"] = accepted_by
    proposal["applied_actions"] = applied_actions
    proposal["skipped_actions"] = skipped_actions
    _write_yaml(path, proposal)
    project_brain = root / "projects" / project / "project_brain"
    if project_brain.exists():
        _write_yaml(project_brain / "migration_proposal.yml", proposal)
    return {
        "applied": True,
        "status": "applied",
        "proposal_id": proposal_id,
        "applied_action_count": len(applied_actions),
        "skipped_action_count": len(skipped_actions),
    }


def run_governance_doctor(root: Path, project: str) -> dict[str, Any]:
    root = Path(root)
    policy = _content_policy(root)
    project_root = root / "projects" / project
    active = project in {str(item) for item in policy.get("active_projects") or []}
    legacy_patterns = [str(item) for item in policy.get("legacy_fact_dir_patterns") or ["*_rebuild", "*legacy*"]]
    formal_roots = {str(item) for item in policy.get("formal_fact_roots") or FORMAL_FACT_ROOTS}
    issues: list[dict[str, str]] = []
    remediation_plan: list[dict[str, Any]] = []
    migration_report: dict[str, Any] = {
        "safe_by_default": True,
        "project_root": str(project_root.relative_to(root)) if project_root.exists() else str(project_root),
        "legacy_directories": [],
        "current_artifact_groups": [],
        "pending_revision_runs": [],
        "missing_fact_files": [],
        "notes": [
            "This report proposes migration work only; it does not delete or move project artifacts.",
            "Canonical facts remain project_fact_events.jsonl, project_fact_snapshot.yml, project_artifact_index.yml, and production/**.",
        ],
    }

    if not project_root.exists():
        issues.append(_issue(
            "error",
            "project_exists",
            f"project does not exist: {project}",
            str(project_root),
            "Create the project or rerun the doctor with the intended project name.",
        ))
        return {
            "status": "fail",
            "project": project,
            "active_content_project": active,
            "issue_count": len(issues),
            "issues": issues,
            "migration_report": migration_report,
            "remediation_plan": remediation_plan,
        }

    if not active:
        issues.append(_issue(
            "warning",
            "active_content_project",
            "project is not listed as active content governance project",
            recommendation="Add the project to config/content_project_governance.yml before treating doctor output as authoritative.",
        ))
        remediation_plan.append(_remediation_action(
            "register_active_content_project",
            "warning",
            "config/content_project_governance.yml",
            "Project is not covered by active long-project governance policy.",
            "Review the project and add it to active_projects if it should be governed.",
        ))

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
            rel = str(child.relative_to(root))
            migration_report["legacy_directories"].append({
                "path": rel,
                "registered": False,
                "risk": "directory may be mistaken for canonical project facts",
            })
            issues.append(_issue(
                "warning",
                "legacy_fact_dir",
                f"unregistered legacy/rebuild directory: {child.name}",
                rel,
                "Register it as legacy/archive/candidate material or promote selected facts through project_artifact_index.yml.",
            ))
            remediation_plan.append(_remediation_action(
                f"review_legacy_dir_{child.name}",
                "warning",
                rel,
                "Unregistered rebuild/legacy directory exists beside canonical project sources.",
                "Inventory useful files, promote only accepted artifacts to production/**, and register the old directory as legacy evidence.",
            ))

    index_path = project_root / "project_artifact_index.yml"
    index = _read_yaml(index_path, {}) or {}
    if not index_path.exists():
        rel = str(index_path.relative_to(root))
        issues.append(_issue(
            "warning",
            "artifact_index_present",
            "project_artifact_index.yml is missing",
            rel,
            "Create a project_artifact_index.yml before promoting or replacing formal artifacts.",
        ))
        remediation_plan.append(_remediation_action(
            "create_artifact_index",
            "warning",
            rel,
            "No artifact index exists, so current production artifacts cannot be audited reliably.",
            "Create project_artifact_index.yml with exactly one current entry per artifact_id.",
        ))

    current_by_id: dict[str, list[dict[str, Any]]] = {}
    for record in index.get("artifacts") or []:
        if not isinstance(record, dict) or record.get("status") != "current":
            continue
        artifact_id = str(record.get("artifact_id") or "")
        current_by_id.setdefault(artifact_id, []).append(record)
        production_path = str(record.get("production_path") or "")
        first_part = Path(production_path).parts[:1]
        if first_part and first_part[0] not in formal_roots:
            issues.append(_issue(
                "error",
                "current_formal_fact_root",
                f"current artifact points outside formal fact roots: {artifact_id}",
                production_path,
                "Move or re-promote the current artifact into a formal root before dispatching Writer/Coder work.",
            ))
            remediation_plan.append(_remediation_action(
                f"rehome_current_artifact_{artifact_id}",
                "error",
                production_path,
                "A current artifact points outside production/** or project_brain/**.",
                "Create an artifact promotion plan that archives the old current path and promotes a formal production path.",
            ))
        if any(fnmatch.fnmatch(part, pattern) for part in Path(production_path).parts for pattern in legacy_patterns):
            issues.append(_issue(
                "error",
                "current_legacy_fact_root",
                f"current artifact points at legacy/rebuild path: {artifact_id}",
                production_path,
                "Do not use rebuild or legacy directories as current truth; re-promote the accepted artifact into production/**.",
            ))
            remediation_plan.append(_remediation_action(
                f"retire_legacy_current_artifact_{artifact_id}",
                "error",
                production_path,
                "A current artifact still points at a rebuild or legacy path.",
                "Promote the accepted content into a stable production/** path and mark the legacy path archived or superseded.",
            ))
    for artifact_id, records in current_by_id.items():
        migration_report["current_artifact_groups"].append({
            "artifact_id": artifact_id,
            "current_count": len(records),
            "production_paths": [str(record.get("production_path") or "") for record in records],
        })
        if len(records) > 1:
            issues.append(_issue(
                "error",
                "single_current_artifact",
                f"artifact has multiple current versions: {artifact_id}",
                recommendation="Choose one current artifact, archive/supersede the others, then update project_artifact_index.yml.",
            ))
            remediation_plan.append(_remediation_action(
                f"dedupe_current_artifact_{artifact_id}",
                "error",
                "project_artifact_index.yml",
                f"Artifact {artifact_id} has {len(records)} current entries.",
                "Pick the accepted current version and mark older versions superseded or archived with lineage.",
            ))

    brain = project_root / "project_brain"
    for filename in ("project_fact_events.jsonl", "project_fact_snapshot.yml"):
        if not (brain / filename).exists():
            rel = str((brain / filename).relative_to(root))
            migration_report["missing_fact_files"].append(rel)
            issues.append(_issue(
                "warning",
                "fact_state_present",
                f"missing project_brain/{filename}",
                rel,
                "Initialize fact events and snapshot before relying on revision governance.",
            ))
            remediation_plan.append(_remediation_action(
                f"initialize_{Path(filename).stem}",
                "warning",
                rel,
                f"Canonical fact state file is missing: {filename}.",
                "Initialize project fact state, then replay or approve accepted fact events through the revision lane.",
            ))

    runs_dir = project_root / "runs"
    if runs_dir.exists():
        for run_dir in sorted([path for path in runs_dir.iterdir() if path.is_dir()])[-20:]:
            prompt_path = run_dir / "user_request.md"
            prompt = prompt_path.read_text(encoding="utf-8", errors="replace") if prompt_path.exists() else ""
            if _revision_keywords(prompt) and not (run_dir / "change_request.yml").exists():
                rel = str(run_dir.relative_to(root))
                command = (
                    f"./agentlab.sh governance revision-intake --project {project} "
                    f"--task-id {run_dir.name} --prompt-file {rel}/user_request.md --write"
                )
                migration_report["pending_revision_runs"].append({
                    "task_id": run_dir.name,
                    "path": rel,
                    "missing": "change_request.yml",
                })
                issues.append(_issue(
                    "warning",
                    "revision_change_request",
                    "revision-like prompt has no change_request.yml",
                    rel,
                    "Run revision-intake so the user change request enters the governance lane.",
                    command,
                ))
                remediation_plan.append(_remediation_action(
                    f"intake_revision_{run_dir.name}",
                    "warning",
                    rel,
                    "A revision-like prompt has not been converted into a change request.",
                    "Generate change_request.yml and state_transition_proposal.yml from the original prompt.",
                    command,
                ))
            if (run_dir / "change_request.yml").exists() and not (run_dir / "state_transition_proposal.yml").exists():
                rel = str(run_dir.relative_to(root))
                migration_report["pending_revision_runs"].append({
                    "task_id": run_dir.name,
                    "path": rel,
                    "missing": "state_transition_proposal.yml",
                })
                issues.append(_issue(
                    "warning",
                    "state_transition_proposal",
                    "change_request.yml has no state_transition_proposal.yml",
                    rel,
                    "Regenerate the transition proposal before dispatching Writer/Coder work.",
                ))
                remediation_plan.append(_remediation_action(
                    f"complete_revision_proposal_{run_dir.name}",
                    "warning",
                    rel,
                    "A change request exists without its matching state transition proposal.",
                    "Rebuild the state_transition_proposal.yml from the accepted change_request.yml.",
                ))

    status = "fail" if any(issue["severity"] == "error" for issue in issues) else "pass"
    return {
        "status": status,
        "project": project,
        "active_content_project": active,
        "issue_count": len(issues),
        "issues": issues,
        "migration_report": migration_report,
        "remediation_plan": remediation_plan,
    }


def build_revision_intake(project: str, task_id: str, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_revision_intake_artifacts(project, task_id, prompt)


def register_governance_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    governance_app = typer.Typer(help="Long-project revision governance commands.", no_args_is_help=True)

    @governance_app.command("doctor")
    def doctor(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        write_report: bool = typer.Option(False, "--write-report", help="Write project_brain/governance_migration_report.yml."),
    ) -> None:
        """Audit long-project revision and fact-source governance."""
        result = run_governance_doctor(project_root, project)
        if write_report and (project_root / "projects" / project).exists():
            report_path = _write_governance_report(project_root, project, result)
            result["report_path"] = str(report_path.relative_to(project_root))
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @governance_app.command("propose-migration")
    def propose_migration_cmd(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
    ) -> None:
        """Create a review-first migration proposal from governance doctor findings."""
        result = propose_migration(project_root, project)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @governance_app.command("apply-migration")
    def apply_migration_cmd(
        proposal: str = typer.Option(..., "--proposal", help="Migration proposal id."),
        accepted_by: str = typer.Option("system", "--accepted-by", help="Reviewer/operator identity."),
        accept: bool = typer.Option(False, "--accept", help="Required explicit acceptance flag."),
    ) -> None:
        """Apply accepted safe migration actions such as revision intake reconstruction."""
        result = apply_migration_proposal(project_root, proposal, accept=accept, accepted_by=accepted_by)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if not result.get("applied"):
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
            result = write_revision_intake(project_root, project, task_id, prompt_text)
            console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
            return
        console.print(yaml.safe_dump({"change_request": change_request, "state_transition_proposal": transition}, sort_keys=False, allow_unicode=True).rstrip())

    @governance_app.command("check-revision")
    def check_revision(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
    ) -> None:
        """Validate a pending revision proposal and run conflict checks."""
        result = validate_revision(project_root, project, task_id)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if not result.get("valid"):
            raise typer.Exit(code=1)

    @governance_app.command("apply-revision")
    def apply_revision_cmd(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
        accepted_by: str = typer.Option("system", "--accepted-by", help="Reviewer/operator identity."),
        accept: bool = typer.Option(False, "--accept", help="Required explicit acceptance flag."),
    ) -> None:
        """Accept a revision proposal and merge it into project fact events/snapshot."""
        if not accept:
            result = {
                "status": "needs_acceptance",
                "applied": False,
                "reason": "rerun with --accept to merge project facts",
            }
            console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
            raise typer.Exit(code=1)
        result = apply_revision(project_root, project, task_id, accepted_by=accepted_by)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if not result.get("applied"):
            raise typer.Exit(code=1)

    @governance_app.command("dispatch-status")
    def dispatch_status(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
    ) -> None:
        """Report whether Writer/Coder dispatch is blocked by pending revisions."""
        result = revision_dispatch_status(project_root, project, task_id)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("blocked"):
            raise typer.Exit(code=1)

    app.add_typer(governance_app, name="governance")
