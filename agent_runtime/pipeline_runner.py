"""AgentLab Dry-run Pipeline Runner.

Single-step node executor. No recursion — iteration is caller's responsibility.
Supports quota failure simulation and resume.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import yaml

from atomic_io import atomic_write_yaml
from lifecycle_graph import (
    load_lifecycle, save_lifecycle, next_node, mark_node_started,
    mark_node_completed, mark_node_skipped, mark_node_failed,
    LIFECYCLE_NODES, OPTIONAL_NODES, NODE_REQUIRED_OUTPUTS,
    create_lifecycle,
)
from fake_provider import fake_output_for_agent, generate_sync_report
from artifact_contract import (
    artifact_content_issues,
    validate_artifacts,
    write_artifact_manifest,
    ensure_skipped_artifact,
)
from command_runner import run_validation_commands_if_present
from state_store import load_state, save_state
from progress_tracker import create_progress, load_progress, save_progress
from task_events import append_task_event, classify_blocked_status
from feedback_manager import create_decision_card, write_feedback_status

try:
    from ingestion.github_reader import extract_github_urls, build_repo_manifest, parse_github_url
    from ingestion.repo_manifest import write_repo_manifest, RepoManifest
    from ingestion.resource_ledger import ResourceLedger, write_resource_ledger
except ImportError:  # pragma: no cover
    extract_github_urls = None
    build_repo_manifest = None
    parse_github_url = None
    write_repo_manifest = None
    RepoManifest = None
    ResourceLedger = None
    write_resource_ledger = None

ARTIFACT_ALIASES = {
    "01_supervisor_plan.md": "supervisor_plan.md",
    "02_reposcout_report.md": "reposcout_report.md",
    "06_implementation_report.md": "implementation_report.md",
    "07_validation_report.md": "validation_report.md",
    "09_archive_update.md": "archive_update.md",
}

NODE_TO_AGENT = {
    "SUPERVISOR_PLAN": "Supervisor",
    "REPO_CONTEXT": "RepoScout",
    "RESEARCH_OPTIONAL": "Researcher",
    "INTERFACE_OPTIONAL": "InterfaceMapper",
    "CODER_IMPLEMENTATION": "Coder",
    "VALIDATION": "TesterAuditor",
    "AUDIT": "TesterAuditor",
    "VERIFY": "Verifier",
    "ARCHIVE": "Archivist",
}

NODE_TO_REPORT = {
    "SUPERVISOR_PLAN": "01_supervisor_plan.md",
    "REPO_CONTEXT": "02_reposcout_report.md",
    "RESEARCH_OPTIONAL": "03_research_notes.md",
    "INTERFACE_OPTIONAL": "04_interface_map.md",
    "CODER_IMPLEMENTATION": "06_implementation_report.md",
    "VALIDATION": "07_validation_report.md",
    "AUDIT": "08_audit_report.md",
    "VERIFY": "verification_report.md",
    "ARCHIVE": "09_archive_update.md",
    "SELF_CHECK": "self_check_report.yml",
    "SYNC_OPTIONAL": "sync_report.yml",
}

NODE_TO_PROGRESS = {
    "INIT_TASK": "init", "CONTEXT_PROFILE": "context_profile",
    "CONTEXT_BUDGET": "context_budget", "CONTEXT_PACK": "context_pack", "PREPARE_PLAN": "planning",
    "SUPERVISOR_PLAN": "planning", "REPO_CONTEXT": "scouting",
    "RESEARCH_OPTIONAL": "research", "INTERFACE_OPTIONAL": "interfacing",
    "CODER_IMPLEMENTATION": "implementation", "VALIDATION": "validation",
    "AUDIT": "audit", "VERIFY": "verifying", "ARCHIVE": "archiving",
    "SELF_CHECK": "checking", "SYNC_OPTIONAL": "syncing", "FINALIZE": "completing",
}

NODE_TO_PCT = {
    "INIT_TASK": 5, "CONTEXT_PROFILE": 7, "CONTEXT_BUDGET": 8, "CONTEXT_PACK": 9,
    "PREPARE_PLAN": 10, "SUPERVISOR_PLAN": 20,
    "REPO_CONTEXT": 30, "RESEARCH_OPTIONAL": 35, "INTERFACE_OPTIONAL": 40,
    "CODER_IMPLEMENTATION": 55, "VALIDATION": 70, "AUDIT": 78,
    "VERIFY": 82, "ARCHIVE": 86, "SELF_CHECK": 90, "SYNC_OPTIONAL": 95, "FINALIZE": 100,
}


def _repo_analysis_requested(text: str) -> bool:
    lowered = (text or "").lower()
    triggers = [
        "repo analysis", "repo profile", "repository review", "architecture analysis",
        "analyze repository", "analyse repository", "分析仓库", "仓库分析", "架构分析",
    ]
    clone_triggers = ["git clone", "full clone", "clone/build/test", "build and test", "run tests"]
    return any(t in lowered for t in triggers) and not any(t in lowered for t in clone_triggers)


def _write_repo_stage_context(run_dir: Path, manifest_paths: list[Path], warnings: list[str]) -> None:
    context = {
        "repo_profile": {
            "access_mode": "repo_profile",
            "clone_allowed": False,
            "full_clone_allowed": False,
            "build_allowed": False,
            "repo_manifest_paths": [str(path) for path in manifest_paths],
            "warnings": warnings,
        }
    }
    path = run_dir / "stage_context.yml"
    existing = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}
    existing.update(context)
    atomic_write_yaml(path, existing)


def ensure_repo_manifest_for_run(agentlab_root: Path, project: str, task_id: str) -> list[Path]:
    """API-first repo ingestion hook for repo analysis/profile tasks."""
    if extract_github_urls is None or build_repo_manifest is None:
        return []
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    request_path = run_dir / "user_request.md"
    task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""
    urls = extract_github_urls(task_text)
    if not urls or not _repo_analysis_requested(task_text):
        return []
    existing_single = run_dir / "repo_manifest.json"
    if existing_single.exists():
        _write_repo_stage_context(run_dir, [existing_single], [])
        return [existing_single]
    manifest_paths: list[Path] = []
    warnings: list[str] = []
    manifests_dir = run_dir / "repo_manifests"
    for index, url in enumerate(urls):
        try:
            manifest = build_repo_manifest(url, mode="repo_profile", agentlab_root=agentlab_root)
        except Exception as exc:
            ref = parse_github_url(url) if parse_github_url else None
            manifest = RepoManifest(
                repo_url=getattr(ref, "repo_url", url),
                owner=getattr(ref, "owner", "unknown"),
                repo=getattr(ref, "repo", "unknown"),
                ref=getattr(ref, "ref", "main"),
                clone_performed=False,
                warnings=[f"repo_manifest_build_failed: {type(exc).__name__}: {exc}"],
            )
        warnings.extend(manifest.warnings)
        if len(urls) == 1:
            path = write_repo_manifest(run_dir, manifest)
        else:
            manifests_dir.mkdir(parents=True, exist_ok=True)
            path = manifests_dir / f"{manifest.owner}__{manifest.repo}.json"
            from atomic_io import atomic_write_json
            atomic_write_json(path, manifest.as_dict())
        manifest_paths.append(path)

    if manifest_paths and ResourceLedger is not None:
        first_manifest_data = None
        try:
            import json
            first_manifest_data = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
        except Exception:
            first_manifest_data = None
        ledger = ResourceLedger.from_manifest(task_id, first_manifest_data or {"repo_url": urls[0], "files_read": [], "bytes_downloaded": 0, "clone_performed": False})
        ledger.repo_access.update({
            "access_mode": "repo_profile",
            "clone_allowed": False,
            "full_clone_allowed": False,
            "build_allowed": False,
            "clone_performed": False,
            "manifest_paths": [str(path) for path in manifest_paths],
            "warnings": warnings,
        })
        write_resource_ledger(run_dir, ledger)
    _write_repo_stage_context(run_dir, manifest_paths, warnings)
    return manifest_paths


def _resolve_execution_mode(dry_run: bool, fake_provider: bool) -> dict:
    """Resolve execution mode based on dry_run and fake_provider flags.

    Returns a dict with:
      - execution_mode: str (dry_run / mock_provider / execute)
      - effective_fake_provider: bool
      - allow_real_provider: bool
      - allow_patches: bool
    """
    if dry_run:
        return {
            "execution_mode": "dry_run",
            "effective_fake_provider": True,
            "allow_real_provider": False,
            "allow_patches": False,
        }
    if fake_provider:
        return {
            "execution_mode": "mock_provider",
            "effective_fake_provider": True,
            "allow_real_provider": False,
            "allow_patches": False,
        }
    return {
        "execution_mode": "execute",
        "effective_fake_provider": False,
        "allow_real_provider": True,
        "allow_patches": True,
    }


def _block_task(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    node_id: str,
    *,
    agent: str | None,
    reason: str,
    stage: str = "blocked",
    report_path: Path | None = None,
    user_action_required: bool = True,
    block_type: str = "generic",
    execution_mode: str | None = None,
    mark_lifecycle: bool = True,
) -> dict:
    """Unified helper to write blocked state across state/progress/lifecycle.

    Always writes USER_DECISION_REQUIRED.md when user_action_required=True.
    Returns a dict with status='paused' and success=False.

    mark_lifecycle: When False, skips mark_node_failed to avoid creating
                    non-standard nodes (e.g. "PIPELINE") in lifecycle.yml.
    """
    if mark_lifecycle:
        mark_node_failed(run_dir, node_id, reason)
    state = load_state(run_dir, project, task_id)
    state.status = "blocked"
    state.current_agent = agent
    state.last_event = f"Blocked at {node_id}: {reason}"
    save_state(run_dir, state)

    progress = load_progress(run_dir)
    if progress:
        progress["status"] = "blocked"
        progress["current_agent"] = None
        progress["current_stage"] = stage
        progress["last_event"] = state.last_event
        if agent and agent in progress.get("agents", {}):
            progress["agents"][agent]["status"] = "blocked"
        save_progress(run_dir, progress)

    if user_action_required:
        decision_lines = [
            f"# User Decision Required",
            "",
            f"- Project: {project}",
            f"- Task: {task_id}",
            f"- Node: {node_id}",
            f"- Block Type: {block_type}",
            f"- Reason: {reason}",
        ]
        if report_path and report_path.exists():
            decision_lines.append(f"- Evidence: {report_path}")
        (run_dir / "USER_DECISION_REQUIRED.md").write_text(
            "\n".join(decision_lines) + "\n", encoding="utf-8"
        )
        card, card_path = create_decision_card(
            run_dir,
            task_id=task_id,
            card_type=block_type,
            title=f"{node_id} requires user action",
            reason=reason,
            stage=stage,
            risk="medium",
            options=[
                {"id": "approve_resume", "label": "Approve resume", "risk": "medium"},
                {"id": "defer", "label": "Defer", "risk": "low"},
                {"id": "stop_task", "label": "Stop task", "risk": "none"},
            ],
            recommended_action="approve_resume",
        )
    else:
        card = None
        card_path = None

    append_task_event(
        run_dir,
        "NODE_BLOCKED",
        stage=stage,
        status=classify_blocked_status(block_type),
        severity="BLOCKED" if user_action_required else "FAILED_RECOVERABLE",
        message=reason,
        payload={
            "project": project,
            "task_id": task_id,
            "node": node_id,
            "agent": agent,
            "block_type": block_type,
            "report_path": str(report_path) if report_path else None,
            "decision_card": str(card_path) if card_path else None,
        },
    )
    feedback_status_path = write_feedback_status(run_dir)

    result: dict = {
        "status": "paused",
        "node": node_id,
        "message": reason,
        "block_type": block_type,
        "requires_user_action": user_action_required,
        "success": False,
        "feedback_status": str(feedback_status_path),
    }
    if card_path and card:
        result["decision_card"] = str(card_path)
        result["decision_id"] = card.get("id")
    if execution_mode:
        result["execution_mode"] = execution_mode

    # ── P1-3: Sync task_card.yml and task_index.yml on blocked state ──
    _sync_task_summary(agentlab_root, project, task_id, run_dir)

    return result


def _mark_node_completed(run_dir: Path, node_id: str, report_path: str | None = None) -> None:
    mark_node_completed(run_dir, node_id, report_path)
    append_task_event(
        run_dir,
        "NODE_COMPLETED",
        stage=NODE_TO_PROGRESS.get(node_id, node_id.lower()),
        status="RUNNING",
        severity="MILESTONE",
        message=f"{node_id} completed.",
        payload={"node": node_id, "report_path": report_path},
    )
    write_feedback_status(run_dir)


def _write_pipeline_incident(
    run_dir: Path,
    *,
    incident_type: str,
    reason: str,
    node_id: str | None = None,
    max_steps: int | None = None,
) -> Path:
    """Write pipeline_incident.yml for pipeline-level errors.

    These incidents are orthogonal to agent-level lifecycle nodes.
    """
    import datetime as dt_mod
    incident = {
        "version": 1,
        "incident_type": incident_type,
        "reason": reason,
        "node_id": node_id,
        "max_steps": max_steps,
        "created_at": dt_mod.datetime.now(dt_mod.timezone.utc).isoformat(),
    }
    path = run_dir / "pipeline_incident.yml"
    path.write_text(
        yaml.safe_dump(incident, sort_keys=False), encoding="utf-8"
    )
    return path


def _sync_task_summary(
    agentlab_root: Path, project: str, task_id: str, run_dir: Path,
) -> None:
    """Refresh task_card.yml and project-level task_index.yml for a run.

    Non-fatal — writes index_sync_warning.log on failure so
    missing task_card/task_index sync is visible.
    """
    try:
        from task_index import (
            generate_per_task_artifacts,
            build_project_task_index,
            save_project_task_index,
        )
        # Refresh per-task card
        generate_per_task_artifacts(agentlab_root, project, task_id)
        # Refresh project-level index
        index = build_project_task_index(agentlab_root, project)
        save_project_task_index(agentlab_root, project, index)
    except Exception as exc:
        warning_path = run_dir / "index_sync_warning.log"
        warning_lines = [
            "# Task Index Sync Warning",
            "",
            f"- Project: {project}",
            f"- Task: {task_id}",
            f"- Exception Type: {type(exc).__name__}",
            f"- Exception Message: {exc}",
            "",
            "This warning did not stop the pipeline, but task_card.yml or task_index.yml may be stale.",
        ]
        warning_path.write_text("\n".join(warning_lines), encoding="utf-8")



def _write_artifact_alias(run_dir: Path, report_name: str) -> None:
    alias = ARTIFACT_ALIASES.get(report_name)
    if alias and (run_dir / report_name).exists():
        (run_dir / alias).write_text(
            (run_dir / report_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _append_dry_run_cost_entry(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    *,
    node_id: str,
    agent: str | None,
    budget_mode: str | None,
    execution_mode: str,
) -> None:
    from cost_tracker import append_cost_ledgers

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "task_id": task_id,
        "node": node_id,
        "agent": agent or node_id,
        "budget_mode": budget_mode or "balanced",
        "execution_mode": execution_mode,
        "provider": "fake_provider",
        "model": "deterministic-dry-run",
        "dry_run": True,
        "usage_source": "no_llm_call",
        "exact_usage_available": True,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost": 0.0,
        "exact_cost_available": True,
        "pricing_confidence": "high",
        "notes": "No paid LLM API call was made; deterministic dry-run evidence only.",
    }
    append_cost_ledgers(agentlab_root / "projects" / project, run_dir, entry)


def _record_dry_run_command(run_dir: Path, node_id: str, agent: str | None) -> str:
    from execution_log import append_command_record

    return append_command_record(run_dir, {
        "node": node_id,
        "agent": agent or node_id,
        "command": f"dry-run lifecycle evidence for {node_id}",
        "cwd": str(run_dir),
        "exit_code": 0,
        "stdout": f"{node_id} completed in dry-run mode; no external process or API was invoked.\n",
        "stderr": "",
        "dry_run": True,
        "notes": "Synthetic command record used to make dry-run validation evidence explicit.",
    })


def _record_dry_run_node_evidence(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    *,
    node_id: str,
    agent: str | None,
    report_name: str | None,
    budget_mode: str | None,
    execution_mode: str,
) -> str:
    command_id = _record_dry_run_command(run_dir, node_id, agent)
    _append_dry_run_cost_entry(
        agentlab_root,
        run_dir,
        project,
        task_id,
        node_id=node_id,
        agent=agent,
        budget_mode=budget_mode,
        execution_mode=execution_mode,
    )
    if report_name:
        _write_artifact_alias(run_dir, report_name)
    return command_id

def run_next_node(
    agentlab_root: Path, project: str, task_id: str, *,
    fake_provider: bool = False, simulate_quota_failure_at: Optional[str] = None,
    budget_mode: Optional[str] = None,
    allow_patches: bool = False,
    execution_mode: str | None = None,
) -> dict:
    """Execute exactly one lifecycle node and return.

    allow_patches: Whether to allow patch application. Controlled by execution mode.
    execution_mode: If provided, used in return dicts so direct callers see
                    correct mode. Defaults to inferring from fake_provider.

    This is a SINGLE-STEP function. It does NOT recurse.
    The caller (run_full_pipeline) handles the loop.
    """
    effective_execution_mode = execution_mode or ("mock_provider" if fake_provider else "execute")
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    state = load_state(run_dir, project, task_id)
    progress = load_progress(run_dir)
    if progress is None or "provider_status" not in progress:
        route_agents = []
        plan_path = run_dir / "workflow_plan.yml"
        if plan_path.exists():
            plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
            route_agents = plan_data.get("route", {}).get("agents", [])
        progress = create_progress(run_dir, project, task_id, route_agents)

    if load_lifecycle(run_dir) is None:
        plan_path = run_dir / "workflow_plan.yml"
        workflow_plan = {}
        if plan_path.exists():
            workflow_plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        create_lifecycle(run_dir, workflow_plan)
    else:
        _ensure_lifecycle_shape(run_dir)
        _skip_stale_context_nodes(run_dir)

    nid = next_node(run_dir)
    if nid is None:
        lifecycle = load_lifecycle(run_dir)
        if lifecycle:
            all_done = all(
                lifecycle["nodes"].get(n, {}).get("status") in ("completed", "skipped")
                for n in LIFECYCLE_NODES
            )
            if all_done:
                return {
                    "status": "completed",
                    "node": None,
                    "message": "All nodes completed.",
                    "execution_mode": effective_execution_mode,
                }
        return {
            "status": "waiting",
            "node": None,
            "message": "No waiting nodes.",
            "execution_mode": effective_execution_mode,
        }

    # Skip optional nodes that are already skipped
    if nid in OPTIONAL_NODES:
        lc = load_lifecycle(run_dir)
        if lc and lc.get("nodes", {}).get(nid, {}).get("status") == "skipped":
            return {"status": "skipped", "node": nid, "message": "Already skipped."}

    # Quota failure simulation
    if simulate_quota_failure_at and nid == simulate_quota_failure_at:
        return _block_task(
            agentlab_root, run_dir, project, task_id, nid,
            agent=NODE_TO_AGENT.get(nid),
            reason="Simulated provider quota exhausted",
            stage="blocked_quota",
            user_action_required=True,
            block_type="quota_exhausted",
        )

    mark_node_started(run_dir, nid)
    state.status = "running"
    state.current_agent = NODE_TO_AGENT.get(nid)
    state.last_event = f"Running: {nid}"
    save_state(run_dir, state)

    progress["current_stage"] = NODE_TO_PROGRESS.get(nid, nid.lower())
    progress["percent_complete"] = NODE_TO_PCT.get(nid, 50)
    progress["current_agent"] = NODE_TO_AGENT.get(nid)
    progress["status"] = "running"
    save_progress(run_dir, progress)
    append_task_event(
        run_dir,
        "NODE_STARTED",
        stage=NODE_TO_PROGRESS.get(nid, nid.lower()),
        status="RUNNING",
        severity="INFO",
        message=f"{nid} started.",
        payload={"node": nid, "agent": NODE_TO_AGENT.get(nid)},
    )
    write_feedback_status(run_dir)

    # INIT and PREPARE are already done by init/prepare CLI — just mark
    if nid == "INIT_TASK":
        run_dir.mkdir(parents=True, exist_ok=True)
        if not (run_dir / "user_request.md").exists():
            (run_dir / "user_request.md").write_text(
                "# User Request\n\nDescribe the task here.\n", encoding="utf-8"
            )
        if not (run_dir / "brain_decisions.yml").exists():
            (run_dir / "brain_decisions.yml").write_text("decisions: []\n", encoding="utf-8")
        if not (run_dir / "cost_ledger.yml").exists():
            (run_dir / "cost_ledger.yml").write_text("entries: []\n", encoding="utf-8")
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name=None,
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    if nid == "PREPARE_PLAN":
        plan_path = run_dir / "workflow_plan.yml"
        request_path = run_dir / "user_request.md"
        task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""
        if not plan_path.exists():
            from workflow_plan import build_workflow_plan
            plan = build_workflow_plan(
                agentlab_root, project, task_id,
                execution_backend="codex", budget_mode=budget_mode,
            )
            plan_path.write_text(
                yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False),
                encoding="utf-8",
            )
            route_agents = plan.route.agents
        else:
            plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
            route_agents = plan_data.get("route", {}).get("agents", [])
        from skill_injector import inject_skills_into_workflow_plan
        inject_skills_into_workflow_plan(
            agentlab_root,
            plan_path,
            project=project,
            task_id=task_id,
            task_text=task_text,
            record_usage=True,
        )
        lc = load_lifecycle(run_dir)
        if lc:
            optional_requirements = {
                "RESEARCH_OPTIONAL": "Researcher",
                "INTERFACE_OPTIONAL": "InterfaceMapper",
                "CODER_IMPLEMENTATION": "Coder",
                "VERIFY": "Verifier",
            }
            for node_id, agent_name in optional_requirements.items():
                node = lc.get("nodes", {}).get(node_id, {})
                if agent_name in route_agents and node.get("status") == "skipped":
                    node["status"] = "waiting"
                    node["skip_reason"] = None
            save_lifecycle(run_dir, lc)
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name="workflow_plan.yml",
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    if nid in {"CONTEXT_PROFILE", "CONTEXT_BUDGET", "CONTEXT_PACK"}:
        from context_governance import write_context_artifacts

        written = write_context_artifacts(agentlab_root, project, task_id)
        report_name = {
            "CONTEXT_PROFILE": "context_profile.yml",
            "CONTEXT_BUDGET": "context_budget.yml",
            "CONTEXT_PACK": "context_pack.yml",
        }[nid]
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name=report_name,
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid, str(run_dir / report_name))
        return {"status": "completed", "node": nid, "message": f"{nid} done.", "artifacts": written}

    if nid == "SELF_CHECK":
        result = validate_artifacts(run_dir)
        (run_dir / "self_check_report.yml").write_text(
            yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name="self_check_report.yml",
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": "Self-check done."}

    if nid == "SYNC_OPTIONAL":
        (run_dir / "sync_report.yml").write_text(
            "# Sync Report\n\nStatus: skipped (dry-run)\n", encoding="utf-8")
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name="sync_report.yml",
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": "Sync skipped (dry-run)."}

    if nid == "FINALIZE":
        from task_index import build_task_record
        record = build_task_record(agentlab_root, project, run_dir)
        card = {
            "version": 1, "project": project, "task_id": task_id,
            "title": record["title"], "status": "finalizing",
        }
        atomic_write_yaml(run_dir / "task_card.yml", card)

        preliminary = validate_artifacts(run_dir)
        write_artifact_manifest(run_dir, preliminary)
        result = validate_artifacts(run_dir)
        final_status = "completed" if result.get("valid") else "blocked"
        card["status"] = final_status
        card["artifact_check"] = {
            "valid": bool(result.get("valid")),
            "pass_rate": result.get("pass_rate"),
            "issues_count": result.get("issues_count", 0),
        }
        atomic_write_yaml(run_dir / "task_card.yml", card)
        result = validate_artifacts(run_dir)
        write_artifact_manifest(run_dir, result)
        if not result.get("valid"):
            issues = [f"{i.get('file')}: {i.get('issue')}" for i in result.get("issues", [])]
            return _block_on_artifact_gate(
                agentlab_root, run_dir, project, task_id, nid, "ArtifactContract", issues,
                report_path=run_dir / "artifact_manifest.yml",
            )
        _mark_node_completed(run_dir, nid)
        state.status = "completed"
        state.last_event = f"Task completed via {effective_execution_mode} pipeline"
        save_state(run_dir, state)
        progress = load_progress(run_dir) or {}
        if progress:
            progress["status"] = "completed"
            progress["current_agent"] = None
            progress["current_stage"] = "completed"
            progress["percent_complete"] = 100
            progress["last_event"] = state.last_event
            save_progress(run_dir, progress)
        append_task_event(
            run_dir,
            "TASK_COMPLETED",
            stage="completed",
            status="COMPLETED_PASS",
            severity="COMPLETED",
            message=state.last_event,
            payload={"artifact_check": result},
        )
        try:
            from webhook_dispatcher import dispatch_event

            dispatch_event(
                agentlab_root,
                event="COMPLETED",
                project=project,
                task_id=task_id,
                stage="completed",
                severity="COMPLETED",
                summary=state.last_event,
                reason="Pipeline finalized successfully.",
            )
        except Exception:
            pass
        try:
            from post_task_learning import run_learning_review
            run_learning_review(agentlab_root, project, task_id)
        except Exception as exc:
            (run_dir / "learning_review_warning.log").write_text(
                f"Post-task learning failed: {type(exc).__name__}: {exc}\n",
                encoding="utf-8",
            )
        write_feedback_status(run_dir)
        return {
            "status": "completed", "node": nid,
            "message": "Lifecycle complete.",
            "artifact_check": result, "success": True,
        }

    # Agent output nodes
    agent = NODE_TO_AGENT.get(nid)
    report_file = NODE_TO_REPORT.get(nid)

    # ── Supervisor gate ──
    if nid == "SUPERVISOR_PLAN" and not fake_provider and (run_dir / "USER_DECISION_REQUIRED.md").exists():
        return _block_task(
            agentlab_root, run_dir, project, task_id, nid,
            agent=agent,
            reason="Supervisor produced split plan — user decision required before next agent",
            stage="blocked_user_decision",
            user_action_required=True,
            block_type="user_decision",
        )

    if fake_provider and agent:
        output = fake_output_for_agent(agent)
        if report_file:
            report_path = run_dir / report_file
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output, encoding="utf-8")
            command_id = _record_dry_run_node_evidence(
                agentlab_root,
                run_dir,
                project,
                task_id,
                node_id=nid,
                agent=agent,
                report_name=report_file,
                budget_mode=budget_mode,
                execution_mode=effective_execution_mode,
            )
            if report_file in {"07_validation_report.md", "08_audit_report.md", "verification_report.md"}:
                output = output.rstrip() + f"\n\nEvidence: command_id {command_id}\n"
                report_path.write_text(output, encoding="utf-8")
                _write_artifact_alias(run_dir, report_file)
            gate_issues = artifact_content_issues(report_path.name, output, run_dir)
            if gate_issues:
                return _block_on_artifact_gate(
                    agentlab_root, run_dir, project, task_id, nid, agent, gate_issues,
                    report_path=report_path,
                )
            _mark_node_completed(run_dir, nid, str(report_path))
            return {"status": "completed", "node": nid, "report": str(report_path)}
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    elif agent and not fake_provider:
        # ─── execute mode: call real LLM API via agent_runner ───
        from agent_runner import run_agent_model, report_path_for_agent
        from workflow_plan import build_workflow_plan

        plan = build_workflow_plan(agentlab_root, project, task_id, budget_mode=budget_mode)
        report_path = run_dir / report_file if report_file else report_path_for_agent(plan, agent)

        try:
            result = run_agent_model(
                agentlab_root, plan, agent, report_path,
                apply_patches=(agent == "Coder" and allow_patches),
            )
        except Exception as exc:
            blocked_path = run_dir / f"blocked_{agent or nid}_exception.md"
            blocked_content = (
                f"# Pipeline Blocked by Exception\n\n"
                f"- Project: {project}\n"
                f"- Task: {task_id}\n"
                f"- Node: {nid}\n"
                f"- Agent: {agent}\n"
                f"- Exception type: {type(exc).__name__}\n"
                f"- Exception message: {exc}\n\n"
                f"## Recovery Suggestions\n\n"
                f"1. Check provider API key / quota / network.\n"
                f"2. Resume with fake provider if debugging pipeline.\n"
                f"3. Resume with another provider if provider failed.\n"
                f"4. Inspect progress.yml and lifecycle.yml.\n"
            )
            blocked_path.write_text(blocked_content, encoding="utf-8")
            return _block_task(
                agentlab_root, run_dir, project, task_id, nid,
                agent=agent,
                reason=f"{type(exc).__name__}: {exc}",
                stage="blocked_exception",
                report_path=blocked_path,
                user_action_required=True,
                block_type="exception",
            )

        if result.status == "blocked_user_decision":
            blocked_path = run_dir / f"blocked_{agent}.md"
            blocked_path.write_text(result.content or "", encoding="utf-8")
            return _block_task(
                agentlab_root, run_dir, project, task_id, nid,
                agent=agent,
                reason=result.error or "User decision required",
                stage="blocked_user_decision",
                report_path=blocked_path,
                user_action_required=True,
                block_type="user_decision",
            )

        if result.status == "fallback_handoff":
            fallback_path = run_dir / f"codex_fallback_{agent}.md"
            fallback_path.write_text(result.content or "", encoding="utf-8")
            return _block_task(
                agentlab_root, run_dir, project, task_id, nid,
                agent=agent,
                reason=result.error or "Provider unavailable — handoff required",
                stage="handoff_required",
                report_path=fallback_path,
                user_action_required=True,
                block_type="fallback_handoff",
            )

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(result.content or "", encoding="utf-8")
        report_content = result.content or ""

        if nid == "VALIDATION" and effective_execution_mode == "execute":
            command_result = run_validation_commands_if_present(
                agentlab_root=agentlab_root,
                run_dir=run_dir,
                workspace_root=agentlab_root,
                node=nid,
                agent=agent or "TesterAuditor",
            )
            if command_result.get("ran"):
                report_content = report_content.rstrip() + "\n" + command_result["summary_markdown"]
                report_path.write_text(report_content, encoding="utf-8")
                if not command_result.get("all_required_passed", True):
                    return _block_task(
                        agentlab_root,
                        run_dir,
                        project,
                        task_id,
                        nid,
                        agent=agent,
                        reason="Required validation command failed",
                        stage="blocked_validation_command",
                        report_path=report_path,
                        user_action_required=True,
                        block_type="validation_command_failed",
                        execution_mode=effective_execution_mode,
                    )

        # Record token usage to cost_ledger
        from cost_tracker import append_cost_ledgers, usage_entry
        raw_usage = result.raw_usage or {}
        append_cost_ledgers(
            agentlab_root / "projects" / project,
            run_dir,
            usage_entry(
                project, task_id, agent,
                result.provider, result.model, result.status,
                result.input_tokens, result.output_tokens, result.total_tokens,
                "API usage from pipeline executor.",
                agentlab_root=agentlab_root,
                usage_source=raw_usage.get("usage_source"),
                token_estimation_method=raw_usage.get("token_estimation_method"),
                exact_usage_available=raw_usage.get("exact_usage_available"),
                raw_usage=raw_usage,
            ),
        )
        gate_issues = artifact_content_issues(report_path.name, report_content, run_dir)
        if gate_issues:
            return _block_on_artifact_gate(
                agentlab_root, run_dir, project, task_id, nid, agent, gate_issues,
                report_path=report_path,
            )
        _mark_node_completed(run_dir, nid, str(report_path))
        return {"status": "completed", "node": nid, "report": str(report_path), "success": True}
    else:
        output = f"# {nid} Report\n\nDry-run output.\n"
        if report_file:
            report_path = run_dir / report_file
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output, encoding="utf-8")
            command_id = _record_dry_run_node_evidence(
                agentlab_root,
                run_dir,
                project,
                task_id,
                node_id=nid,
                agent=agent or nid,
                report_name=report_file,
                budget_mode=budget_mode,
                execution_mode=effective_execution_mode,
            )
            if report_file in {"07_validation_report.md", "08_audit_report.md", "verification_report.md"}:
                output = output.rstrip() + f"\n\nEvidence: command_id {command_id}\n"
                report_path.write_text(output, encoding="utf-8")
                _write_artifact_alias(run_dir, report_file)
            gate_issues = artifact_content_issues(report_path.name, output, run_dir)
            if gate_issues:
                return _block_on_artifact_gate(
                    agentlab_root, run_dir, project, task_id, nid, agent or nid, gate_issues,
                    report_path=report_path,
                )
            _mark_node_completed(run_dir, nid, str(report_path))
            return {"status": "completed", "node": nid, "report": str(report_path), "success": True}
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done.", "success": True}


def _block_on_artifact_gate(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    node_id: str,
    agent: str,
    issues: list[str],
    *,
    report_path: Path | None = None,
) -> dict:
    """Pause the pipeline when an artifact exists but fails semantic checks.

    Delegates to _block_task for unified state/progress/lifecycle sync.
    """
    reason = "; ".join(issues[:5]) or "Artifact semantic validation failed"
    if len(issues) > 5:
        reason += f"; and {len(issues) - 5} more"
    block_path = run_dir / f"blocked_{agent}_artifact_gate.md"
    lines = [
        "# Artifact Gate Blocked",
        "",
        f"- Project: {project}",
        f"- Task: {task_id}",
        f"- Node: {node_id}",
        f"- Agent: {agent}",
    ]
    if report_path and report_path != block_path:
        lines.append(f"- Evidence: {report_path}")
    lines.extend(["", "## Issues"])
    lines.extend(f"- {issue}" for issue in issues)
    lines.extend([
        "",
        "## Required Action",
        "Regenerate or repair the artifact with executable evidence before resuming the lifecycle.",
        "",
    ])
    block_path.write_text("\n".join(lines), encoding="utf-8")

    result = _block_task(
        agentlab_root, run_dir, project, task_id, node_id,
        agent=agent,
        reason=reason,
        stage="blocked_artifact_gate",
        report_path=block_path,
        user_action_required=True,
        block_type="artifact_gate",
    )
    result["artifact_gate"] = issues
    result["artifact_block_report"] = str(block_path)
    return result


def _state_signature(agentlab_root: Path, project: str, task_id: str) -> str:
    """Return a compact string representing the current lifecycle state."""
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    lc = load_lifecycle(run_dir)
    if not lc:
        return "no_lifecycle"
    sig = []
    for nid in LIFECYCLE_NODES:
        status = lc.get("nodes", {}).get(nid, {}).get("status", "?")
        sig.append(f"{nid[:4]}={status[:3]}")
    return "|".join(sig)


def run_full_pipeline(
    agentlab_root: Path, project: str, task_id: str, *,
    dry_run: bool = True, fake_provider: bool = True,
    simulate_quota_failure_at: Optional[str] = None, max_steps: int = 30,
    budget_mode: Optional[str] = None,
) -> dict:
    """Run full lifecycle pipeline with safety guards.

    Uses explicit while loop — no recursion.
    Detects loops via state signature. Detects stalls via no-progress check.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    history = []
    seen_signatures = set()
    mode = _resolve_execution_mode(dry_run, fake_provider)
    ensure_repo_manifest_for_run(agentlab_root, project, task_id)
    effective_max_steps = max_steps
    if simulate_quota_failure_at:
        effective_max_steps += len([n for n in LIFECYCLE_NODES if n.startswith("CONTEXT_")])

    for step in range(effective_max_steps):
        sig = _state_signature(agentlab_root, project, task_id)
        if sig in seen_signatures:
            err = f"Lifecycle loop detected at step {step}: cycle in state"
            (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
            _write_pipeline_incident(
                run_dir, incident_type="loop_detected",
                reason=err, node_id="PIPELINE", max_steps=max_steps,
            )
            blocked = _block_task(
                agentlab_root, run_dir, project, task_id,
                "PIPELINE", agent=None, reason=err,
                stage="pipeline_error",
                report_path=run_dir / "pipeline_error.log",
                user_action_required=True,
                block_type="pipeline_error",
                execution_mode=mode["execution_mode"],
                mark_lifecycle=False,
            )
            return {
                "success": False,
                "final_status": "paused",
                "terminal": False,
                "requires_user_action": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "blocked_reason": blocked.get("message"),
                "blocked_type": blocked.get("block_type"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        seen_signatures.add(sig)

        # Check terminal
        if "FINALIZE=com" in sig or all(
            lc.get("nodes", {}).get(n, {}).get("status") in ("completed", "skipped")
            for n in LIFECYCLE_NODES
            if (lc := (load_lifecycle(run_dir) or {"nodes": {}}))
        ):
            artifact_result = validate_artifacts(run_dir)
            write_artifact_manifest(run_dir, artifact_result)
            if not artifact_result.get("valid"):
                # ── P0.5-1: terminal artifact invalid must go through _block_task ──
                incident_path = _write_pipeline_incident(
                    run_dir,
                    incident_type="artifact_validation_failed",
                    reason="Artifact validation failed at pipeline completion",
                    node_id="FINALIZE",
                    max_steps=max_steps,
                )
                block_result = _block_task(
                    agentlab_root, run_dir, project, task_id,
                    "FINALIZE",
                    agent="ArtifactContract",
                    reason="Artifact validation failed at pipeline completion",
                    stage="blocked_artifact_validation",
                    report_path=incident_path,
                    user_action_required=True,
                    block_type="artifact_validation",
                    execution_mode=mode["execution_mode"],
                )
                return {
                    "success": False,
                    "final_status": "paused",
                    "terminal": False,
                    "requires_user_action": True,
                    "execution_mode": mode["execution_mode"],
                    "step": step,
                    "history": history,
                    "artifact_completeness": artifact_result,
                    "blocked_reason": block_result.get("message"),
                    "blocked_type": block_result.get("block_type"),
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            state = load_state(run_dir, project, task_id)
            state.status = "completed"
            state.last_event = f"Task completed via {mode['execution_mode']} pipeline"
            save_state(run_dir, state)
            progress = load_progress(run_dir) or {}
            if progress:
                progress["status"] = "completed"
                progress["current_agent"] = None
                progress["current_stage"] = "completed"
                progress["percent_complete"] = 100
                progress["last_event"] = state.last_event
                save_progress(run_dir, progress)
            append_task_event(
                run_dir,
                "TASK_COMPLETED",
                stage="completed",
                status="COMPLETED_PASS",
                severity="COMPLETED",
                message=state.last_event,
                payload={"artifact_check": artifact_result},
            )
            try:
                from webhook_dispatcher import dispatch_event

                dispatch_event(
                    agentlab_root,
                    event="COMPLETED",
                    project=project,
                    task_id=task_id,
                    stage="completed",
                    severity="COMPLETED",
                    summary=state.last_event,
                    reason="Pipeline finalized successfully.",
                )
            except Exception:
                pass
            try:
                from post_task_learning import run_learning_review
                run_learning_review(agentlab_root, project, task_id)
            except Exception as exc:
                (run_dir / "learning_review_warning.log").write_text(
                    f"Post-task learning failed: {type(exc).__name__}: {exc}\n",
                    encoding="utf-8",
                )
            write_feedback_status(run_dir)
            return {
                "success": True,
                "final_status": "completed",
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "artifact_completeness": artifact_result,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        result = run_next_node(
            agentlab_root, project, task_id,
            fake_provider=mode["effective_fake_provider"],
            simulate_quota_failure_at=simulate_quota_failure_at,
            budget_mode=budget_mode,
            allow_patches=mode["allow_patches"],
            execution_mode=mode["execution_mode"],
        )
        result["execution_mode"] = mode["execution_mode"]

        history.append({
            "step": step, "node": result.get("node"),
            "status": result.get("status"),
            "message": result.get("message", ""),
        })

        if result.get("status") == "paused":
            artifact_result = validate_artifacts(run_dir)
            return {
                "success": False,
                "final_status": "paused",
                "terminal": False,
                "requires_user_action": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "artifact_completeness": artifact_result,
                "blocked_reason": result.get("message"),
                "blocked_type": result.get("block_type"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        if result.get("status") == "error":
            return {
                "success": False,
                "final_status": "failed",
                "terminal": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "error": result.get("message"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        # Snapshot after, check no-progress
        sig_after = _state_signature(agentlab_root, project, task_id)
        if sig_after == sig:
            err = f"No progress at step {step}: state unchanged"
            (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
            _write_pipeline_incident(
                run_dir, incident_type="no_progress",
                reason=err, node_id="PIPELINE", max_steps=max_steps,
            )
            blocked = _block_task(
                agentlab_root, run_dir, project, task_id,
                "PIPELINE", agent=None, reason=err,
                stage="pipeline_error",
                report_path=run_dir / "pipeline_error.log",
                user_action_required=True,
                block_type="pipeline_error",
                execution_mode=mode["execution_mode"],
                mark_lifecycle=False,
            )
            return {
                "success": False,
                "final_status": "paused",
                "terminal": False,
                "requires_user_action": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "blocked_reason": blocked.get("message"),
                "blocked_type": blocked.get("block_type"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

    err = f"Exceeded max_steps={max_steps}"
    (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
    _write_pipeline_incident(
        run_dir, incident_type="max_steps_exceeded",
        reason=err, node_id="PIPELINE", max_steps=max_steps,
    )
    blocked = _block_task(
        agentlab_root, run_dir, project, task_id,
        "PIPELINE", agent=None, reason=err,
        stage="pipeline_error",
        report_path=run_dir / "pipeline_error.log",
        user_action_required=True,
        block_type="pipeline_error",
        execution_mode=mode["execution_mode"],
        mark_lifecycle=False,
    )
    return {
        "success": False,
        "final_status": "paused",
        "terminal": False,
        "requires_user_action": True,
        "execution_mode": mode["execution_mode"],
        "step": max_steps,
        "history": history,
        "blocked_reason": blocked.get("message"),
        "blocked_type": blocked.get("block_type"),
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def resume_pipeline(
    agentlab_root: Path, project: str, task_id: str, *,
    dry_run: bool = True, fake_provider: bool = True,
    simulate_provider_recovered: bool = False,
    simulate_quota_failure_at: Optional[str] = None,
    max_steps: int = 30,
    budget_mode: Optional[str] = None,
) -> dict:
    """Resume paused pipeline.

    Guarantees a dict return for every branch — never implicitly returns None.
    """
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    state = load_state(run_dir, project, task_id)

    if state.status == "completed":
        return {
            "success": True,
            "final_status": "completed",
            "terminal": True,
            "requires_user_action": False,
            "message": "Task already completed.",
        }

    if simulate_provider_recovered:
        rp = run_dir / "resume_plan.yml"
        if rp.exists():
            rp.unlink()

    if state.status in {"blocked", "paused", "recoverable", "failed_recoverable"}:
        return run_full_pipeline(
            agentlab_root, project, task_id,
            dry_run=dry_run, fake_provider=fake_provider,
            simulate_quota_failure_at=simulate_quota_failure_at,
            max_steps=max_steps,
            budget_mode=budget_mode,
        )

    if state.status in {"failed", "cancelled", "archived"}:
        return {
            "success": False,
            "final_status": state.status,
            "terminal": True,
            "requires_user_action": False,
            "message": f"Task is not resumable from status={state.status}.",
        }

    return {
        "success": False,
        "final_status": state.status,
        "terminal": False,
        "requires_user_action": True,
        "message": f"Task status is not recognized for resume: {state.status}",
    }


def _ensure_lifecycle_shape(run_dir: Path) -> None:
    """Add newly introduced lifecycle nodes to older lifecycle.yml files."""
    lc = load_lifecycle(run_dir)
    if not lc:
        return
    plan_path = run_dir / "workflow_plan.yml"
    route = []
    if plan_path.exists():
        plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        route = plan_data.get("route", {}).get("agents", [])
    nodes = lc.setdefault("nodes", {})
    changed = False
    for node_id in LIFECYCLE_NODES:
        if node_id in nodes:
            continue
        skip_reason = None
        if node_id == "RESEARCH_OPTIONAL" and "Researcher" not in route:
            skip_reason = "Route does not include Researcher"
        elif node_id == "INTERFACE_OPTIONAL" and "InterfaceMapper" not in route:
            skip_reason = "Route does not include InterfaceMapper"
        elif node_id == "CODER_IMPLEMENTATION" and "Coder" not in route:
            skip_reason = "Route does not include Coder"
        elif node_id == "VERIFY" and "Verifier" not in route:
            skip_reason = "Route does not include Verifier"
        nodes[node_id] = {
            "status": "skipped" if skip_reason else "waiting",
            "started_at": None,
            "completed_at": None,
            "checkpoint_id": None,
            "report_path": None,
            "error": None,
            "optional": node_id in OPTIONAL_NODES,
            "skip_reason": skip_reason,
        }
        changed = True
    if changed:
        save_lifecycle(run_dir, lc)
    if not (run_dir / "workflow_plan.yml").exists():
        prepare = nodes.get("PREPARE_PLAN", {})
        if prepare.get("status") == "completed":
            prepare["status"] = "waiting"
            prepare["completed_at"] = None
            save_lifecycle(run_dir, lc)
    if not (run_dir / "brain_decisions.yml").exists():
        (run_dir / "brain_decisions.yml").write_text("decisions: []\n", encoding="utf-8")
    if not (run_dir / "cost_ledger.yml").exists():
        (run_dir / "cost_ledger.yml").write_text("entries: []\n", encoding="utf-8")


def _skip_stale_context_nodes(run_dir: Path) -> None:
    """Skip P2-G nodes when a lifecycle has already advanced past them."""
    lc = load_lifecycle(run_dir)
    if not lc:
        return
    nodes = lc.get("nodes", {})
    downstream_started = any(
        nodes.get(node_id, {}).get("status") in {"completed", "started", "failed", "paused"}
        for node_id in LIFECYCLE_NODES
        if not node_id.startswith("CONTEXT_") and node_id != "INIT_TASK"
    )
    if not downstream_started:
        return
    changed = False
    for node_id in ("CONTEXT_PROFILE", "CONTEXT_BUDGET", "CONTEXT_PACK"):
        node = nodes.get(node_id, {})
        if node.get("status") == "waiting":
            node["status"] = "skipped"
            node["skip_reason"] = "Lifecycle had already advanced before context governance nodes were introduced"
            changed = True
    if changed:
        save_lifecycle(run_dir, lc)
