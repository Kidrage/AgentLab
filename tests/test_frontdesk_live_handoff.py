from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.frontdesk_live_handoff import build_frontdesk_live_handoff
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_frontdesk_live_handoff_keeps_operator_out_of_execution_roles() -> None:
    report = build_frontdesk_live_handoff(ROOT)
    by_id = {item["id"]: item for item in report["items"]}
    checks = {item["id"]: item for item in report["checks"]}

    assert report["report_type"] == "agentlab_frontdesk_live_handoff"
    assert report["status"] == "ready_for_agentlab_submission"
    assert report["frontdesk_agent"] == "openclaw"
    assert report["boundary"]["frontdesk_role"] == "optional_submit_and_observe_only"
    assert report["boundary"]["canonical_frontdesk"]["invocation_contract"] == "openclaw"
    assert report["boundary"]["direct_closed_loop_supported"] is True
    assert report["boundary"]["agentlab_owns_execution"] is True
    assert report["boundary"]["current_live_items_are_internal_role_sessions"] is True
    assert checks["frontdesk_is_not_execution_worker"]["status"] == "pass"
    assert checks["canonical_frontdesk_is_openclaw"]["status"] == "pass"
    assert checks["direct_closed_loop_can_skip_frontdesk"]["status"] == "pass"
    assert checks["sandbox_approval_kept_outside_agentlab_chain"]["status"] == "pass"
    assert checks["writer_command_has_role_session_worker"]["status"] == "pass"
    assert checks["media_command_has_artifact_producer_worker"]["status"] == "pass"

    crown = by_id["run_crown_internal_writer_eval"]
    assert crown["agentlab_execution_owner"] == "Writer"
    assert crown["assigned_worker"] == "agy"
    assert crown["role_session_required"] is True
    assert crown["user_approval_required"] is False
    assert "--writer-worker agy" in crown["agentlab_command"]
    assert "--writer-worker claude_code" not in crown["agentlab_command"]
    assert "generate or edit the production content directly" in crown["frontdesk_must_not"]

    media = by_id["run_crown_internal_media_smoke"]
    assert media["agentlab_execution_owner"] == "ArtifactProducer"
    assert media["assigned_worker"] == "grok"
    assert media["role_session_required"] is True
    assert media["user_approval_required"] is False
    assert "--role ArtifactProducer --worker grok" in media["agentlab_command"]

    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


def test_frontdesk_live_handoff_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "frontdesk_live_handoff.yml"

    result = runner.invoke(app, ["frontdesk-live-handoff", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["frontdesk_agent"] == "openclaw"
    assert report["status"] == "ready_for_agentlab_submission"
