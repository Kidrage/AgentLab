#!/usr/bin/env python3
"""Run deterministic P2-E governance-aware router update checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.router_update import (
    apply_router_policy_patch,
    build_router_policy_patch,
    create_router_patch_approval_request,
    create_router_rollback_plan,
    load_router_policy,
    load_router_update_policy,
    load_routing_recommendations,
    validate_router_policy,
    write_router_patch_artifacts,
)
from agent_runtime.router_update.ledger import record_router_update_event


DEFAULT_UPDATE_POLICY = ROOT / "config" / "router_update_policy.yml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage, approve, apply, and validate router policy patches")
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage")
    stage.add_argument("--recommendations", required=True)
    stage.add_argument("--router-policy", required=True)
    stage.add_argument("--output", required=True)
    stage.add_argument("--update-policy", default=str(DEFAULT_UPDATE_POLICY))

    apply_copy = sub.add_parser("apply-copy")
    apply_copy.add_argument("--router-policy", required=True)
    apply_copy.add_argument("--patch", required=True)
    apply_copy.add_argument("--output", required=True)
    apply_copy.add_argument("--approval-dir", required=True)
    apply_copy.add_argument("--update-policy", default=str(DEFAULT_UPDATE_POLICY))

    validate = sub.add_parser("validate")
    validate.add_argument("--router-policy", required=True)

    args = parser.parse_args(argv)
    if args.command == "stage":
        return _stage(args)
    if args.command == "apply-copy":
        return _apply_copy(args)
    if args.command == "validate":
        return _validate(args)
    return 2


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _stage(args: argparse.Namespace) -> int:
    recommendations_path = _path(args.recommendations)
    router_policy_path = _path(args.router_policy)
    output_dir = _path(args.output)
    update_policy_path = _path(args.update_policy)
    recommendations = load_routing_recommendations(recommendations_path)
    router_policy = load_router_policy(router_policy_path)
    update_policy = load_router_update_policy(update_policy_path)
    patch = build_router_policy_patch(recommendations, router_policy, update_policy, output_dir)
    patch.source_recommendations_path = str(recommendations_path)
    patch.router_policy_path = str(router_policy_path)
    artifacts = write_router_patch_artifacts(output_dir, patch, router_policy)
    create_router_patch_approval_request(patch, update_policy, output_dir)
    create_router_rollback_plan(router_policy, router_policy, patch, output_dir)
    record_router_update_event(output_dir / "router_update_ledger.yml", "patch_staged", patch.patch_id, "STAGED", ["router policy patch staged"], artifacts.values())
    record_router_update_event(output_dir / "router_update_ledger.yml", "approval_requested", patch.patch_id, "APPROVAL_REQUIRED" if patch.requires_human_approval else "NO_OP", ["approval request generated"], [output_dir / "approval_request.yml", output_dir / "approval_request.md"])
    print(f"patch: {output_dir / 'router_policy_patch.yml'}")
    print(f"approval: {output_dir / 'approval_request.yml'}")
    return 0


def _apply_copy(args: argparse.Namespace) -> int:
    result = apply_router_policy_patch(
        router_policy_path=_path(args.router_policy),
        patch_path=_path(args.patch),
        update_policy_path=_path(args.update_policy),
        output_path=_path(args.output),
        approval_dir=_path(args.approval_dir),
    )
    print(f"status: {result.status}")
    for reason in result.reasons:
        print(f"reason: {reason}")
    return 0 if result.applied else 1


def _validate(args: argparse.Namespace) -> int:
    policy = load_router_policy(_path(args.router_policy))
    errors = validate_router_policy(policy)
    if errors:
        for error in errors:
            print(f"validation error: {error}")
        return 1
    print("validation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
