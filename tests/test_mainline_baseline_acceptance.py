from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))


def _load_baseline_module():
    spec = importlib.util.spec_from_file_location(
        "mainline_baseline_acceptance",
        ROOT / "scripts" / "mainline_baseline_acceptance.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mainline_baseline_acceptance"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── P0 Core Infrastructure ─────────────────────────────────────────


def test_p0_cost_ledger_v2_imports() -> None:
    from costing.ledger import CostLedger, CostCall, write_cost_artifacts
    assert CostLedger is not None
    assert CostCall is not None
    assert write_cost_artifacts is not None


def test_p0_budget_gate_imports() -> None:
    from costing.budget import BudgetDecision, evaluate_budget_gate
    assert BudgetDecision is not None
    assert evaluate_budget_gate is not None


def test_p0_repo_manifest_imports() -> None:
    from ingestion.repo_manifest import RepoManifest, write_repo_manifest
    assert RepoManifest is not None
    assert write_repo_manifest is not None


def test_p0_clone_guard_imports() -> None:
    from ingestion.clone_guard import CloneGuardDecision, evaluate_command
    assert CloneGuardDecision is not None
    assert evaluate_command is not None


def test_p0_resource_ledger_imports() -> None:
    from ingestion.resource_ledger import ResourceLedger
    assert ResourceLedger is not None


def test_p0_artifact_contract_imports() -> None:
    from artifact_contract import validate_artifacts, required_artifacts_for_route
    assert validate_artifacts is not None
    assert required_artifacts_for_route is not None


def test_p0_pipeline_runner_imports() -> None:
    from pipeline_runner import run_next_node
    assert run_next_node is not None


# ── P1 External Integration ────────────────────────────────────────


def test_p1_skill_registry_imports() -> None:
    from skills.registry import (
        ExternalSkill,
        load_skill_registry,
        add_or_update_skill,
        assert_skill_dispatchable,
    )
    assert ExternalSkill is not None
    assert load_skill_registry is not None
    assert add_or_update_skill is not None
    assert assert_skill_dispatchable is not None


def test_p1_ecc_inventory_imports() -> None:
    from external_agents.ecc_inventory import scan_ecc_inventory
    assert scan_ecc_inventory is not None


def test_p1_external_handoff_imports() -> None:
    from external_agents.handoff import (
        ExternalHandoff,
        build_external_handoff,
    )
    assert ExternalHandoff is not None
    assert build_external_handoff is not None


def test_p1_anysearch_adapter_imports() -> None:
    from search.anysearch_adapter import AnySearchAdapter
    assert AnySearchAdapter is not None


def test_p1_anysearch_default_disabled() -> None:
    data = yaml.safe_load(
        (ROOT / "config" / "search_providers.yml").read_text(encoding="utf-8")
    )
    anysearch_cfg = data.get("anysearch", data.get("providers", {}).get("anysearch", {}))
    if isinstance(anysearch_cfg, dict):
        assert anysearch_cfg.get("enabled", False) is False


def test_p1_codegraph_adapter_imports() -> None:
    from ingestion.repo_indexers.codegraph_adapter import CodeGraphAdapter
    assert CodeGraphAdapter is not None


def test_p1_external_skills_not_auto_executed_in_tests() -> None:
    """Verify no test file directly invokes external skill scripts via OS."""
    tests_dir = ROOT / "tests"
    dangerous_patterns = [
        r'os\.system\s*\(\s*["\'].*skill',
        r'subprocess\.\w+\s*\(\s*\[.*["\'].*ecc_.*\.sh',
        r'subprocess\.\w+\s*\(\s*\[.*["\'].*external.*skill.*\.py',
    ]
    for test_file in sorted(tests_dir.glob("test_*.py")):
        content = test_file.read_text(encoding="utf-8")
        for pattern in dangerous_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            assert not matches, (
                f"{test_file.name} contains suspicious external skill execution: {matches}"
            )


# ── P2 Review / Retry / Governance / Recovery ──────────────────────


def test_p2_three_e_reviewer_imports() -> None:
    from review.three_e_reviewer import (
        run_three_e_review,
        explore_review_target,
        derive_review_verdict,
    )
    assert run_three_e_review is not None


def test_p2_retry_manager_imports() -> None:
    from retry.retry_manager import (
        run_acceptance_retry_loop,
        decide_retry_action,
    )
    assert run_acceptance_retry_loop is not None


def test_p2_router_update_imports() -> None:
    from router_update.patch_applier import (
        apply_router_policy_patch,
        validate_router_policy,
    )
    assert apply_router_policy_patch is not None


def test_p2_context_governance_imports() -> None:
    from context_governance.context_pack import (
        build_context_artifacts,
        write_context_artifacts,
    )
    assert build_context_artifacts is not None


def test_p2_closure_runner_imports() -> None:
    from p2_closure.closure_runner import run_p2_closure
    assert run_p2_closure is not None


def test_p2_failure_event_imports() -> None:
    from recovery.failure_event import FailureEvent, create_failure_event
    assert FailureEvent is not None


def test_p2_failure_classifier_imports() -> None:
    from recovery.failure_classifier import (
        FailureCategory,
        FailureClassifier,
    )
    assert FailureCategory is not None
    assert FailureClassifier is not None


def test_p2_diagnosis_imports() -> None:
    from recovery.diagnosis import FailureDiagnosis, diagnose_failure
    assert FailureDiagnosis is not None


def test_p2_recovery_plan_imports() -> None:
    from recovery.recovery_plan import RecoveryPlan, build_recovery_plan
    assert RecoveryPlan is not None


def test_p2_human_review_imports() -> None:
    from recovery.human_review import HumanReviewDecision, DecisionType
    assert HumanReviewDecision is not None


def test_p2_closure_feedback_imports() -> None:
    from recovery.closure_feedback import (
        ClosureQualityFeedback,
        derive_closure_quality_feedback,
    )
    assert ClosureQualityFeedback is not None


def test_p2_governance_performance_imports() -> None:
    from governance.performance import (
        build_provider_performance_profiles,
        derive_governance_decisions,
    )
    assert build_provider_performance_profiles is not None


# ── Baseline Script ────────────────────────────────────────────────


def test_baseline_acceptance_script_runs_cleanly() -> None:
    mod = _load_baseline_module()
    results = mod.run_baseline_checks()
    failed = [r for r in results if r.verdict == "FAIL"]
    assert not failed, f"Baseline checks failed: {[r.name for r in failed]}"


def test_baseline_acceptance_script_covers_all_priorities() -> None:
    mod = _load_baseline_module()
    results = mod.run_baseline_checks()
    priorities = {r.priority for r in results}
    assert "P0" in priorities
    assert "P1" in priorities
    assert "P2" in priorities


# ── CLI Smoke ──────────────────────────────────────────────────────


def test_cli_help_runs() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "agentlab.sh"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0


def test_cli_run_pipeline_help_runs() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "agentlab.sh"), "run-pipeline", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0


def test_cli_help_shows_recovery_commands() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "agentlab.sh"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout
    expected_commands = [
        "failure-diagnose",
        "failure-status",
        "recovery-plan",
        "recovery-smoke",
        "recovery-approve",
        "recovery-reject",
        "recovery-stop",
        "recovery-status",
        "recovery-feedback",
    ]
    for cmd in expected_commands:
        assert cmd in output, f"CLI --help missing recovery command: {cmd}"
