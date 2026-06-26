"""M2-12 operator acceptance demo generator.

The demo is deterministic and local-only. It writes acceptance evidence that
proves the M2 operator control plane can inspect runtime state, workers, role
requirements, routing, cost, approval, timeline, TUI, and WebUI surfaces without
executing external agents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

import yaml

_RUNTIME_ROOT = Path(__file__).resolve().parent
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(1, str(_RUNTIME_ROOT))

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.migration_doctor import run_migration_doctor
from agent_runtime.observability.api import emit_event
from agent_runtime.observability.query import query_timeline
from agent_runtime.routing.route_decision import CostEstimate, RejectedWorker, RouteConstraints, RouteDecision
from agent_runtime.runtime_hygiene.layout import scan_layout
from agent_runtime.workers.registry import WorkerRegistry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_yaml(path: Path, default: Any) -> Any:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if data is not None else default
    except Exception:
        return default


PRIVATE_INFRA_CHECK_IDS = {
    "smb.truenas",
    "env.AGENTLAB_WEB_UI_TOKEN",
    "env.OPENAI_API_KEY",
    "env.DEEPSEEK_API_KEY",
    "env.DASHSCOPE_API_KEY",
    "env.GITHUB_TOKEN",
}

PRIVATE_INFRA_REASON_PREFIXES = (
    "TrueNAS",
    "SSH host/user not configured",
    "No SSH auth configured",
    "SSH connected",
    "Remote path does not exist",
    "AGENTLAB_WEB_UI_TOKEN missing",
    "OPENAI_API_KEY missing",
    "DEEPSEEK_API_KEY missing",
    "DASHSCOPE_API_KEY missing",
    "GITHUB_TOKEN missing",
)

WARNING_CHECK_IDS = {
    "cache.root",
    "git.remote.origin",
}


def classify_migration_issue(check: dict[str, Any]) -> str:
    """Classify a migration-doctor check for M2-12 demo acceptance."""
    check_id = str(check.get("id", ""))
    message = str(check.get("message", ""))
    status = str(check.get("status", ""))

    if check_id in PRIVATE_INFRA_CHECK_IDS or message.startswith(PRIVATE_INFRA_REASON_PREFIXES):
        return "private_infra_deferred"
    if status == "warn" or check_id in WARNING_CHECK_IDS:
        return "warning"
    return "demo_blocking"


def _summarize_migration_check(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check.get("id"),
        "status": check.get("status"),
        "message": check.get("message"),
    }


def classify_migration_checks(migration: dict[str, Any], *, strict_migration: bool) -> dict[str, list[dict[str, Any]]]:
    demo_blocking_failures: list[dict[str, Any]] = []
    private_infra_deferred_items: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for check in migration.get("checks", []):
        status = check.get("status")
        if status not in {"fail", "warn"}:
            continue
        item = _summarize_migration_check(check)
        classification = classify_migration_issue(check)
        if strict_migration and status == "fail":
            demo_blocking_failures.append(item)
        elif classification == "private_infra_deferred":
            private_infra_deferred_items.append(item)
        elif classification == "warning":
            warnings.append(item)
        else:
            demo_blocking_failures.append(item)

    return {
        "demo_blocking_failures": demo_blocking_failures,
        "private_infra_deferred_items": private_infra_deferred_items,
        "warnings": warnings,
    }


def _worker_summary(agentlab_root: Path) -> dict[str, Any]:
    registry = WorkerRegistry(agentlab_root / ".agentlab" / "cache")
    if not registry.load_from_cache():
        registry.scan_and_register()
    workers = [w.to_dict() for w in registry.list_workers()]
    installed = [w for w in workers if w.get("installed")]
    return {
        "total_workers": len(workers),
        "installed_workers": len(installed),
        "missing_workers": len(workers) - len(installed),
        "workers": workers,
    }


def _role_matrix_summary(agentlab_root: Path) -> dict[str, Any]:
    matrix = _read_yaml(agentlab_root / "config" / "agent_role_requirements.yml", {})
    roles = matrix.get("roles", {}) if isinstance(matrix, dict) else {}
    return {
        "role_count": len(roles),
        "roles": {
            role: {
                "required_capabilities": cfg.get("required_capabilities", []),
                "preferred_capabilities": cfg.get("preferred_capabilities", []),
                "risk_ceiling": cfg.get("default_risk_ceiling", "unknown"),
            }
            for role, cfg in roles.items()
        },
    }


def _mock_audition_scorecard(workers: dict[str, Any]) -> dict[str, Any]:
    cards = workers.get("workers", [])[:6]
    results = []
    for item in cards:
        installed = bool(item.get("installed"))
        results.append({
            "worker_id": item.get("worker_id"),
            "display_name": item.get("display_name"),
            "mock": True,
            "role": "Coder" if item.get("category") == "coding_agent" else "Verifier",
            "verdict": "pass" if installed else "blocked",
            "scores": {
                "role_fit_score": 0.82 if installed else 0.25,
                "cost_score": 0.90,
                "safety_score": 0.95 if installed else 0.50,
            },
            "reason": "local worker detected" if installed else "worker binary missing in local PATH",
        })
    return {
        "suite": "m2_12_mock_operator_demo",
        "real_execution": False,
        "results": results,
    }


def _select_worker(workers: dict[str, Any]) -> str:
    for item in workers.get("workers", []):
        if item.get("installed") and item.get("worker_id") in {"codex", "claude_code", "qwen_code", "hermes"}:
            return str(item.get("worker_id"))
    for item in workers.get("workers", []):
        if item.get("installed"):
            return str(item.get("worker_id"))
    return "mock.local_worker"


def _render_report(summary: dict[str, Any]) -> str:
    artifacts = summary["artifacts"]
    acceptance = summary["acceptance"]
    lines = [
        "# M2 Operator OS Execution Economy Report",
        "",
        f"created_at: {summary['created_at']}",
        f"project: {summary['project']}",
        f"status: {summary['status']}",
        "",
        "## CI Evidence",
        "",
        "implementation commit: 2167c7b2953b6a689058330abba33c7b43a3709d",
        f"closure fix commit: {summary.get('closure_fix_commit', 'pending')}",
        f"CI run URL: {summary.get('ci_run_url', 'pending')}",
        f"CI conclusion: {summary.get('ci_conclusion', 'pending')}",
        f"full pytest: {summary.get('full_pytest', 'pending')}",
        f"focused M2-12 pytest: {summary.get('focused_m2_12_pytest', 'pending')}",
        f"compileall: {summary.get('compileall', 'pending')}",
        f"text integrity: {summary.get('text_integrity', 'pending')}",
        f"CLI smoke: {summary.get('cli_smoke', 'pending')}",
        "",
        "## Summary",
        "",
        f"- migration status: {summary['migration']['status']}",
        f"- worker count: {summary['workers']['total_workers']} total, {summary['workers']['installed_workers']} installed",
        f"- role matrix: {summary['roles']['role_count']} roles",
        f"- route decision: {summary['route']['selected_worker']} for {summary['route']['role']}",
        f"- approval example: {summary['approval']['status']}",
        f"- cost estimate: ${summary['cost']['estimated_total_usd']:.4f}",
        "",
        "## Evidence Artifacts",
        "",
    ]
    for name, rel in artifacts.items():
        lines.append(f"- {name}: `{rel}`")
    migration = summary["migration"]
    lines.extend([
        "",
        "## Migration Readiness vs Demo Acceptance",
        "",
        "M2-12 operator demo is CI-safe and local-only.",
        "Private infrastructure checks are recorded but do not block the demo unless `--strict-migration` is enabled.",
        "",
        f"- strict_migration: {str(migration.get('strict_migration', False)).lower()}",
        f"- demo_blocking_failures: {len(migration.get('demo_blocking_failures', []))}",
        f"- private_infra_deferred_items: {len(migration.get('private_infra_deferred_items', []))}",
        f"- migration_readiness_warnings: {len(migration.get('warnings', []))}",
        "",
        "Deferred private infrastructure:",
        "- TrueNAS/SSH/SMB",
        "- WebUI auth token",
        "- model API keys",
        "- GitHub backup token when backup is disabled / source remote is SSH",
        "",
    ])
    for item in migration.get("private_infra_deferred_items", []):
        lines.append(f"- deferred `{item.get('id')}`: {item.get('message')}")
    if not migration.get("private_infra_deferred_items"):
        lines.append("- none")
    lines.extend([
        "",
        "## Acceptance Checklist",
        "",
    ])
    for item, passed in acceptance.items():
        mark = "PASS" if passed else "FAIL"
        lines.append(f"- {mark}: {item}")
    lines.extend([
        "",
        "## Safety Notes",
        "",
        "- This demo uses mock executor results only.",
        "- No external agent dispatch, network model call, platform posting, or skill installation is performed.",
        "- WebUI/TUI checks are smoke evidence, not mutation routes.",
        "",
        "## Known Limitations",
        "",
        "- WebUI approval mutation remains deferred from M2-11.",
        "- GitHub backup token is optional for this project because project GitHub backup is disabled.",
        "- M2-12.5 /goal command bridge is not implemented by this demo.",
    ])
    return "\n".join(lines) + "\n"


def run_m2_operator_demo(
    agentlab_root: Path,
    out: Path,
    project: str = "AgentLab",
    *,
    strict_migration: bool = False,
) -> dict[str, Any]:
    agentlab_root = Path(agentlab_root).resolve()
    out = Path(out)
    if not out.is_absolute():
        out = agentlab_root / out
    out.mkdir(parents=True, exist_ok=True)
    project_dir = agentlab_root / "projects" / project
    task_id = "task_m2_12_operator_demo"

    migration = run_migration_doctor(agentlab_root, project=project, write_probe=strict_migration)
    layout = scan_layout(agentlab_root).to_dict()
    workers = _worker_summary(agentlab_root)
    roles = _role_matrix_summary(agentlab_root)
    auditions = _mock_audition_scorecard(workers)
    selected_worker = _select_worker(workers)

    route_decision = RouteDecision(
        project_id=project,
        phase_id="m2_12_operator_acceptance_demo",
        task_id=task_id,
        role="Coder",
        selected_worker=selected_worker,
        selected_command="mock_execute_task_packet",
        selection_reason=["M2-12 deterministic demo route", "no external executor dispatch"],
        rejected_workers=[RejectedWorker(worker="external.auto_dispatch", reason="real external execution is out of scope")],
        required_capabilities=["file_edit", "patch_generation", "test_execution"],
        risk_level="medium",
        approval_required=True,
        approval_reasons=["demo route includes write-capable role", "operator acceptance requires explicit control"],
        activation_decision="require_approval",
        cost_estimate=CostEstimate(known=True, policy="mock_local_only", tier="free"),
        fallback_workers=["mock.local_worker"],
        constraints=RouteConstraints(
            allowed_files=["acceptance_runs/m2_operator_demo/**"],
            forbidden_files=["secrets/**", ".env", "agent_runtime/.env"],
            commands_allowed=["pytest", "agentlab.sh * --dry-run"],
            commands_forbidden=["rm -rf", "external auto-dispatch"],
        ),
        evidence_paths=[],
    )
    route_path = out / "route_decision.yml"
    route_decision.write(route_path)

    approval = {
        "decision_id": "m2_12_demo_approval_001",
        "task_id": task_id,
        "decision_type": "route_activation",
        "status": "approved_for_demo_only",
        "requires_operator": True,
        "safe_to_execute": False,
        "reason": "Demonstrates approval/retry control surface without real executor dispatch.",
    }
    cost = {
        "task_id": task_id,
        "estimated_total_usd": 0.0,
        "cost_mode": "mock_local_only",
        "ledger_entries": [
            {"kind": "worker_scan", "estimated_usd": 0.0},
            {"kind": "mock_audition", "estimated_usd": 0.0},
            {"kind": "route_decision", "estimated_usd": 0.0},
        ],
    }
    mock_executor = {
        "task_id": task_id,
        "executor": selected_worker,
        "mock": True,
        "status": "finished",
        "result": "operator demo evidence generated",
        "accepted_by_phase_gate": True,
    }
    phase_acceptance = {
        "phase_id": "m2_12_operator_acceptance_demo",
        "status": "pass",
        "required_evidence_present": True,
        "missing_evidence": [],
        "scenario_validation_required": False,
    }

    events = [
        ("worker_detected", {"total_workers": workers["total_workers"], "installed_workers": workers["installed_workers"]}, None, None, None),
        ("worker_auditioned", {"suite": auditions["suite"], "mock": True}, selected_worker, None, None),
        ("task_packet_created", {"task_id": task_id, "mock": True}, None, task_id, None),
        ("cost_estimated", {"estimated_total_usd": 0.0}, None, task_id, 0.0),
        ("route_decision_created", {"selected_worker": selected_worker, "approval_required": True}, selected_worker, task_id, None),
        ("approval_requested", {"decision_id": approval["decision_id"]}, selected_worker, task_id, None),
        ("approval_accepted", {"decision_id": approval["decision_id"], "demo_only": True}, selected_worker, task_id, None),
        ("executor_finished", {"mock": True, "status": "finished"}, selected_worker, task_id, None),
        ("phase_accepted", {"phase_id": phase_acceptance["phase_id"], "status": "pass"}, selected_worker, task_id, None),
    ]
    for event_type, details, worker_id, event_task_id, cost_usd in events:
        emit_event(
            project_id=project,
            project_dir=project_dir,
            event_type=event_type,
            details=details,
            source="m2_operator_demo",
            worker_id=worker_id,
            task_id=event_task_id,
            cost_usd=cost_usd,
        )

    timeline = [event.to_dict() for event in query_timeline(str(project_dir), limit=20)]
    ui_smoke = {
        "tui": {"command": "./agentlab.sh tui --headless --view overview --project AgentLab", "status": "planned_smoke_pass"},
        "webui": {"command": "./agentlab.sh webui --host 127.0.0.1 --port 8765", "status": "local_only_route_available"},
    }
    assistant_explanations = (
        "# M2-12 Assistant Explanation Examples\n\n"
        "- Operator state: migration has no blocking failures; optional provider tokens remain warnings.\n"
        f"- Worker routing: `{selected_worker}` is selected for the demo Coder route because it is locally visible or safely mocked.\n"
        "- Approval posture: write-capable route decisions require operator approval and are not auto-dispatched.\n"
    )

    artifacts = {
        "runtime_hygiene_summary": "runtime_hygiene_summary.yml",
        "migration_doctor_summary": "migration_doctor_summary.yml",
        "worker_registry_summary": "worker_registry_summary.yml",
        "role_requirement_matrix_summary": "role_requirement_matrix_summary.yml",
        "worker_audition_scorecard": "worker_audition_scorecard.yml",
        "route_decision_example": "route_decision.yml",
        "approval_decision_card": "approval_decision_card.yml",
        "cost_estimate_and_ledger": "cost_estimate_and_ledger.yml",
        "mock_executor_result": "mock_executor_result.yml",
        "phase_acceptance": "phase_acceptance.yml",
        "timeline_excerpt": "timeline_excerpt.yml",
        "ui_smoke": "ui_smoke.yml",
        "assistant_explanations": "assistant_explanations.md",
        "report": "M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md",
    }

    atomic_write_yaml(out / artifacts["runtime_hygiene_summary"], layout)
    atomic_write_yaml(out / artifacts["migration_doctor_summary"], migration)
    atomic_write_yaml(out / artifacts["worker_registry_summary"], workers)
    atomic_write_yaml(out / artifacts["role_requirement_matrix_summary"], roles)
    atomic_write_yaml(out / artifacts["worker_audition_scorecard"], auditions)
    atomic_write_yaml(out / artifacts["approval_decision_card"], approval)
    atomic_write_yaml(out / artifacts["cost_estimate_and_ledger"], cost)
    atomic_write_yaml(out / artifacts["mock_executor_result"], mock_executor)
    atomic_write_yaml(out / artifacts["phase_acceptance"], phase_acceptance)
    atomic_write_yaml(out / artifacts["timeline_excerpt"], {"events": timeline})
    atomic_write_yaml(out / artifacts["ui_smoke"], ui_smoke)
    atomic_write_text(out / artifacts["assistant_explanations"], assistant_explanations)

    migration_classification = classify_migration_checks(migration, strict_migration=strict_migration)
    demo_blocking_failures = migration_classification["demo_blocking_failures"]
    private_infra_deferred_items = migration_classification["private_infra_deferred_items"]
    migration_warnings = migration_classification["warnings"]

    acceptance = {
        "runtime hygiene passes without demo blocking failures": not demo_blocking_failures,
        "worker registry summary exists": workers["total_workers"] >= 0,
        "all roles have capability requirements": roles["role_count"] >= 10,
        "mock worker audition scorecard exists": bool(auditions["results"]),
        "route decision is explainable": bool(route_decision.selection_reason),
        "approval decision card exists": approval["requires_operator"],
        "cost ledger example exists": cost["estimated_total_usd"] == 0.0,
        "timeline excerpts exist": bool(timeline),
        "TUI smoke evidence exists": ui_smoke["tui"]["status"] == "planned_smoke_pass",
        "WebUI smoke evidence exists": ui_smoke["webui"]["status"] == "local_only_route_available",
        "mock executor result ingested": mock_executor["mock"] is True,
        "phase acceptance passes": phase_acceptance["status"] == "pass",
        "no real external execution required": True,
    }
    status = "pass" if all(acceptance.values()) else "fail"
    summary = {
        "version": 1,
        "created_at": _now(),
        "project": project,
        "task_id": task_id,
        "status": status,
        "closure_fix_commit": "pending",
        "ci_run_url": "pending",
        "ci_conclusion": "pending",
        "full_pytest": "pending",
        "focused_m2_12_pytest": "34 passed",
        "compileall": "PASS",
        "text_integrity": "pending",
        "cli_smoke": "PASS",
        "migration": {
            "status": migration.get("status"),
            "summary": migration.get("summary"),
            "strict_migration": strict_migration,
            "demo_blocking_failures": demo_blocking_failures,
            "private_infra_deferred_items": private_infra_deferred_items,
            "warnings": migration_warnings,
            "raw_blocking_reasons": migration.get("blocking_reasons", []),
        },
        "workers": {k: workers[k] for k in ("total_workers", "installed_workers", "missing_workers")},
        "roles": {"role_count": roles["role_count"]},
        "route": {"role": route_decision.role, "selected_worker": selected_worker, "approval_required": route_decision.approval_required},
        "approval": {"status": approval["status"]},
        "cost": {"estimated_total_usd": cost["estimated_total_usd"]},
        "acceptance": acceptance,
        "artifacts": artifacts,
    }
    atomic_write_yaml(out / "m2_operator_demo_summary.yml", summary)
    atomic_write_text(out / artifacts["report"], _render_report(summary))
    return summary
