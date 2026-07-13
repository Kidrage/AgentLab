from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.external_acceptance_readiness import (
    _session_health_check,
    build_external_acceptance_readiness,
    build_internal_live_readiness,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_claude_writer_probe_output_is_normalized_to_session_health() -> None:
    check = _session_health_check(
        {
            "worker_id": "claude_writer",
            "installed": True,
            "exit_code": 0,
            "timeout": False,
            "error_class": "none",
        },
        check_id="current_claude_writer_session_health",
        healthy_message="healthy",
        blocked_message="blocked",
        next_action="rerun",
    )

    assert check["status"] == "pass"
    assert check["session_smoke_status"] == "pass"
    assert check["command_available"] is True
    assert check["worker_id"] == "claude_writer"
    assert "reason" not in check
    assert "next_action" not in check


def test_external_acceptance_readiness_names_internal_live_smoke_actions(
    private_crown_project_root: Path,
) -> None:
    report = build_external_acceptance_readiness(private_crown_project_root)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["report_type"] == "agentlab_internal_live_readiness"
    assert report["canonical_report_type"] == "agentlab_internal_live_readiness"
    assert report["legacy_report_type_aliases"] == ["agentlab_external_acceptance_readiness"]
    assert report["legacy_command_aliases"] == ["external-acceptance-readiness"]
    assert report["readiness_type"] == "internal_agentlab_live_smoke"
    assert report["status"] in {"ready_for_internal_live_smoke", "route_ready_session_blocked"}
    assert report["source_report_health"]["status"] in {"pass", "missing_evidence"}
    assert by_id["objective_has_no_active_external_blockers"]["status"] == "pass"
    assert by_id["crown_writer_internal_route_ready"]["status"] == "pass"
    assert by_id["grok_media_internal_route_ready"]["status"] == "pass"
    assert by_id["secret_values_not_rendered"]["status"] == "pass"
    assert by_id["frontdesk_live_handoff_ready"]["status"] == "pass"
    assert by_id["historical_policy_rejections_do_not_override_internal_routes"]["status"] == "pass"
    session_by_id = {item["id"]: item for item in report["session_health_checks"]}
    assert "current_agy_session_health" not in session_by_id
    assert "claude_writer_session_probe" in report["source_reports"]
    assert "agy_cli_session_smoke" not in report["source_reports"]
    if report["status"] == "ready_for_internal_live_smoke":
        assert session_by_id["current_claude_writer_session_health"]["status"] == "pass"
        assert session_by_id["current_claude_writer_session_health"]["worker_id"] == "claude_writer"
        assert "reason" not in session_by_id["current_claude_writer_session_health"]
        assert "next_action" not in session_by_id["current_claude_writer_session_health"]
        assert session_by_id["current_grok_session_health"]["status"] == "pass"
        assert "reason" not in session_by_id["current_grok_session_health"]
        assert "next_action" not in session_by_id["current_grok_session_health"]
        assert report["session_health_issues"] == []
    else:
        assert report["session_health_issues"]
        assert any(item["status"] == "blocked" for item in report["session_health_issues"])
        for item in report["session_health_issues"]:
            assert item["reason"]
            assert item["next_action"]
    assert session_by_id["current_grok_session_health"]["cli_entrypoint_available"] is True
    assert session_by_id["current_grok_session_health"]["local_cli_entrypoint_available"] is True
    assert session_by_id["current_grok_session_health"]["local_cli_entrypoint_is_internal_worker"] is True
    assert session_by_id["current_grok_session_health"]["local_cli_requires_api_key"] is False
    assert session_by_id["current_grok_session_health"]["tested_invocation_mode"] == "non_interactive_prompt_contract"
    assert session_by_id["current_grok_session_health"]["non_interactive_prompt_contract_status"] in {"pass", "blocked"}
    assert session_by_id["current_grok_session_health"]["interactive_cli_start_is_not_task_contract_proof"] is True
    diagnostics_summary = session_by_id["current_grok_session_health"].get("diagnostics_summary", {})
    if diagnostics_summary:
        assert diagnostics_summary["auth_status"] in {"authenticated", "not_authenticated", "unknown"}
        assert isinstance(diagnostics_summary["auth_session_healthy"], bool)
        assert isinstance(diagnostics_summary["model_catalog_visible"], bool)
        assert isinstance(diagnostics_summary["not_authenticated_marker_present"], bool)
    if session_by_id["current_grok_session_health"]["status"] == "pass":
        assert "block_scope" not in session_by_id["current_grok_session_health"]
    assert "frontdesk_live_handoff" in report["source_reports"]
    assert report["policy_rejections"] == []
    assert report["historical_policy_rejections"]
    assert {item["id"] for item in report["ready_items"]} == {
        "run_crown_internal_writer_eval",
        "run_crown_internal_media_smoke",
    }
    writer_item = next(item for item in report["ready_items"] if item["id"] == "run_crown_internal_writer_eval")
    assert "--writer-worker claude_code" in writer_item["agentlab_command"]
    assert "--writer-worker agy" not in writer_item["agentlab_command"]
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


def test_internal_live_readiness_alias_uses_internal_report_name(
    private_crown_project_root: Path,
) -> None:
    report = build_internal_live_readiness(private_crown_project_root)

    assert report["report_type"] == "agentlab_internal_live_readiness"
    assert report["legacy_report_type_aliases"] == ["agentlab_external_acceptance_readiness"]
    assert report["legacy_command_aliases"] == ["external-acceptance-readiness"]
    assert report["readiness_type"] == "internal_agentlab_live_smoke"
    assert report["status"] in {"ready_for_internal_live_smoke", "route_ready_session_blocked"}


def test_external_acceptance_readiness_cli_writes_yaml(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "external_acceptance_readiness.yml"

    result = runner.invoke(app, ["external-acceptance-readiness", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["status"] in {"ready_for_internal_live_smoke", "route_ready_session_blocked"}
    assert report["report_type"] == "agentlab_internal_live_readiness"
    assert report["canonical_report_type"] == "agentlab_internal_live_readiness"
    assert report["legacy_command_aliases"] == ["external-acceptance-readiness"]


def test_internal_live_readiness_cli_writes_yaml(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "internal_live_readiness.yml"

    result = runner.invoke(app, ["internal-live-readiness", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["status"] in {"ready_for_internal_live_smoke", "route_ready_session_blocked"}
    assert report["report_type"] == "agentlab_internal_live_readiness"
    assert report["legacy_report_type_aliases"] == ["agentlab_external_acceptance_readiness"]
    assert report["legacy_command_aliases"] == ["external-acceptance-readiness"]
