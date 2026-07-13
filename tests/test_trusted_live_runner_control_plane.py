from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agent_runtime.live_unblock_plan import build_live_unblock_plan
from agent_runtime.run_task import app
from agent_runtime.trusted_live_runner_operator_handoff import (
    _candidate_items,
    build_trusted_live_runner_operator_handoff,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


def test_operator_handoff_preserves_trusted_runner_and_approval_boundaries(
    private_crown_project_root: Path,
) -> None:
    report = build_trusted_live_runner_operator_handoff(private_crown_project_root)
    boundary = report["execution_boundary"]
    steps = {item["step"]: item for item in report["operator_steps"]}
    candidates = {item["id"]: item for item in report["candidate_items"]}

    assert report["report_type"] == "agentlab_trusted_live_runner_operator_handoff"
    if boundary["writer_request_route_current"]:
        assert report["status"] == "ready_for_trusted_runner"
    else:
        assert report["status"] == "needs_attention"
        assert "trusted_live_runner_writer_route_stale" in report["issues"]
    assert boundary["codex_frontdesk_executes_private_live_commands"] is False
    assert boundary["codex_frontdesk_executes_role_session_acceptance_commands"] is False
    assert boundary["trusted_agentlab_runner_required"] is True
    assert boundary["agentlab_internal_route_blocked"] is False
    assert boundary["approval_gate_before_private_context"] is True
    assert boundary["full_run_requires_trusted_status_pass"] is True
    assert boundary["selective_run_supported"] is True
    assert boundary["selective_run_requires_selected_item_pass"] is True
    assert boundary["role_session_acceptance_approval_env_required"] == (
        "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1"
    )

    gates = boundary["selected_session_health_gates"]
    assert gates["run_crown_internal_writer_eval"]["required_issue_ids"] == [
        "current_claude_writer_session_health"
    ]
    assert gates["run_crown_internal_media_smoke"]["required_issue_ids"] == [
        "current_grok_session_health"
    ]
    readiness = report["selected_item_readiness"]
    for item_id, gate in gates.items():
        assert readiness["items"][item_id]["can_run_now"] is gate["clean"]
        assert readiness["items"][item_id]["blocking_session_health_issue_ids"] == (
            gate["blocking_issue_ids"]
        )
    assert set(readiness["ready_item_ids"]).isdisjoint(readiness["blocked_item_ids"])

    assert steps["preflight"]["loads_private_project_context"] is False
    assert steps["session_health"]["loads_private_project_context"] is False
    assert "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" not in steps[
        "session_health"
    ]["command"]
    for step_id, item_id in (
        ("writer_role_session_acceptance_smoke", "run_crown_internal_writer_eval"),
        ("media_role_session_acceptance_smoke", "run_crown_internal_media_smoke"),
    ):
        step = steps[step_id]
        assert step["loads_private_project_context"] is True
        assert step["runs_only"] == item_id
        assert "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" in step["command"]
        assert step["command"].endswith(f"--only {item_id}")
        assert step["selective_run_supported"] is True
    for step_id, item_id in (
        ("writer_selected_collect", "run_crown_internal_writer_eval"),
        ("media_selected_collect", "run_crown_internal_media_smoke"),
    ):
        step = steps[step_id]
        assert step["loads_private_project_context"] is False
        assert step["runs_only"] == item_id
        assert f"--item {item_id}" in step["command"]
    assert "trusted-live-runner-status" in steps["refresh_status"]["command"]
    assert "trusted-live-runner-collect" in steps["refresh_acceptance_reports"][
        "command"
    ]

    writer = candidates["run_crown_internal_writer_eval"]
    assert writer["agentlab_execution_owner"] == "Writer"
    assert (writer["assigned_worker"] == "claude_code") is boundary[
        "writer_request_route_current"
    ]
    assert writer["candidate_only"] is True
    assert writer["required_files_exist"] is True
    assert writer["returned_candidate_artifacts_accepted"] is True
    assert writer["acceptance_blocker"] == "none"
    media = candidates["run_crown_internal_media_smoke"]
    assert media["agentlab_execution_owner"] == "ArtifactProducer"
    assert media["assigned_worker"] == "grok"
    assert media["returned_candidate_artifacts_accepted"] is False
    assert media["acceptance_blocker"] == "missing_required_files"
    assert report["secret_values_rendered"] is False
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


def test_live_unblock_plan_projects_writer_pass_and_deferred_media(
    private_crown_project_root: Path,
) -> None:
    report = build_live_unblock_plan(private_crown_project_root)
    items = {item["id"]: item for item in report["items"]}

    assert report["report_type"] == "agentlab_live_unblock_plan"
    assert report["status"] == "ready_for_internal_live_smoke"
    assert report["workflow_boundary"] == "internal_agentlab_role_sessions"
    assert report["session_health_gate"]["clean"] is True
    assert report["session_health_gate"]["issue_ids"] == []
    assert report["role_session_execution_boundary"][
        "approval_gate_before_private_context"
    ] is True
    assert report["acceptance_phase"]["entered_acceptance"] is True
    assert report["acceptance_phase"]["pending_item_ids"] == [
        "run_crown_internal_media_smoke"
    ]

    writer = items["run_crown_internal_writer_eval"]
    assert writer["current_return"]["status"] == "pass"
    assert writer["current_return"]["required_files_exist"] is True
    assert writer["current_return"]["returned_candidate_artifacts_accepted"] is True
    assert writer["current_return"]["selected_item_collect_status"] == "pass"
    assert writer["current_return"]["acceptance_blocker"] == "none"
    media = items["run_crown_internal_media_smoke"]
    assert media["route"] == {
        **media["route"],
        "worker_id": "grok",
        "role_owner": "ArtifactProducer",
        "internal_worker": True,
        "role_worker_binding": True,
    }
    assert media["current_return"]["status"] == "pending"
    assert media["current_return"]["returned_candidate_artifacts_accepted"] is False
    assert media["current_return"]["acceptance_blocker"] == "missing_required_files"
    assert media["current_return"]["selected_item_collect_status"] == (
        "pending_selected_item"
    )
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


def test_candidate_items_use_explicit_missing_return_state() -> None:
    items = _candidate_items(
        {
            "items": [
                {
                    "id": "run_missing_status",
                    "agentlab_execution_owner": "Writer",
                    "assigned_worker": "claude_code",
                    "expected_outputs": {
                        "type": "narrative_live_smoke",
                        "candidate_only": True,
                        "required_files": ["fiction_draft.md"],
                    },
                }
            ]
        },
        {"items": []},
    )

    assert items[0]["trusted_status_item_present"] is False
    assert items[0]["current_status"] == "missing"
    assert items[0]["current_pending_reason"] == "trusted_status_item_missing"
    assert items[0]["required_files_exist"] is False
    assert items[0]["returned_candidate_artifacts_accepted"] is False
    assert items[0]["acceptance_blocker"] == "trusted_status_item_missing"
    assert all(value is not None for value in items[0].values())


@pytest.mark.parametrize(
    ("command", "report_type"),
    (
        (
            "trusted-live-runner-operator-handoff",
            "agentlab_trusted_live_runner_operator_handoff",
        ),
        ("live-unblock-plan", "agentlab_live_unblock_plan"),
    ),
)
def test_trusted_runner_control_plane_cli_writes_yaml(
    tmp_path: Path,
    command: str,
    report_type: str,
) -> None:
    out = tmp_path / f"{command}.yml"

    result = RUNNER.invoke(app, [command, "--out", str(out)])

    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert result.exit_code == (
        0
        if report["status"]
        in {"ready_for_trusted_runner", "ready_for_internal_live_smoke"}
        else 1
    )
    assert report["report_type"] == report_type
