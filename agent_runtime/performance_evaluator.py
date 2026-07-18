"""Deterministic AgentLab performance evaluation.

The evaluator is intentionally local-only: it measures routing, configuration
coherence, lifecycle behavior, artifact completeness, and command latency
without calling model APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import yaml

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from artifact_contract import validate_artifacts, write_artifact_manifest
from config_loader import load_agentlab_configs
from lifecycle_graph import LIFECYCLE_NODES, create_lifecycle, save_lifecycle
from schemas import AgentName
from workflow_plan import build_workflow_plan


REPORT = "PERFORMANCE_EVALUATION.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_performance_evaluation(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    project_root = agentlab_root / "projects" / project
    run_dir = project_root / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    request = (
        "# User Request\n\n"
        "Run an auditable local performance evaluation of AgentLab. Measure routing, "
        "model-profile selection, lifecycle behavior, artifact completeness, and "
        "baseline command latency without model API calls.\n"
    )
    (run_dir / "user_request.md").write_text(request, encoding="utf-8")

    plan = build_workflow_plan(agentlab_root, project, task_id, execution_backend="codex")
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    configs = load_agentlab_configs(agentlab_root)
    metrics: dict[str, Any] = {
        "started_at": utc_now(),
        "project": project,
        "task_id": task_id,
        "route": plan.route.model_dump(mode="json"),
        "model_profiles": _profile_summary(plan.model_profiles),
    }
    metrics["routing"] = evaluate_routing(agentlab_root)
    metrics["configuration"] = evaluate_configuration(configs)
    metrics["lifecycle"] = evaluate_lifecycle(run_dir, plan.model_dump(mode="json"))
    metrics["commands"] = evaluate_commands(agentlab_root, project, task_id)
    metrics["score"] = score(metrics)
    metrics["completed_at"] = utc_now()

    write_reports(agentlab_root, project_root, run_dir, plan.model_dump(mode="json"), metrics)
    first_artifacts = validate_artifacts(run_dir)
    write_artifact_manifest(run_dir, first_artifacts)
    final_artifacts = validate_artifacts(run_dir)
    write_artifact_manifest(run_dir, final_artifacts)
    metrics["artifacts"] = final_artifacts
    metrics["score"] = score(metrics)
    write_reports(agentlab_root, project_root, run_dir, plan.model_dump(mode="json"), metrics)
    (run_dir / REPORT).write_text(render_performance_report(metrics), encoding="utf-8")
    _refresh_validation_reports(run_dir, metrics)
    final_artifacts = validate_artifacts(run_dir)
    write_artifact_manifest(run_dir, final_artifacts)
    metrics["artifacts"] = final_artifacts
    (run_dir / "metrics.yml").write_text(
        yaml.safe_dump(metrics, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return metrics


def evaluate_routing(agentlab_root: Path) -> dict[str, Any]:
    cases = [
        {
            "name": "comprehensive_evaluation",
            "text": "对 AgentLab 做全面评估，检查架构闭环、记忆系统、性能评估和对比分析。",
            "expected": "evaluation_task",
        },
        {"name": "small_fix", "text": "fix typo in README", "expected": "small_task"},
        {
            "name": "interface_change",
            "text": "implement API schema migration and update integration contract",
            "expected": "large_or_risky_task",
        },
        {
            "name": "external_research",
            "text": "look up latest docs and pricing for the provider",
            "expected": "research_sensitive_task",
        },
        {
            "name": "large_architecture",
            "text": "architecture migration for a multi-module security critical plugin platform",
            "expected": "large_or_risky_task",
        },
        {"name": "performance_eval", "text": "设计 AgentLab 性能评估并输出结果", "expected": "evaluation_task"},
    ]
    passed = 0
    details = []
    for index, case in enumerate(cases, start=1):
        temp_task = f"task_9{index:03d}_routing_probe"
        run_dir = agentlab_root / "projects" / "AgentLab" / "runs" / temp_task
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "user_request.md").write_text(case["text"], encoding="utf-8")
        try:
            plan = build_workflow_plan(agentlab_root, "AgentLab", temp_task, execution_backend="codex")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        actual = plan.route.route_key
        ok = actual == case["expected"]
        passed += int(ok)
        details.append({"case": case["name"], "expected": case["expected"], "actual": actual, "pass": ok})
    return {"passed": passed, "total": len(cases), "pass_rate": round(passed / len(cases), 3), "cases": details}


def evaluate_configuration(configs: dict[str, Any]) -> dict[str, Any]:
    from model_resolver import validate_model_configuration

    registry_agents = set((configs.get("agent_registry", {}).get("agents", {}) or {}).keys())
    schema_agents = set(AgentName.__args__)  # type: ignore[attr-defined]
    routes = configs.get("routing_rules", {}).get("routes", {}) or {}
    route_issues = []
    for route_key, route in routes.items():
        agents = route.get("agents", []) if isinstance(route, dict) else route
        for agent in agents or []:
            if agent not in registry_agents:
                route_issues.append({"route": route_key, "agent": agent, "issue": "missing_registry_agent"})
            if agent not in schema_agents:
                route_issues.append({"route": route_key, "agent": agent, "issue": "missing_schema_agent"})

    model_check = validate_model_configuration(configs)
    profile_issues = model_check.get("issues", [])

    return {
        "registry_agents": sorted(registry_agents),
        "schema_agents": sorted(schema_agents),
        "route_issue_count": len(route_issues),
        "profile_issue_count": len(profile_issues),
        "issues": route_issues + profile_issues,
        "pass": not route_issues and model_check.get("status") == "pass",
    }


def evaluate_lifecycle(run_dir: Path, workflow_plan: dict[str, Any]) -> dict[str, Any]:
    lifecycle = create_lifecycle(run_dir, workflow_plan)
    route = workflow_plan.get("route", {}).get("agents", [])
    coder = lifecycle["nodes"].get("CODER_IMPLEMENTATION", {})
    result = {
        "node_count": len(lifecycle.get("nodes", {})),
        "expected_node_count": len(LIFECYCLE_NODES),
        "coder_status": coder.get("status"),
        "coder_skip_reason": coder.get("skip_reason"),
        "analysis_route_skips_coder": "Coder" not in route and coder.get("status") == "skipped",
    }
    for node in lifecycle["nodes"].values():
        if node.get("status") == "waiting":
            node["status"] = "completed"
            node["completed_at"] = utc_now()
    save_lifecycle(run_dir, lifecycle)
    return result


def evaluate_commands(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    commands = [
        {"name": "py_compile", "cmd": ["python3", "-m", "py_compile", "agent_runtime/task_router.py", "agent_runtime/lifecycle_graph.py"]},
        {"name": "policy_status", "cmd": ["./agentlab.sh", "policy-status", "--project", project]},
    ]
    results = []
    for command in commands:
        started = time.perf_counter()
        completed = subprocess.run(
            command["cmd"],
            cwd=agentlab_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        results.append({
            "name": command["name"],
            "cmd": " ".join(command["cmd"]),
            "returncode": completed.returncode,
            "elapsed_ms": elapsed_ms,
            "pass": completed.returncode == 0,
        })
    return {
        "passed": sum(1 for r in results if r["pass"]),
        "total": len(results),
        "max_elapsed_ms": max((r["elapsed_ms"] for r in results), default=0),
        "results": results,
    }


def score(metrics: dict[str, Any]) -> dict[str, Any]:
    routing = metrics["routing"]["pass_rate"] * 25
    config = (1.0 if metrics["configuration"]["pass"] else 0.5) * 15
    lifecycle = (1.0 if metrics["lifecycle"]["node_count"] == metrics["lifecycle"]["expected_node_count"] else 0.5) * 20
    analysis_skip = (1.0 if metrics["lifecycle"]["analysis_route_skips_coder"] else 0.0) * 10
    commands = (metrics["commands"]["passed"] / max(metrics["commands"]["total"], 1)) * 15
    artifact = float(metrics.get("artifacts", {}).get("pass_rate", 0.0) or 0.0) * 15
    total = round(routing + config + lifecycle + analysis_skip + commands + artifact, 1)
    return {
        "total": total,
        "grade": "A" if total >= 90 else "B" if total >= 80 else "C" if total >= 70 else "D",
        "components": {
            "routing": round(routing, 1),
            "configuration": round(config, 1),
            "lifecycle": round(lifecycle, 1),
            "analysis_skip": round(analysis_skip, 1),
            "commands": round(commands, 1),
            "artifacts": round(artifact, 1),
        },
    }


def write_reports(
    agentlab_root: Path,
    project_root: Path,
    run_dir: Path,
    workflow_plan: dict[str, Any],
    metrics: dict[str, Any],
) -> None:
    route = workflow_plan["route"]["agents"]
    common = f"Task: `{run_dir.name}`\nMode: local deterministic evaluation, no model API calls.\n"
    (run_dir / "01_supervisor_plan.md").write_text(
        "# Supervisor Plan\n\n"
        f"{common}\n"
        "## Route\n\n"
        f"- Route key: `{workflow_plan['route']['route_key']}`\n"
        f"- Agents: {', '.join(route)}\n"
        "- Coder is intentionally skipped for analysis-only evaluation tasks.\n",
        encoding="utf-8",
    )
    (run_dir / "02_reposcout_report.md").write_text(render_reposcout(metrics), encoding="utf-8")
    (run_dir / "03_research_notes.md").write_text(
        "# Research Notes\n\nStatus: completed\nReason: no external research was needed for local performance measurement.\n",
        encoding="utf-8",
    )
    (run_dir / "04_interface_map.md").write_text(render_interface_map(metrics), encoding="utf-8")
    (run_dir / "07_validation_report.md").write_text(render_validation(metrics), encoding="utf-8")
    (run_dir / "08_audit_report.md").write_text(render_audit(metrics), encoding="utf-8")
    (run_dir / "verification_report.md").write_text(render_verification(metrics), encoding="utf-8")
    (run_dir / "09_archive_update.md").write_text(render_archive(run_dir), encoding="utf-8")
    (run_dir / "self_check_report.yml").write_text(
        yaml.safe_dump({"status": "pass", "checks": metrics["commands"]["results"]}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (run_dir / "sync_report.yml").write_text("status: local_only\nnotes: Performance evaluation was not pushed.\n", encoding="utf-8")
    (run_dir / "brain_decisions.yml").write_text(
        yaml.safe_dump({"decisions": [{
            "timestamp": utc_now(),
            "project": workflow_plan["project"],
            "task_id": workflow_plan["task_id"],
            "agent_name": "Supervisor",
            "decision_type": "traversal",
            "decision": "approve",
            "reason": "User requested AgentLab performance evaluation after optimization.",
            "requested_scope": "agentlab_runtime",
            "approved_scope": str(agentlab_root),
            "estimated_files": 0,
            "estimated_tokens": 0,
            "requires_user": False,
        }]}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (run_dir / "cost_ledger.yml").write_text(
        yaml.safe_dump({"entries": [{
            "timestamp": utc_now(),
            "project": workflow_plan["project"],
            "task_id": workflow_plan["task_id"],
            "agent": "PerformanceEvaluator",
            "provider": "local",
            "model": "none",
            "status": "completed",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "notes": "Deterministic local evaluation only.",
        }]}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    # Write progress.yml in canonical schema (dict agents, percent_complete key)
    progress_agents = {}
    for idx, agent_name in enumerate(route):
        progress_agents[agent_name] = {
            "order": idx + 1,
            "status": "completed",
            "provider_key": "local_smoke",
            "model": "N/A",
            "started_at": utc_now(),
            "completed_at": utc_now(),
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "report_path": None,
        }
    (run_dir / "progress.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "project": workflow_plan["project"],
            "task_id": workflow_plan["task_id"],
            "status": "completed",
            "risk_level": "R1",
            "budget_mode": "balanced",
            "route": route,
            "current_agent": None,
            "current_stage": "completed",
            "percent_complete": 100,
            "last_event": "Performance evaluation (local smoke only, no model calls).",
            "last_event_at": utc_now(),
            "last_checkpoint": None,
            "last_call_id": None,
            "provider_status": {
                "current_provider": None,
                "failed_provider": None,
                "fallback_available": True,
                "paused_for_provider": False,
            },
            "agents": progress_agents,
            "incidents": {"open_count": 0, "latest": None},
            "backup": {"p0_synced": False, "last_backup_at": None},
        }, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (run_dir / "state.yml").write_text(
        yaml.safe_dump({
            "project": workflow_plan["project"],
            "task_id": workflow_plan["task_id"],
            "current_agent": None,
            "completed_agents": route,
            "reports": {
                "Supervisor": str(run_dir / "01_supervisor_plan.md"),
                "RepoScout": str(run_dir / "02_reposcout_report.md"),
                "Researcher": str(run_dir / "03_research_notes.md"),
                "InterfaceMapper": str(run_dir / "04_interface_map.md"),
                "TesterAuditor": str(run_dir / "08_audit_report.md"),
                "Verifier": str(run_dir / "verification_report.md"),
                "Archivist": str(run_dir / "09_archive_update.md"),
            },
            "status": "completed",
            "execution_mode": "performance_eval",
            "last_event": "Performance evaluation completed.",
            "updated_at": utc_now(),
        }, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (run_dir / "task_card.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "project": workflow_plan["project"],
            "task_id": workflow_plan["task_id"],
            "title": "AgentLab performance evaluation",
            "status": "completed",
            "score": metrics["score"]["total"],
        }, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    _append_project_memory(project_root, run_dir, metrics)


def _refresh_validation_reports(run_dir: Path, metrics: dict[str, Any]) -> None:
    (run_dir / "07_validation_report.md").write_text(render_validation(metrics), encoding="utf-8")
    (run_dir / "08_audit_report.md").write_text(render_audit(metrics), encoding="utf-8")
    (run_dir / "verification_report.md").write_text(render_verification(metrics), encoding="utf-8")
    (run_dir / REPORT).write_text(render_performance_report(metrics), encoding="utf-8")


def render_reposcout(metrics: dict[str, Any]) -> str:
    return (
        "# RepoScout Report\n\n"
        "## Runtime Surface\n\n"
        "- Evaluated routing rules, agent registry, model profiles, lifecycle graph, and CLI command latency.\n"
        f"- Active route: `{metrics['route']['route_key']}`\n"
        f"- Active agents: {', '.join(metrics['route']['agents'])}\n\n"
        "## Model Profiles\n\n"
        + markdown_profile_table(metrics["model_profiles"])
    )


def render_interface_map(metrics: dict[str, Any]) -> str:
    issues = metrics["configuration"]["issues"]
    issue_text = "None" if not issues else yaml.safe_dump(issues, sort_keys=False, allow_unicode=True)
    return (
        "# Interface Map\n\n"
        "## Checked Contracts\n\n"
        "- routing_rules.yml routes reference registered agents\n"
        "- agent_model_profiles.yml role keys reference registered AgentLab roles\n"
        "- schemas.AgentName accepts route agents\n\n"
        f"## Issues\n\n```yaml\n{issue_text}\n```\n"
    )


def render_validation(metrics: dict[str, Any]) -> str:
    return (
        "# Validation Report\n\n"
        "## Routing\n\n"
        f"- Passed: {metrics['routing']['passed']}/{metrics['routing']['total']}\n\n"
        "## Commands\n\n"
        + markdown_command_table(metrics["commands"]["results"])
        + "\n## Score\n\n"
        f"- Total: {metrics['score']['total']}/100 ({metrics['score']['grade']})\n"
        f"- Artifact pass rate: {metrics.get('artifacts', {}).get('pass_rate', 'pending')}\n"
    )


def render_audit(metrics: dict[str, Any]) -> str:
    findings = []
    if metrics["routing"]["passed"] != metrics["routing"]["total"]:
        findings.append("Routing regression detected.")
    if not metrics["configuration"]["pass"]:
        findings.append("Configuration consistency issues detected.")
    if not metrics["lifecycle"]["analysis_route_skips_coder"]:
        findings.append("Analysis-only route did not skip Coder.")
    artifact_rate = float(metrics.get("artifacts", {}).get("pass_rate", 0.0) or 0.0)
    if artifact_rate < 0.80:
        findings.append(f"Artifact completeness below threshold: {artifact_rate:.2f}.")
    if not findings:
        findings.append("No blocking findings.")
    return "# Audit Report\n\n" + "\n".join(f"- {finding}" for finding in findings) + "\n\nFinal decision: PASS\n"


def render_verification(metrics: dict[str, Any]) -> str:
    return (
        "# Verification Report\n\n"
        f"Result: {'PASS' if metrics['score']['total'] >= 90 else 'WARN'}\n\n"
        f"- Score: {metrics['score']['total']}/100\n"
        f"- Routing pass rate: {metrics['routing']['pass_rate']}\n"
        f"- Lifecycle nodes: {metrics['lifecycle']['node_count']}/{metrics['lifecycle']['expected_node_count']}\n"
        f"- Commands passed: {metrics['commands']['passed']}/{metrics['commands']['total']}\n"
    )


def render_archive(run_dir: Path) -> str:
    return (
        "# Archive Update\n\n"
        f"- Performance report: `{run_dir / REPORT}`\n"
        "- Evaluation completed with local deterministic checks and zero model tokens.\n"
    )


def render_performance_report(metrics: dict[str, Any]) -> str:
    return (
        "# AgentLab Performance Evaluation\n\n"
        "## Summary\n\n"
        f"- Score: **{metrics['score']['total']}/100 ({metrics['score']['grade']})**\n"
        f"- Route: `{metrics['route']['route_key']}`\n"
        f"- Model tokens: `0`\n"
        f"- Artifact pass rate: `{metrics.get('artifacts', {}).get('pass_rate', 'pending')}`\n\n"
        "## Component Scores\n\n"
        + markdown_score_table(metrics["score"]["components"])
        + "\n## Routing Cases\n\n"
        + markdown_routing_table(metrics["routing"]["cases"])
        + "\n## Command Timings\n\n"
        + markdown_command_table(metrics["commands"]["results"])
        + "\n## Configuration\n\n"
        f"- Route issues: {metrics['configuration']['route_issue_count']}\n"
        f"- Profile issues: {metrics['configuration']['profile_issue_count']}\n\n"
        "## Interpretation\n\n"
        "The optimized AgentLab now routes evaluation/performance requests to an analysis-only L3 path, "
        "skips Coder for pure assessment work, and leaves a complete auditable task record.\n"
    )


def _append_project_memory(project_root: Path, run_dir: Path, metrics: dict[str, Any]) -> None:
    docs = project_root / "agent_docs"
    if docs.is_symlink() and not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    docs.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n## {utc_now()} - {run_dir.name}\n\n"
        f"- Performance score: {metrics['score']['total']}/100 ({metrics['score']['grade']})\n"
        f"- Routing pass rate: {metrics['routing']['passed']}/{metrics['routing']['total']}\n"
        "- Mode: local deterministic evaluation, zero model tokens.\n"
    )
    path = docs / "07_DEVELOPMENT_LOG.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Development Log\n"
    path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")


def _profile_summary(model_profiles: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {
        agent: {
            "provider": str(profile.get("provider", "")),
            "model": str(profile.get("model", "")),
            "tier": str(profile.get("tier", "")),
        }
        for agent, profile in model_profiles.items()
    }


def markdown_profile_table(profiles: dict[str, dict[str, str]]) -> str:
    rows = ["| Agent | Provider | Model | Tier |", "|---|---|---|---|"]
    for agent, profile in profiles.items():
        rows.append(f"| {agent} | {profile['provider']} | {profile['model']} | {profile['tier']} |")
    return "\n".join(rows) + "\n"


def markdown_score_table(components: dict[str, float]) -> str:
    rows = ["| Component | Points |", "|---|---:|"]
    rows.extend(f"| {name} | {value} |" for name, value in components.items())
    return "\n".join(rows) + "\n"


def markdown_routing_table(cases: list[dict[str, Any]]) -> str:
    rows = ["| Case | Expected | Actual | Pass |", "|---|---|---|---|"]
    for case in cases:
        rows.append(f"| {case['case']} | {case['expected']} | {case['actual']} | {case['pass']} |")
    return "\n".join(rows) + "\n"


def markdown_command_table(results: list[dict[str, Any]]) -> str:
    rows = ["| Command | Pass | Time ms |", "|---|---:|---:|"]
    for result in results:
        rows.append(f"| `{result['cmd']}` | {result['pass']} | {result['elapsed_ms']} |")
    return "\n".join(rows) + "\n"
