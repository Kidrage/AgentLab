#!/usr/bin/env python3
"""Run deterministic P2-B executor router checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.executors import ExecutionRequest, load_executor_providers, load_executor_router_policy, route_execution_request
from agent_runtime.executors.handoff_bridge import create_execution_plan
from agent_runtime.executors.ledger import record_execution_event
from agent_runtime.executors.mock_executor import run_mock_executor
from agent_runtime.executors.report_writer import write_route_report
from agent_runtime.executors.result_ingestion import ingest_execution_result, review_execution_result_with_3e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AgentLab P2-B executor router")
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=["dry-run", "mock", "manual-handoff"], default="dry-run")
    parser.add_argument("--policy", default=str(ROOT / "config" / "executor_router.yml"))
    args = parser.parse_args(argv)

    output_dir = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    request = ExecutionRequest(
        task_id=output_dir.name,
        task_type=args.task_type,
        summary=args.summary,
        repo_path=ROOT,
        allowed_files=["agent_runtime/"],
        forbidden_files=[".env", ".git/", "secrets/"],
        required_capabilities=[args.task_type],
        risk_level="low",
        max_cost_usd=0.25,
        requires_review=True,
        evidence_required=["execution_result_envelope.yml", "result_summary.md", "changed_files.yml", "claimed_tests.yml"],
    )
    policy = load_executor_router_policy(Path(args.policy))
    if args.mode == "manual-handoff":
        policy.provider_priority[args.task_type] = ["manual.codex", "manual.cline", "manual.ecc"]
    providers = load_executor_providers(policy)
    decision = route_execution_request(request, providers, policy)
    selected = next((item for item in providers if item.provider_id == decision.selected_provider_id), None)
    record_execution_event(
        output_dir / "execution_ledger.yml",
        request.task_id,
        "approval_required" if decision.status == "NEEDS_APPROVAL" else "routed",
        decision.selected_provider_id or "none",
        selected.provider_type if selected else "none",
        selected.execution_mode if selected else policy.default_mode,
        decision.status,
        decision.reason,
        [],
    )
    plan = create_execution_plan(request, decision, policy, output_dir, providers=providers)
    write_route_report(output_dir, request.task_id, decision, plan)

    final_status = decision.status
    if args.mode == "mock" and decision.status == "ROUTED" and plan.selected_provider_type == "mock_executor":
        run_mock_executor(request, plan, output_dir)
        target = ingest_execution_result(output_dir / "mock_result" / "execution_result_envelope.yml", output_dir)
        verdict = review_execution_result_with_3e(target.target_dir, output_dir / "review", ROOT / "config" / "review_policy.yml")
        final_status = verdict.status

    print(f"decision: {decision.status}")
    print(f"provider: {decision.selected_provider_id}")
    print(f"output: {output_dir}")
    if final_status != decision.status:
        print(f"review: {final_status}")
    if final_status in {"ROUTED", "DRY_RUN_ONLY", "PASS", "PASS_WITH_WARNINGS", "NEEDS_APPROVAL"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
