#!/usr/bin/env python3
"""Run the P2-F closure workflow: review → verdict → revision → governance → router feedback."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.p2_closure import run_p2_closure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AgentLab P2-F Closure workflow")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--delivery-path", required=True, help="Path to delivery artifact directory")
    parser.add_argument("--output-dir", required=True, help="Directory for closure outputs")
    parser.add_argument("--provider-id", default=None, help="Provider identifier")
    parser.add_argument("--executor", default=None, help="Executor identifier")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default)")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Disable dry-run")
    parser.add_argument("--allow-router-apply", action="store_true", default=False, help="Allow router apply if approval exists")
    parser.add_argument("--approval-path", default=None, help="Path to approval artifact directory/file")
    parser.add_argument("--config-root", default=None, help="Path to config directory (default: repo config/)")
    args = parser.parse_args(argv)

    delivery_path = Path(args.delivery_path)
    if not delivery_path.is_absolute():
        delivery_path = (ROOT / delivery_path).resolve()
    if not delivery_path.is_dir():
        print(f"ERROR: delivery-path does not exist or is not a directory: {delivery_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (ROOT / output_dir).resolve()

    config_root = Path(args.config_root) if args.config_root else ROOT / "config"
    if not config_root.is_absolute():
        config_root = (ROOT / config_root).resolve()

    approval_path = Path(args.approval_path) if args.approval_path else None
    if approval_path and not approval_path.is_absolute():
        approval_path = (ROOT / approval_path).resolve()

    result = run_p2_closure(
        task_id=args.task_id,
        delivery_path=delivery_path,
        output_dir=output_dir,
        config_root=config_root,
        provider_id=args.provider_id,
        executor=args.executor,
        dry_run=args.dry_run,
        allow_router_apply=args.allow_router_apply,
        approval_path=approval_path,
    )

    print(f"P2 closure verdict: {result.verdict_status}")
    print(f"Review verdict: {result.review_verdict_path}")
    if result.revision_packet_path:
        print(f"Revision packet: {result.revision_packet_path}")
    else:
        print("Revision packet: not required")
    print(f"Provider feedback: {result.provider_feedback_path}")
    print(f"Router feedback: {result.router_feedback_path}")
    if result.router_dry_run_path:
        print(f"Router update: dry-run written")
    if result.router_apply_result_path:
        print(f"Router apply result: {result.router_apply_result_path}")
    if result.router_rollback_path:
        print(f"Router rollback plan: {result.router_rollback_path}")
    print(f"Closure report: {result.closure_report_path}")

    return 0 if result.verdict_status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
