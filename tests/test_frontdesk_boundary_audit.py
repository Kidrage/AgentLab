from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.frontdesk_boundary_audit import build_frontdesk_boundary_audit
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_frontdesk_boundary_audit_reports_role_chain_and_raw_live_adapter_warning() -> None:
    report = build_frontdesk_boundary_audit(ROOT)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["report_type"] == "agentlab_frontdesk_boundary_audit"
    assert report["status"] == "pass"
    assert "Researcher" in "\n".join(report["intended_chain"])
    assert "ArtifactProducer" in "\n".join(report["intended_chain"])
    assert "Writer" in "\n".join(report["intended_chain"])
    assert by_id["frontdesk_policy_declares_non_worker_boundary"]["status"] == "pass"
    assert report["frontdesk_agent"] == "openclaw"
    assert by_id["openclaw_is_default_frontdesk"]["status"] == "pass"
    assert by_id["frontdesk_profile_is_separate_from_role_sessions"]["status"] == "pass"
    assert by_id["codex_is_external_worker_not_frontdesk"]["status"] == "pass"
    assert by_id["direct_closed_loop_does_not_require_frontdesk"]["status"] == "pass"
    assert by_id["sandbox_approval_is_external_runtime_boundary"]["status"] == "pass"
    assert by_id["media_live_role_owner_is_artifact_producer"]["status"] == "pass"
    assert "grok" in by_id["media_live_role_owner_is_artifact_producer"]["summary"]
    assert by_id["local_grok_cli_backend_is_registered_internal_backend"]["status"] == "pass"
    assert by_id["cli_workflow_shell_registry_covers_hermes_and_claude"]["status"] == "pass"
    assert "Hermes and Claude Code" in by_id[
        "cli_workflow_shell_registry_covers_hermes_and_claude"
    ]["summary"]
    assert by_id["cli_workflow_shell_governance_covers_full_cli_mode"]["status"] == "pass"
    assert "full_cli_shells=" in by_id[
        "cli_workflow_shell_governance_covers_full_cli_mode"
    ]["summary"]
    assert by_id["workflow_shell_workers_are_bounded_role_workers"]["status"] == "pass"
    assert by_id["hermes_grok_backend_uses_workflow_shell_without_role_leakage"]["status"] == "pass"
    assert by_id["grok_cli_is_registered_as_internal_research_and_artifact_worker"]["status"] == "pass"
    assert by_id["grok_current_contracts_use_hermes_surface"]["status"] == "pass"
    assert (
        by_id["artifact_producer_profiles_bind_current_codex_default"]["status"]
        == "pass"
    )
    assert by_id["raw_media_live_cli_requires_role_session"]["status"] == "pass"
    assert by_id["narrative_live_eval_requires_writer_role_session"]["status"] == "pass"


def test_frontdesk_boundary_audit_cli_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "frontdesk_boundary_audit.yml"

    result = runner.invoke(app, ["frontdesk-boundary-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["frontdesk_agent"] == "openclaw"
    assert report["status"] == "pass"
