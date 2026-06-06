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
from state_store import load_state, save_state
from progress_tracker import create_progress, load_progress, save_progress

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
    "INIT_TASK": "init", "PREPARE_PLAN": "planning",
    "SUPERVISOR_PLAN": "planning", "REPO_CONTEXT": "scouting",
    "RESEARCH_OPTIONAL": "research", "INTERFACE_OPTIONAL": "interfacing",
    "CODER_IMPLEMENTATION": "implementation", "VALIDATION": "validation",
    "AUDIT": "audit", "VERIFY": "verifying", "ARCHIVE": "archiving",
    "SELF_CHECK": "checking", "SYNC_OPTIONAL": "syncing", "FINALIZE": "completing",
}

NODE_TO_PCT = {
    "INIT_TASK": 5, "PREPARE_PLAN": 10, "SUPERVISOR_PLAN": 20,
    "REPO_CONTEXT": 30, "RESEARCH_OPTIONAL": 35, "INTERFACE_OPTIONAL": 40,
    "CODER_IMPLEMENTATION": 55, "VALIDATION": 70, "AUDIT": 78,
    "VERIFY": 82, "ARCHIVE": 86, "SELF_CHECK": 90, "SYNC_OPTIONAL": 95, "FINALIZE": 100,
}


def run_next_node(
    agentlab_root: Path, project: str, task_id: str, *,
    fake_provider: bool = False, simulate_quota_failure_at: Optional[str] = None,
    budget_mode: Optional[str] = None,
) -> dict:
    """Execute exactly one lifecycle node and return.

    This is a SINGLE-STEP function. It does NOT recurse.
    The caller (run_full_pipeline) handles the loop.
    """
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

    nid = next_node(run_dir)
    if nid is None:
        lifecycle = load_lifecycle(run_dir)
        if lifecycle:
            all_done = all(
                lifecycle["nodes"].get(n, {}).get("status") in ("completed", "skipped")
                for n in LIFECYCLE_NODES
            )
            if all_done:
                return {"status": "completed", "node": None, "message": "All nodes completed."}
        return {"status": "waiting", "node": None, "message": "No waiting nodes."}

    # Skip optional nodes that are already skipped
    if nid in OPTIONAL_NODES:
        lc = load_lifecycle(run_dir)
        if lc and lc.get("nodes", {}).get(nid, {}).get("status") == "skipped":
            return {"status": "skipped", "node": nid, "message": "Already skipped."}

    # Quota failure simulation
    if simulate_quota_failure_at and nid == simulate_quota_failure_at:
        mark_node_failed(run_dir, nid, "Simulated provider quota exhausted")
        state.status = "blocked"
        state.last_event = f"Quota exhausted at {nid}"
        save_state(run_dir, state)
        resume = {"paused_at": datetime.now(timezone.utc).isoformat(), "paused_reason": f"Failure at {nid}",
                  "current_node": nid, "allowed_resume_providers": ["qwen", "deepseek"]}
        (run_dir / "resume_plan.yml").write_text(yaml.safe_dump(resume, sort_keys=False), encoding="utf-8")
        return {"status": "paused", "node": nid, "message": f"Simulated quota failure at {nid}."}

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

    # INIT and PREPARE are already done by init/prepare CLI — just mark
    if nid == "INIT_TASK":
        run_dir.mkdir(parents=True, exist_ok=True)
        if not (run_dir / "user_request.md").exists():
            (run_dir / "user_request.md").write_text("# User Request\n\nDescribe the task here.\n", encoding="utf-8")
        if not (run_dir / "brain_decisions.yml").exists():
            (run_dir / "brain_decisions.yml").write_text("decisions: []\n", encoding="utf-8")
        if not (run_dir / "cost_ledger.yml").exists():
            (run_dir / "cost_ledger.yml").write_text("entries: []\n", encoding="utf-8")
        mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    if nid == "PREPARE_PLAN":
        plan_path = run_dir / "workflow_plan.yml"
        if not plan_path.exists():
            from workflow_plan import build_workflow_plan
            plan = build_workflow_plan(agentlab_root, project, task_id, execution_backend="codex", budget_mode=budget_mode)
            plan_path.write_text(yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
            route_agents = plan.route.agents
        else:
            plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
            route_agents = plan_data.get("route", {}).get("agents", [])
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
        mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    if nid == "SELF_CHECK":
        result = validate_artifacts(run_dir)
        (run_dir / "self_check_report.yml").write_text(
            yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
        mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": "Self-check done."}

    if nid == "SYNC_OPTIONAL":
        (run_dir / "sync_report.yml").write_text("# Sync Report\n\nStatus: skipped (dry-run)\n", encoding="utf-8")
        mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": "Sync skipped (dry-run)."}

    if nid == "FINALIZE":
        from task_index import build_task_record
        record = build_task_record(agentlab_root, project, run_dir)
        card = {"version": 1, "project": project, "task_id": task_id,
                "title": record["title"], "status": "finalizing"}
        atomic_write_yaml(run_dir / "task_card.yml", card)

        # FINALIZE must create its own required artifacts before running the
        # final artifact contract.  The first manifest may contain a temporary
        # self-reference issue; the second one records the final truth.
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
                run_dir, project, task_id, nid, "ArtifactContract", issues,
                report_path=run_dir / "artifact_manifest.yml",
            )
        mark_node_completed(run_dir, nid)
        state.status = "completed"
        mode = "dry-run" if fake_provider else "execute"
        state.last_event = f"Task completed via {mode} pipeline"
        save_state(run_dir, state)
        progress = load_progress(run_dir) or {}
        if progress:
            progress["status"] = "completed"
            progress["current_agent"] = None
            progress["current_stage"] = "completed"
            progress["percent_complete"] = 100
            progress["last_event"] = state.last_event
            save_progress(run_dir, progress)
        return {"status": "completed", "node": nid, "message": "Lifecycle complete.",
                "artifact_check": result}

    # Agent output nodes
    agent = NODE_TO_AGENT.get(nid)
    report_file = NODE_TO_REPORT.get(nid)
    if fake_provider and agent:
        output = fake_output_for_agent(agent)
        if report_file:
            report_path = run_dir / report_file
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output, encoding="utf-8")
            gate_issues = artifact_content_issues(report_path.name, output, run_dir)
            if gate_issues:
                return _block_on_artifact_gate(
                    run_dir, project, task_id, nid, agent, gate_issues,
                    report_path=report_path,
                )
            mark_node_completed(run_dir, nid, str(report_path))
            return {"status": "completed", "node": nid, "report": str(report_path)}
        mark_node_completed(run_dir, nid)
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
                apply_patches=(agent == "Coder"),
            )
        except Exception as exc:
            mark_node_failed(run_dir, nid, str(exc))
            state.status = "blocked"
            state.last_event = f"Blocked at {nid}: {exc}"
            save_state(run_dir, state)
            return {"status": "error", "node": nid, "message": str(exc)}

        if result.status == "blocked_user_decision":
            blocked_path = run_dir / f"blocked_{agent}.md"
            blocked_path.write_text(result.content or "", encoding="utf-8")
            (run_dir / "USER_DECISION_REQUIRED.md").write_text(result.content or "", encoding="utf-8")
            mark_node_failed(run_dir, nid, result.error or "User decision required")
            state.status = "blocked"
            state.last_event = f"Blocked at {nid}: {result.error}"
            state.reports[f"{agent}_blocked"] = str(blocked_path)
            save_state(run_dir, state)
            return {"status": "paused", "node": nid, "message": result.error or "User decision required"}

        if result.status == "fallback_handoff":
            fallback_path = run_dir / f"codex_fallback_{agent}.md"
            fallback_path.write_text(result.content or "", encoding="utf-8")
            mark_node_failed(run_dir, nid, result.error or "Provider unavailable — handoff required")
            state.status = "blocked"
            state.last_event = f"Handoff required at {nid}: {result.error}"
            state.reports[f"{agent}_fallback"] = str(fallback_path)
            save_state(run_dir, state)
            return {"status": "paused", "node": nid, "message": result.error or "Provider unavailable"}

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(result.content or "", encoding="utf-8")

        # Record token usage to cost_ledger
        from cost_tracker import append_cost_ledgers, usage_entry
        append_cost_ledgers(
            agentlab_root / "projects" / project,
            run_dir,
            usage_entry(
                project, task_id, agent,
                result.provider, result.model, result.status,
                result.input_tokens, result.output_tokens, result.total_tokens,
                "API usage from pipeline executor.",
            ),
        )
        gate_issues = artifact_content_issues(report_path.name, result.content or "", run_dir)
        if gate_issues:
            return _block_on_artifact_gate(
                run_dir, project, task_id, nid, agent, gate_issues,
                report_path=report_path,
            )
        mark_node_completed(run_dir, nid, str(report_path))
        return {"status": "completed", "node": nid, "report": str(report_path)}
    else:
        output = f"# {nid} Report\n\nDry-run output.\n"
        if report_file:
            report_path = run_dir / report_file
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output, encoding="utf-8")
            gate_issues = artifact_content_issues(report_path.name, output, run_dir)
            if gate_issues:
                return _block_on_artifact_gate(
                    run_dir, project, task_id, nid, agent or nid, gate_issues,
                    report_path=report_path,
                )
            mark_node_completed(run_dir, nid, str(report_path))
            return {"status": "completed", "node": nid, "report": str(report_path)}
        mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}


def _block_on_artifact_gate(
    run_dir: Path,
    project: str,
    task_id: str,
    node_id: str,
    agent: str,
    issues: list[str],
    *,
    report_path: Path | None = None,
) -> dict:
    """Pause the pipeline when an artifact exists but fails semantic checks."""
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
    if report_path:
        lines.append(f"- Report: {report_path}")
    lines.extend(["", "## Issues"])
    lines.extend(f"- {issue}" for issue in issues)
    lines.extend([
        "",
        "## Required Action",
        "Regenerate or repair the artifact with executable evidence before resuming the lifecycle.",
        "",
    ])
    content = "\n".join(lines)
    block_path.write_text(content, encoding="utf-8")
    (run_dir / "USER_DECISION_REQUIRED.md").write_text(content, encoding="utf-8")
    mark_node_failed(run_dir, node_id, reason)
    state = load_state(run_dir, project, task_id)
    state.status = "blocked"
    state.current_agent = agent
    state.last_event = f"Blocked at {node_id}: artifact gate failed"
    state.reports[f"{agent}_artifact_gate"] = str(block_path)
    save_state(run_dir, state)
    return {"status": "paused", "node": node_id, "message": reason, "artifact_gate": issues}


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

    for step in range(max_steps):
        # Snapshot before
        sig = _state_signature(agentlab_root, project, task_id)
        if sig in seen_signatures:
            err = f"Lifecycle loop detected at step {step}: cycle in state"
            (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
            return {"success": False, "error": err, "step": step, "history": history}
        seen_signatures.add(sig)

        # Check terminal
        if "FINALIZE=com" in sig or all(
            lc.get("nodes", {}).get(n, {}).get("status") in ("completed", "skipped")
            for n in LIFECYCLE_NODES
            if (lc := (load_lifecycle(run_dir) or {"nodes": {}}))
        ):
            artifact_result = validate_artifacts(run_dir)
            write_artifact_manifest(run_dir, artifact_result)
            state = load_state(run_dir, project, task_id)
            final_status = "completed" if artifact_result.get("valid") else "blocked"
            state.status = final_status
            mode = "dry-run" if fake_provider else "execute"
            state.last_event = f"Task completed via {mode} pipeline" if artifact_result.get("valid") else "Artifact validation failed at pipeline completion"
            save_state(run_dir, state)
            progress = load_progress(run_dir) or {}
            if progress:
                progress["status"] = final_status
                progress["current_agent"] = None
                progress["current_stage"] = "completed" if final_status == "completed" else "blocked"
                progress["percent_complete"] = 100 if final_status == "completed" else progress.get("percent_complete", 0)
                progress["last_event"] = state.last_event
                save_progress(run_dir, progress)
            return {
                "success": bool(artifact_result.get("valid")), "final_status": final_status, "step": step,
                "history": history, "artifact_completeness": artifact_result,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        result = run_next_node(agentlab_root, project, task_id,
                               fake_provider=fake_provider,
                               simulate_quota_failure_at=simulate_quota_failure_at,
                               budget_mode=budget_mode)

        history.append({"step": step, "node": result.get("node"), "status": result.get("status"),
                        "message": result.get("message", "")})

        if result.get("status") == "paused":
            artifact_result = validate_artifacts(run_dir)
            return {"success": True, "final_status": "paused", "step": step,
                    "history": history, "artifact_completeness": artifact_result,
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat()}

        if result.get("status") == "error":
            return {"success": False, "final_status": "error", "step": step,
                    "history": history, "error": result.get("message"),
                    "started_at": started_at}

        # Snapshot after, check no-progress
        sig_after = _state_signature(agentlab_root, project, task_id)
        if sig_after == sig:
            err = f"No progress at step {step}: state unchanged"
            (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
            return {"success": False, "error": err, "step": step, "history": history}

    err = f"Exceeded max_steps={max_steps}"
    (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
    return {"success": False, "error": err, "step": max_steps, "history": history}


def resume_pipeline(
    agentlab_root: Path, project: str, task_id: str, *,
    dry_run: bool = True, fake_provider: bool = True,
    simulate_provider_recovered: bool = False,
) -> dict:
    """Resume paused pipeline."""
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    state = load_state(run_dir, project, task_id)
    if state.status == "completed":
        return {"status": "completed", "message": "Already completed."}
    if simulate_provider_recovered:
        rp = run_dir / "resume_plan.yml"
        if rp.exists():
            rp.unlink()
    return run_full_pipeline(agentlab_root, project, task_id,
                             dry_run=dry_run, fake_provider=fake_provider)


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
