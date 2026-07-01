"""v1.0 internal closed-loop guardrails."""

from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from agent_runtime.costing.facade import build_cost_state
from agent_runtime.operator_os.action_runtime import execute_operator_action
from agent_runtime.operator_os.state_model import build_operator_state
from agent_runtime.operator_os.timeline import build_timeline
from web_ui import server as web_server


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_operator_state_uses_canonical_timeline_builder() -> None:
    import agent_runtime.operator_os.state_model as state_model

    source = inspect.getsource(state_model)
    assert ("def " + "_build_full_timeline") not in source
    assert "build_timeline(project_root)" in source


def test_webui_mutations_use_operator_action_runtime_not_cost_ledger_or_executor() -> None:
    decision_source = inspect.getsource(web_server.handle_post_decision)
    agent_source = inspect.getsource(web_server.handle_run_agent)

    assert "execute_operator_action" in decision_source
    assert "cost_ledger.yml" not in decision_source
    assert "subprocess.run" not in decision_source

    assert "execute_operator_action" in agent_source
    assert "cost_ledger.yml" not in agent_source
    assert "subprocess.run" not in agent_source
    assert "external_executor_enablement" in agent_source


def test_operator_action_ledger_feeds_timeline_and_state(tmp_path: Path) -> None:
    project = "Demo"
    project_root = tmp_path / "projects" / project
    brain = project_root / "project_brain"
    brain.mkdir(parents=True)
    (project_root / "PROJECT_HANDOFF.md").write_text("# Demo\n", encoding="utf-8")
    _write_yaml(project_root / "project_artifact_index.yml", {"artifacts": []})
    _write_yaml(brain / "acceptance_history.yml", {"entries": []})
    _write_yaml(brain / "next_actions.yml", {"next_action": "prepare_task"})
    _write_yaml(brain / "project_fact_snapshot.yml", {"project": project, "event_count": 0})

    result = execute_operator_action(tmp_path, {
        "action": "pause",
        "target_type": "project",
        "target_id": project,
        "project": project,
        "actor": "operator",
        "reason": "budget review",
        "source_surface": "web_ui",
    })

    assert result["success"] is True
    assert result["audit_recorded"] is True
    timeline = build_timeline(project_root)
    assert any(event["event_type"] == "operator_action_recorded" for event in timeline)
    state = build_operator_state(tmp_path, project)
    assert any(event["event_type"] == "operator_action_recorded" for event in state["timeline"])


def test_cost_facade_is_operator_cost_source(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Demo"
    run = project_root / "runs" / "task_001"
    _write_yaml(run / "cost_ledger.yml", {
        "calls": [
            {
                "stage": "phase_1",
                "agent": "coder",
                "model_alias": "model-a",
                "input_tokens": 10,
                "output_tokens": 5,
                "estimated_cost_usd": 0.01,
            }
        ],
    })

    state = build_cost_state(project_root, accepted_phase_ids=["phase_1"])

    assert state["source"] == "agent_runtime.costing.facade"
    assert state["total_estimated_cost_usd"] == 0.01
    assert state["attribution"]["by_task"]["task_001"]["total_cost"] == 0.01
    assert state["attribution"]["by_phase"]["phase_1"]["total_cost"] == 0.01
