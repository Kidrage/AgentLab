#!/usr/bin/env python3
"""Mainline baseline acceptance script for P0/P1/P2.

Verifies that all known AgentLab baseline modules exist, import correctly,
and expose the expected API surface. Does NOT execute external skills,
external agents, or any network operations.

Exit code 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))


@dataclass
class ModuleCheck:
    name: str
    priority: str
    module_path: str
    exists: bool = False
    importable: bool = False
    expected_symbols: list[str] = field(default_factory=list)
    found_symbols: list[str] = field(default_factory=list)
    missing_symbols: list[str] = field(default_factory=list)
    notes: str = ""
    verdict: str = "PENDING"


def _check_module(
    name: str,
    priority: str,
    module_path: str,
    expected_symbols: list[str] | None = None,
) -> ModuleCheck:
    check = ModuleCheck(
        name=name,
        priority=priority,
        module_path=module_path,
        expected_symbols=expected_symbols or [],
    )
    rel = module_path.replace(".", "/") + ".py"
    check.exists = (ROOT / rel).exists()
    if not check.exists:
        check.verdict = "FAIL"
        check.notes = f"File not found: {rel}"
        return check

    try:
        mod = importlib.import_module(module_path)
        check.importable = True
    except Exception as exc:
        check.verdict = "FAIL"
        check.notes = f"Import failed: {exc}"
        return check

    if check.expected_symbols:
        for sym in check.expected_symbols:
            if hasattr(mod, sym):
                check.found_symbols.append(sym)
            else:
                check.missing_symbols.append(sym)
        if check.missing_symbols:
            check.verdict = "WARN"
            check.notes = f"Missing symbols: {check.missing_symbols}"
        else:
            check.verdict = "PASS"
    else:
        check.verdict = "PASS"

    return check


def run_baseline_checks() -> list[ModuleCheck]:
    results: list[ModuleCheck] = []

    # ── P0: Core Infrastructure ──────────────────────────────────────

    results.append(_check_module(
        "CostLedger v2",
        "P0",
        "agent_runtime.costing.ledger",
        ["CostLedger", "CostCall", "write_cost_artifacts"],
    ))
    results.append(_check_module(
        "Cost Pricing",
        "P0",
        "agent_runtime.costing.pricing",
        ["PriceInfo", "PriceResolver"],
    ))
    results.append(_check_module(
        "BudgetGate",
        "P0",
        "agent_runtime.costing.budget",
        ["BudgetDecision", "evaluate_budget_gate"],
    ))
    results.append(_check_module(
        "Budget Planner",
        "P0",
        "agent_runtime.budget_planner",
        ["build_token_budgets", "select_budget_profile_key"],
    ))
    results.append(_check_module(
        "RepoManifest",
        "P0",
        "agent_runtime.ingestion.repo_manifest",
        ["RepoManifest", "write_repo_manifest"],
    ))
    results.append(_check_module(
        "CloneGuard",
        "P0",
        "agent_runtime.ingestion.clone_guard",
        ["CloneGuardDecision", "evaluate_command"],
    ))
    results.append(_check_module(
        "ResourceLedger",
        "P0",
        "agent_runtime.ingestion.resource_ledger",
        ["ResourceLedger", "load_resource_ledger", "write_resource_ledger"],
    ))
    results.append(_check_module(
        "Artifact Evidence Gate",
        "P0",
        "agent_runtime.artifact_contract",
        ["validate_artifacts", "is_tbd_or_empty", "required_artifacts_for_route"],
    ))
    results.append(_check_module(
        "Pipeline Runner",
        "P0",
        "agent_runtime.pipeline_runner",
        ["run_next_node"],
    ))
    results.append(_check_module(
        "Cost Tracker",
        "P0",
        "agent_runtime.cost_tracker",
        ["load_pricing", "estimate_cost"],
    ))

    # ── P1: External Integration ─────────────────────────────────────

    results.append(_check_module(
        "External Skill Registry",
        "P1",
        "agent_runtime.skills.registry",
        ["ExternalSkill", "load_skill_registry", "add_or_update_skill",
         "assert_skill_dispatchable"],
    ))
    results.append(_check_module(
        "ECC Inventory",
        "P1",
        "agent_runtime.external_agents.ecc_inventory",
        ["scan_ecc_inventory", "load_ecc_config"],
    ))
    results.append(_check_module(
        "External Agent Handoff",
        "P1",
        "agent_runtime.external_agents.handoff",
        ["ExternalHandoff", "build_external_handoff", "write_external_handoff"],
    ))
    results.append(_check_module(
        "AnySearch Adapter",
        "P1",
        "agent_runtime.search.anysearch_adapter",
        ["AnySearchAdapter"],
    ))
    results.append(_check_module(
        "CodeGraph Adapter",
        "P1",
        "agent_runtime.ingestion.repo_indexers.codegraph_adapter",
        ["CodeGraphAdapter"],
    ))
    results.append(_check_module(
        "Search Provider Base",
        "P1",
        "agent_runtime.search.provider",
        ["SearchProvider", "SearchResponse", "SearchResult"],
    ))
    results.append(_check_module(
        "Local URL Reader",
        "P1",
        "agent_runtime.search.local_url_reader",
        ["LocalUrlReader"],
    ))

    # ── P2: Review, Retry, Governance, Recovery ──────────────────────

    results.append(_check_module(
        "3E Reviewer",
        "P2",
        "agent_runtime.review.three_e_reviewer",
        ["run_three_e_review", "explore_review_target", "derive_review_verdict"],
    ))
    results.append(_check_module(
        "Review Models",
        "P2",
        "agent_runtime.review.models",
        ["ReviewTarget", "ReviewReport", "ReviewVerdict"],
    ))
    results.append(_check_module(
        "Retry Manager",
        "P2",
        "agent_runtime.retry.retry_manager",
        ["run_acceptance_retry_loop", "decide_retry_action"],
    ))
    results.append(_check_module(
        "Retry Policy",
        "P2",
        "agent_runtime.retry.policy",
        ["load_retry_policy"],
    ))
    results.append(_check_module(
        "Provider Scorecard",
        "P2",
        "agent_runtime.retry.scorecard",
        ["load_provider_scorecard", "update_provider_scorecard"],
    ))
    results.append(_check_module(
        "Router Update Patch Applier",
        "P2",
        "agent_runtime.router_update.patch_applier",
        ["apply_router_policy_patch", "validate_router_policy"],
    ))
    results.append(_check_module(
        "Router Update Patch Builder",
        "P2",
        "agent_runtime.router_update.patch_builder",
        ["build_router_policy_patch"],
    ))
    results.append(_check_module(
        "Context Governance",
        "P2",
        "agent_runtime.context_governance.context_pack",
        ["build_context_artifacts", "write_context_artifacts", "context_summary"],
    ))
    results.append(_check_module(
        "P2 Closure Runner",
        "P2",
        "agent_runtime.p2_closure.closure_runner",
        ["run_p2_closure"],
    ))
    results.append(_check_module(
        "P2 Capability Map",
        "P2",
        "agent_runtime.p2_closure.capability_map",
        ["scan_p2_capabilities", "write_capability_map"],
    ))
    results.append(_check_module(
        "Governance Performance",
        "P2",
        "agent_runtime.governance.performance",
        ["build_provider_performance_profiles", "derive_governance_decisions"],
    ))
    results.append(_check_module(
        "Governance Cost",
        "P2",
        "agent_runtime.governance.cost",
        ["build_provider_cost_profiles"],
    ))
    results.append(_check_module(
        "Routing Feedback",
        "P2",
        "agent_runtime.governance.routing_feedback",
        ["generate_routing_recommendations"],
    ))

    # ── P2-I: Failure Recovery ───────────────────────────────────────

    results.append(_check_module(
        "Failure Event Capture",
        "P2",
        "agent_runtime.recovery.failure_event",
        ["FailureEvent", "create_failure_event"],
    ))
    results.append(_check_module(
        "Failure Classifier",
        "P2",
        "agent_runtime.recovery.failure_classifier",
        ["FailureCategory", "FailureClassifier"],
    ))
    results.append(_check_module(
        "Failure Diagnosis",
        "P2",
        "agent_runtime.recovery.diagnosis",
        ["FailureDiagnosis", "diagnose_failure"],
    ))
    results.append(_check_module(
        "Recovery Plan",
        "P2",
        "agent_runtime.recovery.recovery_plan",
        ["RecoveryPlan", "build_recovery_plan"],
    ))
    results.append(_check_module(
        "Recovery Verdict",
        "P2",
        "agent_runtime.recovery.verdict",
        ["RecoveryVerdict", "VerdictType"],
    ))
    results.append(_check_module(
        "Retry Policy (Recovery)",
        "P2",
        "agent_runtime.recovery.retry_policy",
        ["RetryPolicyConfig", "decide_retry_action"],
    ))
    results.append(_check_module(
        "Human Review",
        "P2",
        "agent_runtime.recovery.human_review",
        ["HumanReviewDecision", "DecisionType"],
    ))
    results.append(_check_module(
        "Resume Policy",
        "P2",
        "agent_runtime.recovery.resume_policy",
        ["derive_recovery_next_action"],
    ))
    results.append(_check_module(
        "Recovery Closure",
        "P2",
        "agent_runtime.recovery.closure",
        ["build_recovery_closure_summary"],
    ))
    results.append(_check_module(
        "Closure Feedback",
        "P2",
        "agent_runtime.recovery.closure_feedback",
        ["ClosureQualityFeedback", "derive_closure_quality_feedback"],
    ))
    results.append(_check_module(
        "Context Redaction",
        "P2",
        "agent_runtime.recovery.redaction",
        ["redact_context_text"],
    ))

    return results


def print_report(results: list[ModuleCheck]) -> bool:
    total = len(results)
    passed = sum(1 for r in results if r.verdict == "PASS")
    warned = sum(1 for r in results if r.verdict == "WARN")
    failed = sum(1 for r in results if r.verdict == "FAIL")

    by_priority: dict[str, list[ModuleCheck]] = {}
    for r in results:
        by_priority.setdefault(r.priority, []).append(r)

    print("=" * 70)
    print("AgentLab Mainline Baseline Acceptance Report")
    print("=" * 70)
    print()

    for priority in ("P0", "P1", "P2"):
        checks = by_priority.get(priority, [])
        p_pass = sum(1 for c in checks if c.verdict == "PASS")
        p_warn = sum(1 for c in checks if c.verdict == "WARN")
        p_fail = sum(1 for c in checks if c.verdict == "FAIL")
        print(f"## {priority}: {p_pass} PASS, {p_warn} WARN, {p_fail} FAIL")
        print()
        for c in checks:
            status_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(c.verdict, "?")
            print(f"  {status_icon} {c.name} ({c.module_path})")
            if c.notes:
                print(f"     → {c.notes}")
        print()

    print("-" * 70)
    print(f"TOTAL: {total} checks | {passed} PASS | {warned} WARN | {failed} FAIL")
    print("-" * 70)

    all_ok = failed == 0
    print(f"\nVerdict: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def main() -> None:
    results = run_baseline_checks()
    all_ok = print_report(results)
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
