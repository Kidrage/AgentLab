from pathlib import Path

from typer.testing import CliRunner

from agent_runtime.protocols import (
    build_frontdesk_context,
    build_role_session,
    build_workspace_entry,
    check_role_binding,
    run_frontdesk_doctor,
    run_protocol_doctor,
    run_role_doctor,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_workspace_entry_binds_agy_as_frontdesk_not_worker():
    packet = build_workspace_entry(ROOT, "agy", project="AgentLab")

    assert packet["packet_type"] == "agentlab_workspace_entry"
    assert packet["allowed_profiles"]["frontdesk_capable"] is True
    assert packet["allowed_profiles"]["worker_capable"] is True
    assert packet["allowed_profiles"]["allowed_roles"] == ["ArtifactProducer", "Coder"]
    assert "rediscover_agentlab_by_full_repo_scan" in packet["forbidden_actions"]


def test_frontdesk_context_is_grounded_and_forbids_execution():
    packet = build_frontdesk_context(ROOT, "agy", project="AgentLab")

    assert packet["packet_type"] == "agentlab_frontdesk_context"
    assert packet["role"] == "AgentLab Frontdesk / Chat Assistant Layer"
    assert "implement_task_itself" in packet["forbidden_actions"]
    assert packet["workspace_entry"]["agent_id"] == "agy"


def test_frontdesk_doctor_accepts_agy_frontdesk_contract():
    result = run_frontdesk_doctor(ROOT, "agy")

    assert result["status"] == "pass"
    assert any(c["id"] == "frontdesk_not_task_packet_worker" for c in result["checks"])


def test_role_binding_allows_agy_as_coder_and_rejects_codex():
    agy_allowed, agy_reason = check_role_binding(ROOT, "agy", "Coder")
    codex_allowed, codex_reason = check_role_binding(ROOT, "codex", "Coder")
    artifact_allowed, artifact_reason = check_role_binding(ROOT, "agy", "ArtifactProducer")

    assert agy_allowed is True
    assert agy_reason == "role binding allowed"
    assert codex_allowed is False
    assert "forbidden" in codex_reason
    assert artifact_allowed is True
    assert artifact_reason == "role binding allowed"


def test_role_session_reports_binding_verdicts():
    accepted = build_role_session(ROOT, "Coder", "agy", project="AgentLab", task_id="task_missing")
    rejected = build_role_session(ROOT, "Coder", "codex", project="AgentLab", task_id="task_missing")

    assert accepted["binding"]["allowed"] is True
    assert rejected["binding"]["allowed"] is False
    assert accepted["packet_type"] == "agentlab_role_session"
    assert "validation_results" in accepted["exit_report_must_include"]


def test_role_doctor_fails_invalid_binding_and_passes_valid_binding():
    bad = run_role_doctor(ROOT, "Supervisor", "agy")
    good = run_role_doctor(ROOT, "Coder", "agy")

    assert bad["status"] == "fail"
    assert good["status"] == "pass"


def test_protocol_doctor_passes_repository_protocol_wiring():
    result = run_protocol_doctor(ROOT)

    assert result["status"] == "pass"
    assert result["summary"]["failed"] == 0


def test_cli_role_session_exits_nonzero_for_invalid_frontdesk_worker():
    result = runner.invoke(app, ["role-session", "--role", "Supervisor", "--worker", "agy"])

    assert result.exit_code == 1
    assert "forbidden" in result.output


def test_cli_protocol_doctor_passes():
    result = runner.invoke(app, ["protocol-doctor"])

    assert result.exit_code == 0
    assert "status: pass" in result.output
