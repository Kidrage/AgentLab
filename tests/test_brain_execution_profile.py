from __future__ import annotations

from pathlib import Path
import sys

from agent_runtime.brain.task_compiler import compile_task_packet


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agent_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from task_router import recommend_route  # noqa: E402
from task_snapshot import build_task_snapshot  # noqa: E402
from workflow_plan import build_workflow_plan  # noqa: E402


def test_brain_profile_keeps_network_permission_failures_lightweight() -> None:
    result = compile_task_packet(
        "Fix a small repo bug. If network or permission checks fail, use a mock-first recovery plan and do not collapse the whole pipeline.",
        task_id="lightweight_failure_boundary",
        project="AgentLab",
    )

    profile = result.execution_profile
    assert profile["task_size"] == "small"
    assert profile["route_key_hint"] == "small_task"
    assert profile["budget_mode"] == "balanced"
    assert "network_calls_require_policy_and_allowlist" in profile["boundaries"]
    assert "permission_errors_stop_at_recovery_plan" in profile["boundaries"]


def test_brain_profile_marks_large_work_as_phase_split_not_blind_expansion() -> None:
    result = compile_task_packet(
        "Refactor the AgentLab architecture for a large task orchestration platform with multi-module routing, governance, and phase acceptance.",
        task_id="large_phase_split",
        project="AgentLab",
    )

    profile = result.execution_profile
    assert profile["task_size"] == "large"
    assert profile["route_key_hint"] == "large_or_risky_task"
    assert any("split phases" in item for item in profile["rationale"])
    assert "plan_first_no_execution" in profile["boundaries"]


def test_task_router_prefers_brain_profile_over_keyword_size_guess() -> None:
    route = recommend_route(
        "Architecture migration permission network platform rewrite.",
        brain_profile={
            "task_size": "small",
            "risk_level": "R1",
            "route_key_hint": "small_task",
            "boundaries": ["plan_first_no_execution"],
            "rationale": ["Brain decided this is a narrow first-phase patch."],
        },
    )

    assert route.task_size == "small"
    assert route.route_key == "small_task"
    assert "Brain execution profile selected route before keyword fallback." in route.rationale


def test_workflow_plan_records_brain_execution_profile(tmp_path: Path) -> None:
    request = tmp_path / "user_request.md"
    request.write_text(
        "Fix a small repo bug. If network or permission checks fail, write a recovery note and keep the task lightweight.",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        ROOT,
        "AgentLab",
        "brain_execution_profile_test",
        user_request_path=request,
        budget_mode=None,
    )

    assert plan.execution_profile["route_key_hint"] == "small_task"
    assert plan.route.route_key == "small_task"
    assert plan.budget_mode == "balanced"
    assert any("Brain execution profile" in note for note in plan.notes)
    controls = plan.route_controls
    assert controls["source"] == "brain_execution_profile"
    assert controls["mock_first"] is True
    assert controls["failure_policy"] == "recoverable_boundary"
    assert "permission_errors_stop_at_recovery_plan" in controls["recovery_boundaries"]
    assert "Researcher" in controls["skipped_agent_reasons"]
    assert "recovery/recovery_plan.md" in controls["recovery_artifacts_if_blocked"]


def test_task_snapshot_exposes_route_controls(tmp_path: Path) -> None:
    run_dir = tmp_path / "task_route_controls"
    run_dir.mkdir()
    (run_dir / "workflow_plan.yml").write_text(
        """
route:
  agents:
    - Supervisor
    - Coder
route_controls:
  source: brain_execution_profile
  failure_policy: recoverable_boundary
  mock_first: true
  recovery_boundaries:
    - network_calls_require_policy_and_allowlist
""",
        encoding="utf-8",
    )

    snapshot = build_task_snapshot(run_dir, project="AgentLab", task_id="task_route_controls")

    assert snapshot["status"] == "planned"
    assert snapshot["route_controls"]["source"] == "brain_execution_profile"
    assert snapshot["route_controls"]["mock_first"] is True
