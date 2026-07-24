from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner
import yaml

from agent_runtime.protocols import (
    build_frontdesk_context,
    build_role_session,
    build_workspace_entry,
    check_role_binding,
    evaluate_frontdesk_write_gate,
    run_frontdesk_doctor,
    run_protocol_doctor,
    run_role_doctor,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_live_project_and_knowledge_scope_is_agentlab_plus_crown_only():
    knowledge = yaml.safe_load(
        (ROOT / "config" / "knowledge_system.yml").read_text(encoding="utf-8")
    )
    content = yaml.safe_load(
        (ROOT / "config" / "content_project_governance.yml").read_text(
            encoding="utf-8"
        )
    )

    assert knowledge["indexing"]["project_allowlist"] == [
        "AgentLab",
        "Crown_of_Ash",
    ]
    assert content["active_projects"] == ["Crown_of_Ash"]


def test_workspace_entry_binds_agy_as_frontdesk_and_bounded_worker():
    packet = build_workspace_entry(ROOT, "agy", project="AgentLab")

    assert packet["packet_type"] == "agentlab_workspace_entry"
    assert packet["allowed_profiles"]["frontdesk_capable"] is True
    assert packet["allowed_profiles"]["worker_capable"] is True
    assert set(packet["allowed_profiles"]["worker_capabilities"]) == {
        "frontdesk_gateway",
        "role_worker",
        "workflow_shell",
    }
    assert packet["allowed_profiles"]["allowed_roles"] == [
        "Observer",
        "Reviewer",
        "NarrativePlanner",
        "Writer",
        "Scribe",
    ]
    assert "rediscover_agentlab_by_full_repo_scan" in packet["forbidden_actions"]
    assert packet["known_projects"] == ["Crown_of_Ash"]
    assert packet["content_project_governance"]["active_projects"] == ["Crown_of_Ash"]


def test_frontdesk_context_is_grounded_and_forbids_execution():
    packet = build_frontdesk_context(ROOT, "agy", project="AgentLab")

    assert packet["packet_type"] == "agentlab_frontdesk_context"
    assert packet["role"] == "AgentLab Frontdesk / Chat Assistant Layer"
    assert "implement_task_itself" in packet["forbidden_actions"]
    assert packet["write_gate"]["default"] == "proposal_only"
    assert "config/agent_model_profiles.yml" in packet["write_gate"]["protected_paths"]
    assert packet["workspace_entry"]["agent_id"] == "agy"
    assert "candidate_roots" in packet["forbidden_project_sources"]
    for sources in packet["active_project_state_sources"].values():
        assert all(
            source.endswith(("PROJECT_HANDOFF.md", "project_artifact_index.yml", "project_fact_snapshot.yml"))
            for source in sources
        )


def test_frontdesk_doctor_accepts_agy_frontdesk_contract():
    result = run_frontdesk_doctor(ROOT, "agy")

    assert result["status"] == "pass"
    assert any(c["id"] == "frontdesk_not_task_packet_worker" for c in result["checks"])


def test_openclaw_is_default_frontdesk_and_codex_is_external_worker():
    context = build_frontdesk_context(ROOT, "openclaw", project="AgentLab")
    openclaw_doctor = run_frontdesk_doctor(ROOT, "openclaw")
    hermes_doctor = run_frontdesk_doctor(ROOT, "hermes")
    codex_doctor = run_frontdesk_doctor(ROOT, "codex")

    assert context["frontdesk_capable"] is True
    assert context["is_default_frontdesk"] is True
    assert context["default_frontdesk"] == {
        "agent_id": "openclaw",
        "invocation_contract": "openclaw",
    }
    assert context["execution_paths"]["direct_closed_loop"]["frontdesk_required"] is False
    assert openclaw_doctor["status"] == "pass"
    assert hermes_doctor["status"] == "pass"
    assert codex_doctor["status"] == "fail"


def test_role_binding_rejects_agy_as_coder_and_allows_codex():
    agy_allowed, agy_reason = check_role_binding(ROOT, "agy", "Coder")
    codex_allowed, codex_reason = check_role_binding(ROOT, "codex", "Coder")
    artifact_allowed, artifact_reason = check_role_binding(ROOT, "agy", "ArtifactProducer")

    assert agy_allowed is False
    assert "lacks role_worker" in agy_reason or "forbidden" in agy_reason
    assert codex_allowed is True
    assert codex_reason == "role binding allowed"
    assert artifact_allowed is False
    assert "forbidden" in artifact_reason


def test_narrative_planner_allows_only_claude_code():
    claude_allowed, claude_reason = check_role_binding(
        ROOT, "claude_code", "NarrativePlanner"
    )
    qwen_allowed, qwen_reason = check_role_binding(ROOT, "qwen", "NarrativePlanner")
    codex_allowed, codex_reason = check_role_binding(
        ROOT, "codex", "NarrativePlanner"
    )

    assert claude_allowed is True, claude_reason
    assert qwen_allowed is False, qwen_reason
    assert codex_allowed is False, codex_reason


def test_visual_reviewer_route_uses_reviewer_role_binding():
    allowed, reason = check_role_binding(ROOT, "agy", "visual_reviewer")

    assert allowed is True
    assert reason == "role binding allowed"


def test_grok_is_alter_role_worker_but_not_writer():
    artifact_allowed, artifact_reason = check_role_binding(ROOT, "grok", "ArtifactProducer")
    research_allowed, research_reason = check_role_binding(ROOT, "grok", "Researcher")
    coder_allowed, coder_reason = check_role_binding(ROOT, "grok", "Coder")
    writer_allowed, writer_reason = check_role_binding(ROOT, "grok", "Writer")

    assert artifact_allowed is True
    assert artifact_reason == "role binding allowed"
    assert research_allowed is True
    assert research_reason == "role binding allowed"
    assert coder_allowed is True
    assert coder_reason == "role binding allowed"
    assert writer_allowed is False
    assert "forbidden" in writer_reason


def test_role_session_reports_binding_verdicts():
    accepted = build_role_session(ROOT, "Coder", "agy", project="AgentLab", task_id="task_missing")
    rejected = build_role_session(ROOT, "Supervisor", "agy", project="AgentLab", task_id="task_missing")

    assert accepted["binding"]["allowed"] is False
    assert rejected["binding"]["allowed"] is False
    assert accepted["packet_type"] == "agentlab_role_session"
    assert accepted["role_session_id"] == "task_missing:Coder:agy"
    assert "validation_results" in accepted["exit_report_must_include"]


def test_agy_frontdesk_write_gate_allows_only_bounded_proposals():
    blocked = evaluate_frontdesk_write_gate(ROOT, "agy", "config/agent_model_profiles.yml")
    proposal = evaluate_frontdesk_write_gate(ROOT, "agy", "projects/NovelGen/runs/task_1/change_request.yml")
    candidate = evaluate_frontdesk_write_gate(ROOT, "agy", "projects/NovelGen/runs/task_1/artifacts/chapter.md")

    assert blocked["status"] == "blocked"
    assert blocked["requires"] == "core_config_editor"
    assert proposal["status"] == "proposal_allowed"
    assert candidate["status"] == "blocked"
    assert candidate["requires"] == "candidate_artifact_worker"


def test_role_doctor_fails_invalid_binding_and_passes_valid_binding():
    bad = run_role_doctor(ROOT, "Supervisor", "agy")
    good = run_role_doctor(ROOT, "Coder", "codex")

    assert bad["status"] == "fail"
    assert good["status"] == "pass"


def test_protocol_doctor_passes_repository_protocol_wiring():
    result = run_protocol_doctor(ROOT)

    assert result["status"] == "pass"
    assert result["summary"]["failed"] == 0

    with patch("agent_runtime.protocols.run_protocol_doctor", return_value=result):
        cli_result = runner.invoke(app, ["protocol-doctor"])

    assert cli_result.exit_code == 0
    assert "status: pass" in cli_result.output


def test_cli_role_session_exits_nonzero_for_invalid_frontdesk_worker():
    result = runner.invoke(app, ["role-session", "--role", "Supervisor", "--worker", "agy"])

    assert result.exit_code == 1
    assert "forbidden" in result.output
