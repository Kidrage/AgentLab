#!/usr/bin/env python3
"""Run the deterministic AgentLab P2 3E reviewer workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.review import ReviewTarget, load_review_policy, run_three_e_review


def build_target(target_dir: Path, task_id: str | None = None) -> ReviewTarget:
    return ReviewTarget(
        task_id=task_id or target_dir.name,
        target_dir=target_dir,
        handoff_path=target_dir / "external_handoff.md",
        report_path=target_dir / "p1_acceptance_report.md",
    )


def run_review(target_dir: Path, output_dir: Path, task_id: str | None = None) -> dict[str, str]:
    policy = load_review_policy(ROOT / "config" / "review_policy.yml")
    target = build_target(target_dir, task_id=task_id)
    report = run_three_e_review(target, policy, output_dir)
    return {
        "verdict": report.verdict.status,
        "review_report": str(report.markdown_path),
        "review_report_yml": str(report.yaml_path),
        "retry_handoff": str(report.retry_handoff.path) if report.retry_handoff else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AgentLab P2 3E reviewer")
    parser.add_argument("--target", required=True, help="Delivery artifact directory to review")
    parser.add_argument("--output", required=True, help="Directory for review outputs")
    parser.add_argument("--task-id", default=None, help="Optional review task id")
    args = parser.parse_args(argv)

    target_dir = (ROOT / args.target).resolve() if not Path(args.target).is_absolute() else Path(args.target)
    output_dir = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    result = run_review(target_dir, output_dir, task_id=args.task_id)
    print(f"verdict: {result['verdict']}")
    print(f"review_report: {result['review_report']}")
    if result["retry_handoff"]:
        print(f"retry_handoff: {result['retry_handoff']}")
    return 0 if result["verdict"] in {"PASS", "PASS_WITH_WARNINGS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
