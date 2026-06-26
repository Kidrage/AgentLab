#!/usr/bin/env python3
"""Acceptance script: deterministic route–gate consistency checks.

Runs a fixed set of fixture prompts through the routing and consistency
pipeline, printing intent, route, executors, artifacts, and gate consistency.

Exit 0 = all fixtures consistent or correctly flagged.
Exit 1 = a contradiction was silently accepted.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure agent_runtime/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent_runtime"))

from task_router import _detect_implementation_intent, recommend_route  # noqa: E402
from route_gate_consistency import (  # noqa: E402
    IMPLEMENTATION_EXECUTORS,
    RouteGateConsistencyError,
    validate_route_gate_consistency,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

FIXTURES: list[dict] = [
    {
        "case": "analysis_only_prompt",
        "prompt": (
            "Analyze the design only. Do not modify files. Do not implement."
        ),
        "expect_impl_intent": False,
        "expect_coder_in_route": False,
        "expect_impl_gate_required": False,
    },
    {
        "case": "implementation_prompt",
        "prompt": (
            "Implement the multimodal capability broker patch. "
            "Create files, add tests, and produce implementation_report."
        ),
        "expect_impl_intent": True,
        "expect_coder_in_route": True,
        "expect_impl_gate_required": True,
    },
    {
        "case": "chinese_implementation_prompt",
        "prompt": (
            "请实现这个补丁，修改仓库，增加测试，并生成实现报告。"
        ),
        "expect_impl_intent": True,
        "expect_coder_in_route": True,
        "expect_impl_gate_required": True,
    },
    {
        "case": "mixed_analysis_implementation_prompt",
        "prompt": (
            "Analyze the issue and then implement the fix with tests."
        ),
        "expect_impl_intent": True,
        "expect_coder_in_route": True,
        "expect_impl_gate_required": True,
    },
    {
        "case": "multimodal_implementation_prompt",
        "prompt": (
            "Add image understanding capability to the broker. "
            "Implement the vision backend, add tests, and generate "
            "implementation report."
        ),
        "expect_impl_intent": True,
        "expect_coder_in_route": True,
        "expect_impl_gate_required": True,
    },
]

CONTRADICTORY_FIXTURES: list[dict] = [
    {
        "case": "contradictory_route_gate_fixture",
        "route_agents": ["Supervisor", "RepoScout", "Researcher", "TesterAuditor", "Archivist"],
        "gates": [
            {"id": "implementation_report", "owner": "Coder", "required": True},
        ],
        "intent": "analysis_only",
        "expect_errors": True,
        "expect_codes": [
            "analysis_only_requires_implementation_artifact",
        ],
    },
    {
        "case": "no_executor_available_fixture",
        "route_agents": ["Supervisor", "Researcher", "Archivist"],
        "gates": [
            {"id": "routing_report", "owner": "Supervisor", "required": True},
        ],
        "intent": "implementation_required",
        "expect_errors": True,
        "expect_codes": [
            "implementation_required_but_no_executor",
        ],
    },
]


def _make_gate(
    gate_id: str,
    owner: str,
    required: bool = True,
    evidence: list[str] | None = None,
    required_artifacts: list[str] | None = None,
) -> dict:
    return {
        "id": gate_id,
        "owner": owner,
        "required": required,
        "evidence": evidence or [],
        "required_artifacts": required_artifacts or [],
    }


def main() -> int:
    errors = 0

    print("=" * 72)
    print("Route–Gate Consistency Acceptance Checks")
    print("=" * 72)

    # ── Phase 1: Route fixtures ─────────────────────────────────────────
    print("\n── Intent & Route Checks ──\n")
    print(
        f"{'case':<44s} "
        f"{'impl_intent':<12s} "
        f"{'coder':<7s} "
        f"{'route_key':<22s} "
        f"{'verdict'}"
    )
    print("-" * 95)

    for fix in FIXTURES:
        case = fix["case"]
        prompt = fix["prompt"]
        impl_intent = _detect_implementation_intent(prompt)
        route = recommend_route(prompt)
        coder_in_route = "Coder" in route.agents
        has_impl_exec = bool(set(route.agents) & IMPLEMENTATION_EXECUTORS)

        # Build validation gates based on route
        if has_impl_exec:
            gates = [
                _make_gate("implementation_report", "Coder"),
                _make_gate("validation_evidence", "TesterAuditor"),
            ]
        else:
            gates = [
                _make_gate("analysis_report", "Supervisor"),
            ]

        intent_str = "implementation_required" if impl_intent else "analysis_only"
        gate_errors = validate_route_gate_consistency(
            route.agents, gates, intent=intent_str
        )

        verdict = "PASS"
        if impl_intent != fix["expect_impl_intent"]:
            verdict = f"FAIL: impl_intent={impl_intent} != expected={fix['expect_impl_intent']}"
            errors += 1
        elif coder_in_route != fix["expect_coder_in_route"]:
            verdict = f"FAIL: coder_in_route={coder_in_route} != expected"
            errors += 1
        elif gate_errors:
            verdict = f"FAIL: gate errors={[e.code for e in gate_errors]}"
            errors += 1

        print(
            f"{case:<44s} "
            f"{str(impl_intent):<12s} "
            f"{str(coder_in_route):<7s} "
            f"{route.route_key:<22s} "
            f"{verdict}"
        )

    # ── Phase 2: Contradictory gate fixtures ─────────────────────────────
    print("\n── Contradiction Detection Checks ──\n")
    for fix in CONTRADICTORY_FIXTURES:
        case = fix["case"]
        actual_errors = validate_route_gate_consistency(
            fix["route_agents"],
            fix["gates"],
            intent=fix["intent"],
        )
        actual_codes = {e.code for e in actual_errors}
        expected_codes = set(fix["expect_codes"])
        missing = expected_codes - actual_codes

        verdict = "PASS" if not missing else f"FAIL: missing codes={missing}"
        if missing:
            errors += 1

        print(f"  {case}:")
        print(f"    route_agents: {fix['route_agents']}")
        print(f"    intent: {fix['intent']}")
        print(f"    gates: {[g['id'] for g in fix['gates']]}")
        print(f"    errors found: {actual_codes}")
        print(f"    verdict: {verdict}")
        print()

    # ── Summary ──────────────────────────────────────────────────────────
    print("=" * 72)
    if errors:
        print(f"❌ {errors} failure(s) detected.")
        return 1
    else:
        print("✅ All route–gate consistency checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
