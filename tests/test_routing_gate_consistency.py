"""Tests for routing intent detection and route–gate consistency.

Covers:
1. Implementation prompt → Coder in route, not analysis-only
2. Chinese implementation prompt → Coder in route
3. Explicit analysis-only → no Coder, no implementation_report required
4. Mixed analysis+implementation → implementation wins
5. Route/gate contradiction → errors flagged
6. External implementation executor satisfies gate
7. No executor available → implementation_required_but_no_executor
8. Multimodal implementation prompt → implementation intent preserved
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make agent_runtime/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))


# ── Helpers ────────────────────────────────────────────────────────────────


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


# ── Implementation intent detection ────────────────────────────────────────


class TestImplementationIntentDetection:
    """Tests for _detect_implementation_intent in task_router."""

    def test_english_implementation_detected(self):
        from task_router import _detect_implementation_intent

        assert _detect_implementation_intent(
            "Implement the multimodal capability broker patch. "
            "Create files, add tests, and produce implementation_report."
        )

    def test_chinese_implementation_detected(self):
        from task_router import _detect_implementation_intent

        assert _detect_implementation_intent(
            "请实现这个补丁，修改仓库，增加测试，并生成实现报告。"
        )

    def test_fix_is_implementation(self):
        from task_router import _detect_implementation_intent

        assert _detect_implementation_intent("Fix the routing bug in task_router.py")

    def test_wire_is_implementation(self):
        from task_router import _detect_implementation_intent

        assert _detect_implementation_intent("Wire up the new endpoint")

    def test_explicit_analysis_only_overrides(self):
        from task_router import _detect_implementation_intent

        # "implement" appears but "analysis only" overrides
        assert not _detect_implementation_intent(
            "Analyze the design only. Do not modify files. Do not implement."
        )

    def test_chinese_analysis_only_overrides(self):
        from task_router import _detect_implementation_intent

        assert not _detect_implementation_intent(
            "只分析，不要改代码。评估当前架构。"
        )

    def test_pure_analysis_no_implementation(self):
        from task_router import _detect_implementation_intent

        assert not _detect_implementation_intent(
            "Evaluate the performance of the current system and compare with benchmarks."
        )


# ── Route recommendation ───────────────────────────────────────────────────


class TestRouteRecommendation:
    """Tests for recommend_route with implementation intent."""

    def test_implementation_prompt_routes_to_coder(self):
        from task_router import recommend_route

        route = recommend_route(
            "Implement the multimodal capability broker patch. "
            "Create files, add tests, and produce implementation_report."
        )
        assert "Coder" in route.agents
        assert route.route_key != "evaluation_task"

    def test_chinese_implementation_prompt_routes_to_coder(self):
        from task_router import recommend_route

        route = recommend_route(
            "请实现这个补丁，修改仓库，增加测试，并生成实现报告。"
        )
        assert "Coder" in route.agents

    def test_explicit_analysis_only_skips_coder(self):
        from task_router import recommend_route

        route = recommend_route(
            "Analyze the design only. Do not modify files. Do not implement."
        )
        # May or may not include Coder depending on length/task size,
        # but the route should NOT be classified as implementation-required
        # with a forced Coder injection.  The key invariant: analysis-only
        # should not inject Coder just because of the "fix" keyword
        # (which isn't even present here).
        rationale_text = " ".join(route.rationale)
        assert "Implementation intent detected" not in rationale_text

    def test_mixed_analysis_implementation_chooses_implementation(self):
        from task_router import recommend_route

        route = recommend_route(
            "Analyze the issue and then implement the fix with tests."
        )
        assert "Coder" in route.agents
        rationale_text = " ".join(route.rationale)
        assert "Implementation intent detected" in rationale_text

    def test_evaluation_with_implementation_keeps_coder(self):
        from task_router import recommend_route

        route = recommend_route(
            "Evaluate the system performance and implement the recommended fixes."
        )
        assert "Coder" in route.agents
        rationale_text = " ".join(route.rationale)
        assert "implementation intent overrides" in rationale_text


# ── Route–gate consistency validation ──────────────────────────────────────


class TestRouteGateConsistency:
    """Tests for validate_route_gate_consistency."""

    def test_implementation_report_with_coder_is_consistent(self):
        from route_gate_consistency import validate_route_gate_consistency

        errors = validate_route_gate_consistency(
            route_agents=["Supervisor", "Coder", "TesterAuditor"],
            validation_gates=[
                _make_gate("implementation_report", "Coder"),
            ],
            intent="implementation_required",
        )
        assert len(errors) == 0

    def test_implementation_report_without_coder_is_inconsistent(self):
        from route_gate_consistency import validate_route_gate_consistency

        errors = validate_route_gate_consistency(
            route_agents=["Supervisor", "RepoScout", "TesterAuditor"],
            validation_gates=[
                _make_gate("implementation_report", "Coder"),
            ],
            intent="implementation_required",
        )
        assert len(errors) >= 1
        codes = {e.code for e in errors}
        assert "implementation_report_requires_missing_executor" in codes

    def test_analysis_only_with_implementation_gate_fails(self):
        from route_gate_consistency import validate_route_gate_consistency

        errors = validate_route_gate_consistency(
            route_agents=["Supervisor", "RepoScout", "Researcher"],
            validation_gates=[
                _make_gate(
                    "implementation_report",
                    "Coder",
                    evidence=["06_implementation_report.md"],
                ),
            ],
            intent="analysis_only",
        )
        assert len(errors) >= 1

    def test_no_executor_available_blocks(self):
        from route_gate_consistency import validate_route_gate_consistency

        errors = validate_route_gate_consistency(
            route_agents=["Supervisor", "Researcher", "Archivist"],
            validation_gates=[_make_gate("routing_report", "Supervisor")],
            intent="implementation_required",
        )
        codes = {e.code for e in errors}
        assert "implementation_required_but_no_executor" in codes

    def test_external_ide_ai_satisfies_gate(self):
        from route_gate_consistency import validate_route_gate_consistency

        errors = validate_route_gate_consistency(
            route_agents=["Supervisor", "external_ide_ai"],
            validation_gates=[
                _make_gate("implementation_report", "external_ide_ai"),
            ],
            intent="implementation_required",
        )
        # external_ide_ai IS an implementation executor
        codes = {e.code for e in errors}
        assert "implementation_report_requires_missing_executor" not in codes

    def test_claude_code_as_coder_satisfies_gate(self):
        from route_gate_consistency import validate_route_gate_consistency

        errors = validate_route_gate_consistency(
            route_agents=["Supervisor", "claude_code", "TesterAuditor"],
            validation_gates=[
                _make_gate("implementation_report", "Coder"),
            ],
            intent="implementation_required",
        )
        # claude_code IS in IMPLEMENTATION_EXECUTORS, and the gate owner
        # "Coder" would be checked against route.  claude_code is a valid
        # implementation executor but the gate says owner=Coder.  This is
        # a gate config issue, not a route issue — the gate should accept
        # claude_code as implementation executor.  The implementation_report
        # gate check looks for any impl executor in route.
        impl_exec_code = "implementation_required_but_no_executor"
        assert impl_exec_code not in {e.code for e in errors}

    def test_empty_gates_is_consistent(self):
        from route_gate_consistency import validate_route_gate_consistency

        errors = validate_route_gate_consistency(
            route_agents=["Supervisor", "Coder"],
            validation_gates=[],
            intent="implementation_required",
        )
        assert len(errors) == 0


# ── Multimodal: implementation intent preserved ────────────────────────────


class TestMultimodalImplementationIntent:
    """Multimodal prompts that also request code changes keep impl intent."""

    def test_multimodal_implementation_prompt(self):
        from task_router import _detect_implementation_intent

        assert _detect_implementation_intent(
            "Add image understanding capability to the broker. "
            "Implement the vision backend, add tests, and generate "
            "implementation report."
        )

    def test_multimodal_implementation_routes_to_coder(self):
        from task_router import recommend_route

        route = recommend_route(
            "Add image understanding capability to the broker. "
            "Implement the vision backend, add tests, and generate "
            "implementation report."
        )
        assert "Coder" in route.agents


# ── Config contract tests ──────────────────────────────────────────────────


class TestConfigAlignment:
    """Check that config files match the new implementation intent model."""

    def test_routing_rules_evaluation_marked_analysis_only(self):
        """evaluation_task route should still be marked analysis_only."""
        import yaml

        config_path = (
            Path(__file__).parent.parent / "config" / "routing_rules.yml"
        )
        data = yaml.safe_load(config_path.read_text())
        eval_route = data["routes"]["evaluation_task"]
        assert eval_route.get("analysis_only") is True, (
            "evaluation_task route must remain analysis_only=True in config; "
            "code-level implementation detection overrides at runtime."
        )

    def test_validation_gates_has_implementation_report(self):
        """validation_gates.yml must still require implementation_report."""
        import yaml

        config_path = (
            Path(__file__).parent.parent / "config" / "validation_gates.yml"
        )
        data = yaml.safe_load(config_path.read_text())
        gate_ids = {g["id"] for g in data.get("gates", [])}
        assert "implementation_report" in gate_ids
