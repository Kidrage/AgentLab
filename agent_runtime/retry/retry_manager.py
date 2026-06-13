from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.executors import ExecutionRequest, load_executor_providers, load_executor_router_policy, route_execution_request
from agent_runtime.executors.handoff_bridge import create_execution_plan
from agent_runtime.executors.ledger import record_execution_event
from agent_runtime.executors.models import ExecutionPlan, ExecutionResultEnvelope, ExecutorDecision, ExecutorProvider, to_plain_data as executor_plain
from agent_runtime.executors.report_writer import write_route_report
from agent_runtime.executors.result_ingestion import ingest_execution_result, review_execution_result_with_3e
from agent_runtime.retry.attempt_ledger import record_retry_attempt
from agent_runtime.retry.models import RetryAttempt, RetryDecision, RetryLoopState, RetryPolicy, to_plain_data
from agent_runtime.retry.policy import load_retry_policy
from agent_runtime.retry.report_writer import write_retry_loop_artifacts
from agent_runtime.retry.scorecard import update_provider_scorecard


SAFE_ATTESTATION = {
    "external_scripts_executed": False,
    "mcp_servers_started": False,
    "remote_repos_cloned": False,
    "private_urls_accessed": False,
    "secrets_exposed": False,
    "third_party_source_copied": False,
}


def run_acceptance_retry_loop(
    request: ExecutionRequest,
    router_policy_path: Path,
    retry_policy_path: Path,
    review_policy_path: Path,
    output_dir: Path,
    mode: str = "mock",
) -> RetryLoopState:
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = load_retry_policy(retry_policy_path)
    max_attempts = int(policy.loop.get("max_attempts_per_task", 3))
    state = RetryLoopState(
        task_id=request.task_id,
        task_type=request.task_type,
        current_attempt=0,
        max_attempts=max_attempts,
        total_estimated_cost_usd=0.0,
        status="running",
    )
    previous_handoff: str | None = None

    for attempt_index in range(1, max_attempts + 1):
        state.current_attempt = attempt_index
        attempt_dir = output_dir / f"attempt_{attempt_index:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        attempt = RetryAttempt(
            task_id=request.task_id,
            attempt_id=f"attempt_{attempt_index:03d}",
            attempt_index=attempt_index,
            provider_id="none",
            provider_type="none",
            execution_mode=mode,
            input_handoff=previous_handoff,
            status="planned",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        _record(output_dir, state, attempt)

        decision, providers, plan = _route_attempt(request, router_policy_path, attempt_dir, mode)
        selected = _selected_provider(providers, decision.selected_provider_id)
        attempt.provider_id = decision.selected_provider_id or "none"
        attempt.provider_type = selected.provider_type if selected else "none"
        attempt.execution_mode = selected.execution_mode if selected else mode
        attempt.route_report = _rel(output_dir, attempt_dir / "route_report.yml")
        attempt.execution_plan = _rel(output_dir, attempt_dir / "execution_plan.yml")
        attempt.estimated_cost_usd = plan.estimated_cost_usd if plan else None
        state.total_estimated_cost_usd = (state.total_estimated_cost_usd or 0.0) + (attempt.estimated_cost_usd or 0.0)
        attempt.status = "routed" if decision.status in {"ROUTED", "NEEDS_APPROVAL", "DRY_RUN_ONLY"} else "blocked"
        attempt.failure_reasons = list(decision.reason)
        _record(output_dir, state, attempt)

        if decision.status == "NO_PROVIDER":
            retry_decision = RetryDecision("STOP_NO_PROVIDER", decision.reason, "stop", stop_reason="no provider available")
            state.decisions.append(retry_decision)
            state.status = retry_decision.status
            state.final_verdict = retry_decision.status
            break
        if decision.status == "NEEDS_APPROVAL" or mode == "manual-handoff":
            attempt.status = "handoff_created"
            retry_decision = RetryDecision(
                "NEEDS_MANUAL_APPROVAL",
                ["external retry requires manual approval"],
                "manual_approval",
                next_provider_id=attempt.provider_id,
                retry_handoff_path=attempt.execution_plan,
            )
            state.decisions.append(retry_decision)
            state.status = retry_decision.status
            state.final_verdict = retry_decision.status
            _record(output_dir, state, attempt)
            break
        if mode == "dry-run":
            retry_decision = RetryDecision("NEEDS_MANUAL_APPROVAL", ["dry-run only; no result reviewed"], "manual_approval")
            state.decisions.append(retry_decision)
            state.status = retry_decision.status
            state.final_verdict = retry_decision.status
            _record(output_dir, state, attempt)
            break

        envelope = _write_mock_result(request, plan, attempt_dir, _mock_verdict_for(mode, attempt_index))
        attempt.result_envelope = _rel(output_dir, attempt_dir / "mock_result" / "execution_result_envelope.yml")
        attempt.status = "mock_executed"
        _record(output_dir, state, attempt)

        target = ingest_execution_result(attempt_dir / "mock_result" / "execution_result_envelope.yml", attempt_dir)
        verdict = review_execution_result_with_3e(target.target_dir, attempt_dir / "review", review_policy_path)
        setattr(attempt, "review_verdict_status", verdict.status)
        attempt.review_verdict = _rel(output_dir, attempt_dir / "review" / "review_verdict.yml")
        attempt.review_report = _rel(output_dir, attempt_dir / "review" / "review_report.yml")
        retry_handoff = attempt_dir / "review" / "retry_handoff.md"
        if retry_handoff.exists():
            attempt.retry_handoff = _rel(output_dir, retry_handoff)
            previous_handoff = attempt.retry_handoff
        attempt.status = "review_passed" if verdict.status in policy.review.get("pass_statuses", []) else "review_failed"
        attempt.failure_reasons = list(verdict.reasons)
        update_provider_scorecard(
            output_dir / "provider_scorecard.yml",
            attempt.provider_id,
            attempt.provider_type,
            verdict.status,
            policy,
            notes=["deterministic mock provider"] if attempt.provider_type == "mock_executor" else [],
        )
        _record(output_dir, state, attempt)

        retry_decision = decide_retry_action(attempt, state, policy)
        state.decisions.append(retry_decision)
        attempt.retry_decision = retry_decision.status
        _record(output_dir, state, attempt)
        if retry_decision.status == "ACCEPTED":
            state.accepted = True
            state.status = "ACCEPTED"
            state.final_verdict = verdict.status
            break
        if retry_decision.status != "RETRY":
            state.status = retry_decision.status
            state.final_verdict = verdict.status if verdict.status else retry_decision.status
            break
        state.status = "retrying"

    write_retry_loop_artifacts(output_dir, state)
    return state


def decide_retry_action(
    attempt: RetryAttempt,
    loop_state: RetryLoopState,
    policy: RetryPolicy,
) -> RetryDecision:
    verdict = getattr(attempt, "review_verdict_status", None) or _read_verdict_status(attempt.review_verdict)
    pass_statuses = set(policy.review.get("pass_statuses", ["PASS", "PASS_WITH_WARNINGS"]))
    retry_statuses = set(policy.review.get("retry_statuses", ["NEEDS_REVISION", "FAIL"]))
    blocked_statuses = set(policy.review.get("blocked_statuses", ["BLOCKED"]))
    if verdict in pass_statuses:
        return RetryDecision("ACCEPTED", [f"P2-A review verdict {verdict}"], "stop")
    if policy.review.get("require_p2_review_each_attempt", True) and not verdict:
        return RetryDecision("STOP_SAFETY_BLOCKED", ["unreviewed result cannot be accepted"], "stop", stop_reason="unreviewed result")
    if verdict in blocked_statuses:
        return RetryDecision("STOP_SAFETY_BLOCKED", [f"P2-A review verdict {verdict}"], "stop", stop_reason="blocked")
    if loop_state.current_attempt >= loop_state.max_attempts:
        return RetryDecision("STOP_MAX_ATTEMPTS", ["maximum retry attempts reached"], "stop", stop_reason="max attempts")
    if _budget_exceeded(loop_state, policy):
        return RetryDecision("STOP_BUDGET", ["retry budget exceeded"], "stop", stop_reason="budget")
    if _repeated_same_failure(loop_state, policy):
        return RetryDecision("ESCALATE_TO_HUMAN", ["same failure repeated across retry window"], "escalate", stop_reason="repeated failure")
    if attempt.provider_id == "none":
        return RetryDecision("STOP_NO_PROVIDER", ["no provider available"], "stop", stop_reason="no provider")
    if attempt.provider_type != "mock_executor" and policy.routing.get("require_approval_for_external_retry", True):
        return RetryDecision(
            "NEEDS_MANUAL_APPROVAL",
            ["external retry requires approval"],
            "manual_approval",
            next_provider_id=attempt.provider_id,
            retry_handoff_path=attempt.retry_handoff,
        )
    if verdict in retry_statuses:
        return RetryDecision("RETRY", [f"P2-A review verdict {verdict}"], "route_retry", attempt.provider_id, attempt.retry_handoff)
    return RetryDecision("ESCALATE_TO_HUMAN", [f"unhandled review verdict: {verdict}"], "escalate")


def _route_attempt(
    request: ExecutionRequest,
    router_policy_path: Path,
    attempt_dir: Path,
    mode: str,
) -> tuple[ExecutorDecision, list[ExecutorProvider], ExecutionPlan | None]:
    router_policy = load_executor_router_policy(router_policy_path)
    if mode == "manual-handoff":
        router_policy.routing["allow_mock_executor"] = False
        router_policy.provider_priority[request.task_type] = ["manual.codex", "manual.cline", "manual.ecc"]
    providers = load_executor_providers(router_policy)
    decision = route_execution_request(request, providers, router_policy)
    selected = _selected_provider(providers, decision.selected_provider_id)
    record_execution_event(
        attempt_dir / "execution_ledger.yml",
        request.task_id,
        "approval_required" if decision.status == "NEEDS_APPROVAL" else "routed",
        decision.selected_provider_id or "none",
        selected.provider_type if selected else "none",
        selected.execution_mode if selected else router_policy.default_mode,
        decision.status,
        decision.reason,
        [],
    )
    plan = create_execution_plan(request, decision, router_policy, attempt_dir, providers=providers)
    write_route_report(attempt_dir, request.task_id, decision, plan)
    return decision, providers, plan


def _write_mock_result(
    request: ExecutionRequest,
    plan: ExecutionPlan,
    output_dir: Path,
    verdict: str,
) -> ExecutionResultEnvelope:
    mock_dir = output_dir / "mock_result"
    mock_dir.mkdir(parents=True, exist_ok=True)
    if verdict == "PASS":
        claimed_tests = ["python -m pytest -q tests/test_p2_retry_manager.py"]
        changed_files = ["tests/fixtures/p2_retry_loop/mock_only.txt"]
        summary = "Deterministic retry mock produced a complete local-only result."
        attest = dict(SAFE_ATTESTATION)
    elif verdict == "BLOCKED":
        claimed_tests = ["No tests claimed."]
        changed_files = ["secrets/token.txt"]
        summary = "Deterministic retry mock produced unsafe evidence for blocked-path testing."
        attest = dict(SAFE_ATTESTATION)
        attest["external_scripts_executed"] = True
    else:
        claimed_tests = ["python -m pytest -q tests/test_p2_retry_manager.py"]
        changed_files = []
        summary = (
            "Deterministic retry mock produced an incomplete result that requires revision. "
            "Modified files: agent_runtime/retry/retry_manager.py."
        )
        attest = dict(SAFE_ATTESTATION)
    atomic_write_text(mock_dir / "result_summary.md", _result_summary(summary, claimed_tests, attest, verdict))
    atomic_write_yaml(mock_dir / "changed_files.yml", {"changed_files": changed_files})
    atomic_write_yaml(mock_dir / "claimed_tests.yml", {"claimed_tests": claimed_tests})
    envelope = ExecutionResultEnvelope(
        task_id=request.task_id,
        provider_id=plan.selected_provider_id,
        source="retry_mock_executor",
        status=verdict,
        changed_files=changed_files,
        claimed_tests=claimed_tests,
        output_artifacts=[
            "mock_result/result_summary.md",
            "mock_result/changed_files.yml",
            "mock_result/claimed_tests.yml",
        ],
        summary=summary,
        safety_attestation=attest,
        review_target_dir=str(output_dir / "review_input"),
    )
    atomic_write_yaml(mock_dir / "execution_result_envelope.yml", executor_plain(envelope))
    atomic_write_yaml(output_dir / "execution_result_envelope.yml", executor_plain(envelope))
    record_execution_event(
        output_dir / "execution_ledger.yml",
        request.task_id,
        "mock_executed",
        plan.selected_provider_id,
        plan.selected_provider_type,
        plan.execution_mode,
        verdict,
        [summary],
        ["mock_result/execution_result_envelope.yml"],
    )
    return envelope


def _result_summary(summary: str, claimed_tests: list[str], attest: dict[str, bool], verdict: str) -> str:
    tests = claimed_tests or ["No tests claimed."]
    return "\n".join(
        [
            "# Result Summary",
            "",
            "## Summary",
            summary,
            "",
            "## Tests Run",
            *[f"- {item}" for item in tests],
            "",
            "## Safety Evidence",
            *[f"- {key}: {str(value).lower()}" for key, value in attest.items()],
            "",
            "## Known Limitations",
            "- Mock executor does not edit repository code.",
            "",
            "## Verdict",
            f"- {verdict}",
            "",
        ]
    )


def _mock_verdict_for(mode: str, attempt_index: int) -> str:
    if mode in {"mock", "mock-pass-first"}:
        return "PASS"
    if mode == "mock-fail-then-pass":
        return "NEEDS_REVISION" if attempt_index == 1 else "PASS"
    if mode == "mock-fail-until-max":
        return "NEEDS_REVISION"
    if mode == "mock-blocked":
        return "BLOCKED"
    return "PASS"


def _record(output_dir: Path, state: RetryLoopState, attempt: RetryAttempt) -> None:
    existing = {item.attempt_id: item for item in state.attempts}
    existing[attempt.attempt_id] = attempt
    state.attempts = sorted(existing.values(), key=lambda item: item.attempt_index)
    record_retry_attempt(output_dir / "retry_attempt_ledger.yml", state.task_id, attempt)
    atomic_write_yaml(output_dir / "retry_loop_state.yml", to_plain_data(state))


def _read_verdict_status(path: str | None) -> str | None:
    if not path:
        return None
    verdict_path = Path(path)
    if not verdict_path.is_absolute():
        verdict_path = Path.cwd() / verdict_path
    if not verdict_path.exists():
        return None
    data = yaml.safe_load(verdict_path.read_text(encoding="utf-8")) or {}
    return str(data.get("status") or "") or None


def _budget_exceeded(loop_state: RetryLoopState, policy: RetryPolicy) -> bool:
    total = loop_state.total_estimated_cost_usd
    if total is None:
        return bool(policy.budget.get("unknown_cost_requires_approval", True))
    return total > float(policy.budget.get("max_retry_cost_usd_per_task", 0.5))


def _repeated_same_failure(loop_state: RetryLoopState, policy: RetryPolicy) -> bool:
    if policy.loop.get("stop_on_repeated_same_failure", True) is not True:
        return False
    window = int(policy.loop.get("repeated_failure_window", 2))
    if len(loop_state.attempts) < window:
        return False
    recent = loop_state.attempts[-window:]
    first = set(recent[0].failure_reasons)
    if not any(reason.startswith(("HIGH ", "CRITICAL ")) for reason in first):
        return False
    return bool(first) and all(set(item.failure_reasons) == first for item in recent[1:])


def _selected_provider(providers: Iterable[ExecutorProvider], provider_id: str | None) -> ExecutorProvider | None:
    return next((provider for provider in providers if provider.provider_id == provider_id), None)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
