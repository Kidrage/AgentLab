from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner
import yaml

import agent_runtime.protocols.enforcement as enforcement_module
from agent_runtime.protocols import (
    build_frontdesk_context,
    build_frontdesk_session,
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
        "Researcher",
        "Reviewer",
        "NarrativePlanner",
        "Writer",
        "Scribe",
    ]
    assert check_role_binding(ROOT, "agy", "Researcher")[0] is True
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


@patch(
    "agent_runtime.protocols.enforcement._probe_frontdesk_runtime",
    return_value=(True, "OpenClaw runtime probe passed"),
)
def test_openclaw_is_default_frontdesk_and_codex_is_external_worker(_probe):
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


@patch(
    "agent_runtime.protocols.enforcement._probe_frontdesk_runtime",
    return_value=(False, "Invalid regular expression: missing /"),
)
def test_openclaw_doctor_fails_when_runtime_cannot_start(_probe):
    result = run_frontdesk_doctor(ROOT, "openclaw")
    by_id = {check["id"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert by_id["frontdesk_runtime_usable"]["status"] == "fail"
    assert "Invalid regular expression" in by_id["frontdesk_runtime_usable"]["message"]


@patch("agent_runtime.protocols.enforcement.subprocess.run")
def test_openclaw_runtime_probe_reports_specific_startup_reason(run):
    run.return_value.returncode = 1
    run.return_value.stdout = ""
    run.return_value.stderr = (
        "[openclaw] Could not start the CLI.\n"
        "[openclaw] Reason: Invalid regular expression: missing /\n"
    )

    ok, detail = enforcement_module._probe_frontdesk_runtime(
        ROOT,
        {"safe_probe": ["openclaw", "agents", "list", "--json"]},
    )

    assert ok is False
    assert "Reason: Invalid regular expression: missing /" in detail
    run.assert_called_once_with(
        ["openclaw", "agents", "list", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_openclaw_session_has_attention_search_and_report_guardrails() -> None:
    context = build_frontdesk_context(ROOT, "openclaw", project="AgentLab")
    session = build_frontdesk_session(ROOT, "openclaw", project="AgentLab")

    assert context["backend"] == {
        "provider": "deepseek",
        "model_key": "deepseek_v4_flash",
        "model_id": "deepseek-v4-flash",
    }
    assert context["turn_contract"]["phases"] == [
        "INTAKE", "CLARIFY", "ROUTE", "MONITOR", "REPORT"
    ]
    assert "ROLE LOCK" in session
    assert "preserve the user's request verbatim" in session
    assert "frontdesk search" in session
    assert "frontdesk report" in session
    assert "No evidence means UNKNOWN" in session
    assert session.count("OPENCLAW FRONTDESK ONLY") >= 2


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


def test_verified_claude_worker_is_narrowly_bound_away_from_narrative_planner():
    claude_allowed, claude_reason = check_role_binding(
        ROOT, "claude_code", "NarrativePlanner"
    )
    qwen_allowed, qwen_reason = check_role_binding(ROOT, "qwen", "NarrativePlanner")
    codex_allowed, codex_reason = check_role_binding(
        ROOT, "codex", "NarrativePlanner"
    )

    assert claude_allowed is False
    assert "forbidden" in claude_reason
    assert qwen_allowed is False, qwen_reason
    assert codex_allowed is False, codex_reason


def test_visual_reviewer_route_uses_reviewer_role_binding():
    allowed, reason = check_role_binding(ROOT, "agy", "visual_reviewer")

    assert allowed is True
    assert reason == "role binding allowed"


def test_grok_historical_worker_is_never_selectable():
    artifact_allowed, artifact_reason = check_role_binding(ROOT, "grok", "ArtifactProducer")
    research_allowed, research_reason = check_role_binding(ROOT, "grok", "Researcher")
    coder_allowed, coder_reason = check_role_binding(ROOT, "grok", "Coder")
    writer_allowed, writer_reason = check_role_binding(ROOT, "grok", "Writer")

    assert artifact_allowed is False
    assert "not selectable" in artifact_reason
    assert research_allowed is False
    assert "not selectable" in research_reason
    assert coder_allowed is False
    assert "not selectable" in coder_reason
    assert writer_allowed is False
    assert "not selectable" in writer_reason


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


def test_hermes_reviewer_requires_exact_senior_editor_contract() -> None:
    denied_without_contract = check_role_binding(ROOT, "hermes", "Reviewer")
    denied_wrong_contract = check_role_binding(
        ROOT,
        "hermes",
        "Reviewer",
        "hermes_deepseek",
    )
    allowed = check_role_binding(
        ROOT,
        "hermes",
        "Reviewer",
        "hermes_deepseek_narrative_audit",
    )

    assert denied_without_contract[0] is False
    assert denied_wrong_contract[0] is False
    assert allowed == (True, "contract-bound role binding allowed")
    packet = build_role_session(
        ROOT,
        "Reviewer",
        "hermes",
        invocation_contract="hermes_deepseek_narrative_audit",
    )
    assert packet["binding"]["allowed"] is True
    assert packet["binding"]["invocation_contract"] == (
        "hermes_deepseek_narrative_audit"
    )


def test_role_binding_rejects_contract_owned_by_another_worker() -> None:
    assert check_role_binding(
        ROOT, "claude_code", "Writer", "hermes_deepseek"
    )[0] is False
    assert check_role_binding(
        ROOT, "codex", "Coder", "hermes_deepseek"
    )[0] is False
    assert check_role_binding(
        ROOT, "agy", "Writer", "claude_writer"
    )[0] is False


def test_contract_bound_role_rejects_historical_contract(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "agent_role_bindings.yml").write_text(
        yaml.safe_dump(
            {
                "roles": {
                    "Reviewer": {
                        "allowed_workers": [],
                        "contract_bound_workers": {
                            "hermes": ["hermes_deepseek_narrative_audit"]
                        },
                    }
                },
                "workers": {
                    "hermes": {
                        "worker_capable": True,
                        "worker_capabilities": ["role_worker"],
                        "allowed_roles": [],
                        "forbidden_roles": ["Reviewer"],
                        "contract_bound_roles": {
                            "Reviewer": ["hermes_deepseek_narrative_audit"]
                        },
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "worker_invocation_contracts.yml").write_text(
        yaml.safe_dump(
            {
                "contracts": {
                    "hermes_deepseek_narrative_audit": {
                        "worker_id": "hermes",
                        "availability": "historical_only",
                        "selectable": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    allowed, _reason = check_role_binding(
        tmp_path,
        "hermes",
        "Reviewer",
        "hermes_deepseek_narrative_audit",
    )
    assert allowed is False


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
