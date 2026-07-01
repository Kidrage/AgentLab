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
    assert "build_timeline(project_root, read_errors)" in source


def test_webui_mutations_use_operator_action_runtime_not_cost_ledger_or_executor() -> None:
    decision_source = inspect.getsource(web_server.handle_post_decision)
    agent_source = inspect.getsource(web_server.handle_run_agent)
    nl_source = inspect.getsource(web_server.handle_natural_language_task)

    assert "execute_operator_action" in decision_source
    assert "cost_ledger.yml" not in decision_source
    assert "subprocess.run" not in decision_source

    assert "execute_operator_action" in agent_source
    assert "cost_ledger.yml" not in agent_source
    assert "subprocess.run" not in agent_source
    assert "external_executor_enablement" in agent_source

    assert "execute_operator_action" in nl_source
    assert '"run-agent"' not in nl_source
    assert '"Supervisor"' not in nl_source


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
    assert result["runtime_status"] == "project_pause_recorded"
    assert (brain / "operator_control_state.yml").exists()
    timeline = build_timeline(project_root)
    assert any(event["event_type"] == "operator_action_recorded" for event in timeline)
    state = build_operator_state(tmp_path, project)
    assert any(event["event_type"] == "operator_action_recorded" for event in state["timeline"])
    assert state["read_errors"] == []


def test_operator_state_collects_yaml_read_errors_without_failing(tmp_path: Path) -> None:
    project = "Demo"
    project_root = tmp_path / "projects" / project
    brain = project_root / "project_brain"
    brain.mkdir(parents=True)
    (project_root / "PROJECT_HANDOFF.md").write_text("# Demo\n", encoding="utf-8")
    _write_yaml(project_root / "project_artifact_index.yml", {"artifacts": []})
    (brain / "acceptance_history.yml").write_text("entries: [\n", encoding="utf-8")
    _write_yaml(brain / "next_actions.yml", {"next_action": "repair_yaml"})
    _write_yaml(brain / "project_fact_snapshot.yml", {"project": project, "event_count": 0})

    state = build_operator_state(tmp_path, project)

    assert state["project"]["id"] == project
    assert state["read_errors"]
    assert state["read_errors"][0]["path"] == f"projects/{project}/project_brain/acceptance_history.yml"


def test_timeline_sources_are_project_root_relative_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Demo"
    run = project_root / "runs" / "task_0001"
    _write_yaml(run / "task_packet.yml", {"created_at": "2026-01-01T00:00:00+00:00", "phase_id": "phase_1"})

    timeline = build_timeline(project_root)

    assert timeline[0]["data"]["source"] == "runs/task_0001/task_packet.yml"


def test_webui_legacy_decision_endpoint_resolves_single_pending_card(tmp_path: Path, monkeypatch) -> None:
    project = "Demo"
    task_id = "task_0001"
    run_dir = tmp_path / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(web_server, "AGENTLAB_ROOT", tmp_path)
    from feedback_manager import create_decision_card

    card, _ = create_decision_card(
        run_dir,
        task_id=task_id,
        card_type="approval",
        title="Approve resume",
        reason="Need user approval",
        options=[{"id": "approve_resume", "label": "Approve"}],
        recommended_action="approve_resume",
    )

    result = web_server.handle_post_decision({
        "project": project,
        "taskId": task_id,
        "action": "yes",
        "actor": "operator",
        "reason": "approved",
    })

    assert result["success"] is True
    resolved = yaml.safe_load((run_dir / "decision_cards" / f"{card['id']}.yml").read_text(encoding="utf-8"))
    assert resolved["status"] == "approved"
    assert (tmp_path / "projects" / project / "project_brain" / "operator_action_ledger.yml").exists()


def test_feedback_manager_is_package_importable_for_operator_runtime() -> None:
    import agent_runtime.feedback_manager as feedback_manager

    assert callable(feedback_manager.resolve_decision_card)


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
