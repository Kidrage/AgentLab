#!/usr/bin/env python3
"""Run deterministic P2-C acceptance-to-retry loop checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.executors import ExecutionRequest
from agent_runtime.retry import run_acceptance_retry_loop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AgentLab P2-C acceptance-to-retry loop")
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--mode",
        choices=["dry-run", "mock-pass-first", "mock-fail-then-pass", "mock-fail-until-max", "manual-handoff"],
        default="mock-pass-first",
    )
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--router-policy", default=str(ROOT / "config" / "executor_router.yml"))
    parser.add_argument("--retry-policy", default=str(ROOT / "config" / "retry_policy.yml"))
    parser.add_argument("--review-policy", default=str(ROOT / "config" / "review_policy.yml"))
    args = parser.parse_args(argv)

    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    retry_policy = Path(args.retry_policy)
    if args.max_attempts is not None:
        retry_policy = _write_policy_override(retry_policy, output_dir, args.max_attempts)

    request = ExecutionRequest(
        task_id=output_dir.name,
        task_type=args.task_type,
        summary=args.summary,
        repo_path=ROOT,
        allowed_files=["agent_runtime/retry/retry_manager.py"],
        forbidden_files=[".env", ".git/", "secrets/"],
        required_capabilities=[args.task_type],
        risk_level="low",
        max_cost_usd=0.25,
        requires_review=True,
        evidence_required=["execution_result_envelope.yml", "result_summary.md", "changed_files.yml", "claimed_tests.yml"],
        bounded_scope=True,
        reversible=True,
        output_dir=output_dir,
    )
    state = run_acceptance_retry_loop(
        request=request,
        router_policy_path=Path(args.router_policy),
        retry_policy_path=retry_policy,
        review_policy_path=Path(args.review_policy),
        output_dir=output_dir,
        mode=args.mode,
    )
    print(f"status: {state.status}")
    print(f"accepted: {state.accepted}")
    print(f"attempts: {len(state.attempts)}")
    print(f"output: {output_dir}")
    if state.status in {"ACCEPTED", "NEEDS_MANUAL_APPROVAL"}:
        return 0
    return 1


def _write_policy_override(source: Path, output_dir: Path, max_attempts: int) -> Path:
    import yaml

    output_dir.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    data.setdefault("retry_policy", {}).setdefault("loop", {})["max_attempts_per_task"] = max_attempts
    path = output_dir / "retry_policy.effective.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
