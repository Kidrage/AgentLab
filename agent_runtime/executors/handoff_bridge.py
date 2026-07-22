from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.executors.authorization import executor_estimated_cost
from agent_runtime.executors.ledger import record_execution_event
from agent_runtime.executors.models import ExecutionPlan, ExecutionRequest, ExecutorDecision, ExecutorProvider, to_plain_data
from agent_runtime.executors.policy import ExecutorRouterPolicy


def create_execution_plan(
    request: ExecutionRequest,
    decision: ExecutorDecision,
    policy: ExecutorRouterPolicy,
    output_dir: Path,
    providers: list[ExecutorProvider] | None = None,
) -> ExecutionPlan:
    output_dir.mkdir(parents=True, exist_ok=True)
    provider = _find_provider(decision.selected_provider_id, providers or [])
    provider_id = decision.selected_provider_id or "none"
    provider_type = provider.provider_type if provider else "unknown"
    execution_mode = provider.execution_mode if provider else policy.default_mode
    estimated_cost = executor_estimated_cost(request, provider)
    plan = ExecutionPlan(
        task_id=request.task_id,
        selected_provider_id=provider_id,
        selected_provider_type=provider_type,
        execution_mode=execution_mode,
        approval_required=decision.approval_required,
        estimated_cost_usd=estimated_cost,
        estimated_risk=provider.risk_level if provider else request.risk_level,
        reason=list(decision.reason),
        handoff_artifact=None,
        expected_result_envelope="execution_result_envelope.yml",
        review_required=request.requires_review or policy.routing.get("require_review_for_all_external_results", True) is True,
        approval_mode=decision.approval_mode,
        approval_grant=decision.approval_grant,
        approval_request=(decision.approval_grant or {}).get("scope"),
    )

    if execution_mode == "manual_handoff_only" or decision.status == "NEEDS_APPROVAL":
        handoff_path = output_dir / "external_execution_handoff.md"
        atomic_write_text(handoff_path, render_external_execution_handoff(request, decision, plan, provider, policy))
        plan.handoff_artifact = handoff_path.name
        record_execution_event(
            output_dir / "execution_ledger.yml",
            request.task_id,
            "handoff_created",
            provider_id,
            provider_type,
            execution_mode,
            decision.status,
            decision.reason,
            [handoff_path.name],
        )
    if decision.status == "NEEDS_APPROVAL":
        atomic_write_yaml(
            output_dir / "approval_required.yml",
            {
                "task_id": request.task_id,
                "provider_id": provider_id,
                "approval_required": True,
                "reason": decision.reason,
            },
        )

    atomic_write_yaml(output_dir / "execution_plan.yml", to_plain_data(plan))
    return plan


def render_external_execution_handoff(
    request: ExecutionRequest,
    decision: ExecutorDecision,
    plan: ExecutionPlan,
    provider: ExecutorProvider | None,
    policy: ExecutorRouterPolicy,
) -> str:
    provider_name = provider.display_name if provider else plan.selected_provider_id
    allowed = request.allowed_files or ["No files pre-approved; ask AgentLab/user before editing."]
    forbidden = request.forbidden_files or ["Secrets, credentials, .git/, dependency caches, and unrelated files."]
    required_artifacts = request.evidence_required or [
        "execution_result_envelope.yml",
        "result_summary.md",
        "changed_files.yml",
        "claimed_tests.yml",
    ]
    lines = [
        "# External Execution Handoff",
        "",
        "## Task Summary",
        request.summary,
        "",
        "## Selected Provider",
        f"- Provider ID: {plan.selected_provider_id}",
        f"- Provider: {provider_name}",
        f"- Provider Type: {plan.selected_provider_type}",
        f"- Execution Mode: {plan.execution_mode}",
        f"- Approval Required: {plan.approval_required}",
        "",
        "## Why This Provider",
        *[f"- {item}" for item in decision.reason],
        "",
        "## Scope",
        f"- Task ID: {request.task_id}",
        f"- Task Type: {request.task_type}",
        f"- Repo Path: {request.repo_path or 'local workspace context only'}",
        "",
        "## Allowed Files",
        *[f"- {item}" for item in allowed],
        "",
        "## Forbidden Files",
        *[f"- {item}" for item in forbidden],
        "",
        "## Required Artifacts",
        *[f"- {item}" for item in required_artifacts],
        "",
        "## Required Tests",
        "- Record every validation command and result.",
        "- If tests cannot be run, explain why in result_summary.md.",
        "",
        "## Budget Notes",
        f"- Max cost USD: {request.max_cost_usd}",
        f"- Estimated cost USD: {plan.estimated_cost_usd}",
        f"- Unknown cost requires approval: {policy.budget.get('unknown_cost_requires_approval', True)}",
        "",
        "## Safety Constraints",
        "- Do not expose secrets.",
        "- Do not clone remote repositories unless explicitly approved.",
        "- Do not execute external scripts unless explicitly approved.",
        "- Do not start MCP servers.",
        "- Do not copy third-party source code.",
        "- Do not use or reveal private subscription credentials.",
        "",
        "## Result Envelope Requirements",
        "- Return result as ExecutionResultEnvelope.",
        "- Include changed_files, claimed_tests, output_artifacts, summary, safety_attestation, and review_target_dir.",
        "- safety_attestation must explicitly state external_scripts_executed=false, mcp_servers_started=false, remote_repos_cloned=false, private_urls_accessed=false, secrets_exposed=false, and third_party_source_copied=false.",
        "",
        "## P2-A Review Requirement",
        "- All results must pass P2-A 3E review before merge.",
        "- Unreviewed results must not be marked accepted.",
    ]
    return "\n".join(lines) + "\n"


def _find_provider(provider_id: str | None, providers: list[ExecutorProvider]) -> ExecutorProvider | None:
    for provider in providers:
        if provider.provider_id == provider_id:
            return provider
    return None
