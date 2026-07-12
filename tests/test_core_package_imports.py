from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_brain_modules_import_as_packages() -> None:
    import agent_runtime.budget_planner  # noqa: F401
    import agent_runtime.cli_executor  # noqa: F401
    import agent_runtime.model_resolver  # noqa: F401
    import agent_runtime.skill_injector  # noqa: F401
    import agent_runtime.skill_usage  # noqa: F401
    import agent_runtime.state_store  # noqa: F401
    import agent_runtime.task_router  # noqa: F401
    import agent_runtime.workflow_plan  # noqa: F401


def test_workflow_plan_builds_without_package_import_degradation(tmp_path: Path) -> None:
    from agent_runtime.workflow_plan import build_workflow_plan

    request_path = tmp_path / "user_request.md"
    request_path.write_text("设计一个 AgentLab 状态总览网页端 UI。", encoding="utf-8")

    plan = build_workflow_plan(
        ROOT,
        "AgentLab",
        "task_package_import_probe_pytest",
        user_request_path=request_path,
    )

    assert plan.route.route_key == "interface_sensitive_task"
    assert plan.production_pack["pack_id"] == "code_factory"
    assert isinstance(plan.skills, dict)
    assert "error" not in plan.skills
    assert isinstance(plan.artifact_intent, dict)
    assert "error" not in plan.artifact_intent
