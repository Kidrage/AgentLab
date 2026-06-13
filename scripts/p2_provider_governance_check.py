#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime.governance import (  # noqa: E402
    build_provider_cost_profiles,
    build_provider_performance_profiles,
    build_quarantine_recommendations,
    build_watchlist,
    derive_governance_decisions,
    discover_governance_inputs,
    generate_routing_recommendations,
    load_provider_governance_policy,
    write_governance_reports,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic provider performance and cost governance checks.")
    parser.add_argument("--input-root", default=".", help="Repository root containing executor_runs/ and retry_runs/.")
    parser.add_argument("--output", required=True, help="Directory for governance report artifacts.")
    parser.add_argument("--policy", default="config/provider_governance.yml", help="Provider governance policy YAML.")
    parser.add_argument("--router-policy", default="config/executor_router.yml", help="Executor router policy YAML to read.")
    parser.add_argument("--include-executor-runs", default="executor_runs", help="Executor runs directory under input root.")
    parser.add_argument("--include-retry-runs", default="retry_runs", help="Retry runs directory under input root.")
    parser.add_argument("--allow-quarantine-recommendations", action="store_true", help="Return exit code 0 when quarantine is recommended.")
    args = parser.parse_args(argv)

    input_root = Path(args.input_root)
    output_dir = Path(args.output)
    router_policy_path = Path(args.router_policy)

    policy = load_provider_governance_policy(Path(args.policy))
    input_bundle = discover_governance_inputs(input_root, args.include_executor_runs, args.include_retry_runs)
    profiles = build_provider_performance_profiles(input_bundle, policy)
    cost_profiles = build_provider_cost_profiles(input_bundle, profiles, policy, router_policy_path)
    decisions = derive_governance_decisions(profiles, cost_profiles, policy)
    watchlist = build_watchlist(decisions)
    quarantine = build_quarantine_recommendations(decisions, profiles)
    routing_recommendations, routing_warnings = generate_routing_recommendations(decisions, router_policy_path, output_dir)
    write_governance_reports(
        output_dir,
        input_bundle,
        profiles,
        cost_profiles,
        decisions,
        watchlist,
        quarantine,
        routing_recommendations,
        routing_warnings,
    )

    for warning in [*input_bundle.warnings, *routing_warnings]:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"wrote provider governance reports to {output_dir}")
    has_quarantine = any(item.status == "QUARANTINE_RECOMMENDED" for item in decisions)
    if has_quarantine and not args.allow_quarantine_recommendations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
