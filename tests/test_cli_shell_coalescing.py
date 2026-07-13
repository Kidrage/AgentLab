from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime import cli_shell_coalescing_collect as collect_module
from agent_runtime.cli_shell_coalescing import build_cli_shell_coalescing_plan
from agent_runtime.cli_shell_coalescing_collect import build_cli_shell_coalescing_collect
from agent_runtime.cli_shell_coalescing_request import build_cli_shell_coalescing_runner_request
from agent_runtime.cli_shell_coalescing_status import build_cli_shell_coalescing_status
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_cli_shell_coalescing_plan_finds_native_backend_groups() -> None:
    report = build_cli_shell_coalescing_plan(ROOT, mode="full_cli", tier="performance")
    groups = {group["backend"]: group for group in report["groups"]}

    assert report["status"] == "pass"
    assert report["policy"]["provider_calls_executed"] is False
    assert report["policy"]["per_role_receipts_required"] is True
    assert report["eligible_group_count"] >= 2

    assert groups["claude_code"]["coalescing_eligible"] is True
    assert groups["claude_code"]["coalescing_mode"] == "native_subagents"
    assert set(groups["claude_code"]["roles"]) == {"Coder", "Archivist"}

    assert groups["hermes"]["coalescing_eligible"] is True
    assert groups["hermes"]["coalescing_mode"] == "board_mediated"
    assert "Supervisor" in groups["hermes"]["roles"]
    assert groups["hermes"]["surface"]["board_surface"] == "hermes kanban"

    assert groups["codex"]["coalescing_eligible"] is False
    assert "backend_lacks_registered_subagent_or_board_surface" in groups["codex"]["blocked_reasons"]

    for group in report["groups"]:
        assert group["single_shell_session_contract"]["must_return_one_receipt_per_role"] is True
        assert group["single_shell_session_contract"]["shell_state_counts_as_project_memory"] is False
        assert len(group["role_receipts"]) == group["role_count"]
        for receipt in group["role_receipts"]:
            assert receipt["receipt_path"].startswith("role_receipts/")
            assert receipt["validation_evidence_path"].startswith("role_receipts/")


def test_cli_shell_coalescing_plan_cli_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "cli_shell_coalescing_plan.yml"

    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-plan",
            "--out",
            str(out),
            "--mode",
            "full_cli",
            "--tier",
            "performance",
        ],
    )

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_cli_shell_coalescing_plan"
    assert report["status"] == "pass"
    assert report["acceptance_gate"]["runtime_execution_not_performed"] is True
    assert len(report["materialized_session_packets"]) == report["eligible_group_count"]
    assert report["missing_session_packets"] == []

    report_root = Path(report["root"])
    for packet_rel in report["materialized_session_packets"]:
        packet_path = Path(packet_rel)
        if not packet_path.is_absolute():
            packet_path = report_root / packet_path
        packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
        assert packet["packet_type"] == "agentlab_coalesced_cli_shell_session"
        assert packet["provider_calls_executed_by_packet_generation"] is False
        assert packet["agentlab_authority"]["shell_state_counts_as_project_memory"] is False
        assert packet["acceptance_contract"]["must_return_one_receipt_per_role"] is True
        assert packet["task_contract"]["task_kind"] == "cli_shell_native_runtime_acceptance"
        assert packet["task_contract"]["acceptance_scope"] == "synthetic_native_surface_smoke"
        assert packet["task_contract"]["private_project_context_loaded"] is False
        assert packet["task_contract"]["synthetic_input_only"] is True
        assert packet["task_contract"]["production_changes_allowed"] is False
        assert packet["execution_contract"]["trusted_runner_required"] is True
        assert packet["execution_contract"]["frontdesk_role_invocations"] == 0
        assert packet["execution_contract"]["provider_invocation_count_claimed"] is False
        assert len(packet["delegated_roles"]) >= 2
        for role in packet["delegated_roles"]:
            assert role["receipt_path"].startswith("role_receipts/")
            assert role["validation_evidence_path"].startswith("role_receipts/")
            assert role["task"]["objective"]
            assert role["task"]["read_scope"] == []
            assert role["task"]["private_project_context_loaded"] is False
            assert role["task"]["synthetic_fixture"]["fixture_id"] == "agentlab-cli-native-surface-smoke-v1"
            assert role["task"]["write_scope"] == ["returned_artifacts/"]
            assert role["task"]["production_changes_allowed"] is False
            assert role["model_route"]["configured_model_key"]
            assert "applied_to_shell_invocation" in role["model_route"]

        if packet["backend"] == "claude_code":
            assert packet["execution_contract"]["native_surface"] == "claude_inline_agents"
            assert packet["execution_contract"]["coordination_semantics"] == "single_top_level_shell_invocation"
            assert packet["execution_contract"]["command_spec"]["entrypoint"] == "claude"
            args = packet["execution_contract"]["command_spec"]["arguments"]
            assert "--agents" in args
            assert "--permission-mode" in args
            assert "plan" in args
            assert "--safe-mode" in args
            assert "--no-session-persistence" in args
            assert args[args.index("--tools") + 1] == "Agent"
            assert "bypassPermissions" not in args
            assert "--dangerously-skip-permissions" not in args
            routes = {role["role"]: role["model_route"] for role in packet["delegated_roles"]}
            assert routes["Coder"]["applied_to_shell_invocation"] is False
            assert routes["Coder"]["shell_model_selection"] == "shell_native_default"
            assert routes["Archivist"]["applied_to_shell_invocation"] is False
        elif packet["backend"] == "hermes":
            assert packet["execution_contract"]["native_surface"] == "hermes_kanban"
            assert packet["execution_contract"]["coordination_semantics"] == "board_orchestrated_multi_worker"
            assert packet["execution_contract"]["command_spec"]["entrypoint"] == "hermes"
            assert packet["execution_contract"]["command_spec"]["command_family"] == "kanban"
            role_command = packet["execution_contract"]["command_spec"]["role_task_command"]
            assert role_command[role_command.index("--workspace") + 1] == "scratch"
            assert packet["execution_contract"]["single_provider_session_claimed"] is False
            routes = {role["role"]: role["model_route"] for role in packet["delegated_roles"]}
            supervisor = routes["Supervisor"]
            assert supervisor["applied_to_shell_invocation"] is True
            assert supervisor["provider"] == "openai-codex"
            assert supervisor["model_id"] == "gpt-5.6-sol"
            assert supervisor["reasoning_effort"] == "xhigh"
            assert supervisor["workflow_shell_profile"] == "agentlabsupervisor"
            assert supervisor["required_profile_config"] == {
                "model.provider": "openai-codex",
                "model.default": "gpt-5.6-sol",
                "model.base_url": "https://chatgpt.com/backend-api/codex",
                "agent.reasoning_effort": "xhigh",
                "fallback_providers": [],
            }
            assert supervisor["forbidden_profile_config_keys"] == ["fallback_model"]
            assert supervisor.get("fallback_worker") is None
            assert supervisor.get("fallback_model_key") is None
            prompt_engineer = routes["PromptEngineer"]
            assert prompt_engineer["applied_to_shell_invocation"] is True
            assert prompt_engineer["provider"] == "deepseek"
            assert prompt_engineer["model_id"] == "deepseek-v4-flash"
            assert prompt_engineer["base_url"] == "https://api.deepseek.com"
            assert prompt_engineer["workflow_shell_profile"] == "agentlabpromptengineer"


def test_cli_shell_coalescing_status_reports_pending_until_receipts_return(tmp_path: Path) -> None:
    plan_path = tmp_path / "cli_shell_coalescing_plan.yml"
    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-plan",
            "--out",
            str(plan_path),
            "--mode",
            "full_cli",
            "--tier",
            "performance",
        ],
    )

    assert result.exit_code == 0
    report = build_cli_shell_coalescing_status(ROOT, plan_path=plan_path)

    assert report["status"] == "pending_returned_artifacts"
    assert report["provider_calls_executed"] is False
    assert report["secret_values_rendered"] is False
    assert report["acceptance_scope"] == "synthetic_native_surface_smoke"
    assert report["private_project_context_loaded"] is False
    assert report["expected_packet_count"] >= 2
    assert report["accepted_packet_count"] == 0
    assert report["missing_returned_files_count"] > 0
    assert any(path.endswith("shell_subagent_delegation_receipt.yml") for path in report["missing_returned_files"])
    assert any(path.endswith("shell_board_sync_receipt.yml") for path in report["missing_returned_files"])

    out = tmp_path / "cli_shell_coalescing_status.yml"
    cli_result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-status",
            "--plan",
            str(plan_path),
            "--out",
            str(out),
        ],
    )
    assert cli_result.exit_code == 0
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert written["status"] == "pending_returned_artifacts"


def test_cli_shell_coalescing_status_passes_when_all_receipts_return(tmp_path: Path) -> None:
    plan_path = tmp_path / "cli_shell_coalescing_plan.yml"
    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-plan",
            "--out",
            str(plan_path),
            "--mode",
            "full_cli",
            "--tier",
            "performance",
        ],
    )
    assert result.exit_code == 0
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    session_receipt_paths: list[Path] = []
    for packet_text in plan["materialized_session_packets"]:
        packet_path = Path(packet_text)
        if not packet_path.is_absolute():
            packet_path = ROOT / packet_path
        packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
        packet_sha256 = hashlib.sha256(
            yaml.safe_dump(packet, sort_keys=True, allow_unicode=True).encode("utf-8")
        ).hexdigest()
        session_receipt_name = (
            "shell_board_sync_receipt.yml"
            if packet["coalescing_mode"] == "board_mediated"
            else "shell_subagent_delegation_receipt.yml"
        )
        session_receipt_path = packet_path.parent / session_receipt_name
        session_receipt_paths.append(session_receipt_path)
        session_receipt_path.write_text(
            yaml.safe_dump(
                {
                    "status": "pass",
                    "backend": packet["backend"],
                    "coalescing_mode": packet["coalescing_mode"],
                    "native_surface_used": packet["execution_contract"]["native_surface"],
                    "delegated_roles": [role["role"] for role in packet["delegated_roles"]],
                    "frontdesk_role_invocations": 0,
                    "acceptance_scope": "synthetic_native_surface_smoke",
                    "private_project_context_loaded": False,
                    "execution_workspace_isolated": True,
                    "project_read_tools_enabled": False,
                    "provider_calls_executed_by_shell_session": True,
                    "source_packet_sha256": packet_sha256,
                    "production_promotion_allowed": False,
                    "production_promotion_attempted": False,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        for role in packet["delegated_roles"]:
            artifact_path = packet_path.parent / "role_receipts" / f"{role['role'].lower()}_artifact.txt"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(f"{role['role']} returned artifact\n", encoding="utf-8")
            receipt_path = packet_path.parent / role["receipt_path"]
            validation_path = packet_path.parent / role["validation_evidence_path"]
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(
                yaml.safe_dump(
                    {
                        "status": "pass",
                        "role": role["role"],
                        "acceptance_scope": "synthetic_native_surface_smoke",
                        "private_project_context_loaded": False,
                        "source_packet_sha256": packet_sha256,
                        "returned_artifacts": [str(artifact_path)],
                        "production_promotion_attempted": False,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                yaml.safe_dump(
                    {
                        "status": "pass",
                        "role": role["role"],
                        "acceptance_scope": "synthetic_native_surface_smoke",
                        "private_project_context_loaded": False,
                        "source_packet_sha256": packet_sha256,
                        "production_promotion_attempted": False,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

    report = build_cli_shell_coalescing_status(ROOT, plan_path=plan_path)

    assert report["status"] == "pass"
    assert report["accepted_packet_count"] == report["expected_packet_count"]
    assert report["accepted_role_count"] == report["delegated_role_count"]
    assert report["missing_returned_files"] == []
    assert report["failures"] == []

    unsafe_receipt = yaml.safe_load(session_receipt_paths[0].read_text(encoding="utf-8"))
    unsafe_receipt["private_project_context_loaded"] = True
    session_receipt_paths[0].write_text(
        yaml.safe_dump(unsafe_receipt, sort_keys=False),
        encoding="utf-8",
    )
    unsafe_report = build_cli_shell_coalescing_status(ROOT, plan_path=plan_path)
    assert unsafe_report["status"] == "fail"
    assert any(
        "private project context" in failure
        for packet_failure in unsafe_report["failures"]
        for failure in packet_failure["failures"]
    )

    unsafe_receipt["private_project_context_loaded"] = False
    unsafe_receipt["source_packet_sha256"] = "0" * 64
    session_receipt_paths[0].write_text(
        yaml.safe_dump(unsafe_receipt, sort_keys=False),
        encoding="utf-8",
    )
    stale_report = build_cli_shell_coalescing_status(ROOT, plan_path=plan_path)
    assert stale_report["status"] == "pending_returned_artifacts"
    assert stale_report["failure_count"] == 0
    assert str(session_receipt_paths[0]) in stale_report["stale_returned_files"]


def test_cli_shell_coalescing_runner_request_packages_receipt_handoff(tmp_path: Path) -> None:
    plan_path = tmp_path / "cli_shell_coalescing_plan.yml"
    status_path = tmp_path / "cli_shell_coalescing_status.yml"
    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-plan",
            "--out",
            str(plan_path),
            "--mode",
            "full_cli",
            "--tier",
            "performance",
        ],
    )
    assert result.exit_code == 0
    status_result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-status",
            "--plan",
            str(plan_path),
            "--out",
            str(status_path),
        ],
    )
    assert status_result.exit_code == 0

    report = build_cli_shell_coalescing_runner_request(ROOT, plan_path=plan_path, status_path=status_path)

    assert report["report_type"] == "agentlab_cli_shell_coalescing_runner_request"
    assert report["status"] == "ready_for_trusted_runner"
    assert report["runner_boundary"]["frontdesk_agent_executes_shell_sessions"] is False
    assert report["runner_boundary"]["trusted_shell_runner_required"] is True
    assert report["runner_boundary"]["provider_calls_executed_by_request_generation"] is False
    assert report["runner_boundary"]["shell_state_counts_as_project_memory"] is False
    assert report["runner_boundary"]["production_promotion_allowed"] is False
    assert report["runner_boundary"]["acceptance_scope"] == "synthetic_native_surface_smoke"
    assert report["runner_boundary"]["private_project_context_loaded"] is False
    assert report["runner_boundary"]["isolated_execution_workspace_required"] is True
    assert report["runner_boundary"]["project_read_tools_allowed"] is False
    assert report["status_summary"]["packet_count"] == 2
    assert report["status_summary"]["missing_returned_files_count"] > 0
    assert report["local_runner_package"]["must_return_one_shell_receipt_per_packet"] is True
    assert report["local_runner_package"]["must_return_one_role_receipt_per_delegated_role"] is True
    assert report["local_runner_package"]["must_return_validation_evidence_per_delegated_role"] is True
    assert report["local_runner_package"]["full_run_requires_coalescing_status_pass"] is True
    assert "cli-shell-coalescing-runner" in report["local_runner_package"]["dry_run_command"]
    assert "AGENTLAB_TRUSTED_CLI_SHELL_RUNNER=1" in report["local_runner_package"]["execute_command"]
    assert "--execute" in report["local_runner_package"]["execute_command"]
    assert "cli-shell-coalescing-collect" in report["local_runner_package"]["post_run_collect_command"]
    assert "cli-shell-coalescing-status" in report["local_runner_package"]["status_command"]
    assert len(report["packets"]) == 2
    assert {packet["backend"] for packet in report["packets"]} == {"claude_code", "hermes"}
    assert any(packet["coalescing_mode"] == "native_subagents" for packet in report["packets"])
    assert any(packet["coalescing_mode"] == "board_mediated" for packet in report["packets"])
    execute_step = next(step for step in report["operator_steps"] if step["step"] == "execute_trusted_shell_sessions")
    assert execute_step["loads_private_project_context"] is False
    assert execute_step["acceptance_scope"] == "synthetic_native_surface_smoke"
    for packet in report["packets"]:
        assert packet["session_receipt_path"].endswith(".yml")
        assert len(packet["source_packet_sha256"]) == 64
        assert packet["task_contract"]["task_kind"] == "cli_shell_native_runtime_acceptance"
        assert packet["execution_contract"]["native_surface"] in {"claude_inline_agents", "hermes_kanban"}
        assert packet["execution_contract"]["frontdesk_role_invocations"] == 0
        assert packet["delegated_roles"]
        for role in packet["delegated_roles"]:
            assert role["receipt_path"].endswith("_role_session_receipt.yml")
            assert role["validation_evidence_path"].endswith("_validation_evidence.yml")
            assert "production promotion" in role["acceptance_rule"]
            assert role["task"]["objective"]
            assert role["model_route"]["configured_model_key"]


def test_cli_shell_coalescing_runner_request_cli_writes_yaml(tmp_path: Path) -> None:
    plan_path = tmp_path / "cli_shell_coalescing_plan.yml"
    status_path = tmp_path / "cli_shell_coalescing_status.yml"
    out = tmp_path / "cli_shell_coalescing_runner_request.yml"
    assert runner.invoke(
        app,
        [
            "cli-shell-coalescing-plan",
            "--out",
            str(plan_path),
            "--mode",
            "full_cli",
            "--tier",
            "performance",
        ],
    ).exit_code == 0
    assert runner.invoke(
        app,
        [
            "cli-shell-coalescing-status",
            "--plan",
            str(plan_path),
            "--out",
            str(status_path),
        ],
    ).exit_code == 0

    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-runner-request",
            "--plan",
            str(plan_path),
            "--status",
            str(status_path),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["status"] == "ready_for_trusted_runner"
    assert report["secret_values_rendered"] is False
    steps = {step["step"]: step for step in report["operator_steps"]}
    assert steps["refresh_status"]["pass_condition"] == "cli_shell_coalescing_status.status is pass"
    assert steps["collect_acceptance"]["pass_condition"] == "cli_shell_coalescing_collect.status is pass"


def test_cli_shell_coalescing_collect_custom_paths_do_not_refresh_canonical_acceptance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan_path = tmp_path / "cli_shell_coalescing_plan.yml"
    status_path = tmp_path / "cli_shell_coalescing_status.yml"
    request_path = tmp_path / "cli_shell_coalescing_runner_request.yml"
    out = tmp_path / "cli_shell_coalescing_collect.yml"
    assert runner.invoke(
        app,
        [
            "cli-shell-coalescing-plan",
            "--out",
            str(plan_path),
            "--mode",
            "full_cli",
            "--tier",
            "performance",
        ],
    ).exit_code == 0

    def fail_if_refreshed(_root: Path) -> dict:
        raise AssertionError("custom collector paths must not refresh canonical acceptance")

    monkeypatch.setattr(collect_module, "_refresh_acceptance_reports", fail_if_refreshed)
    report = build_cli_shell_coalescing_collect(
        ROOT,
        plan_path=plan_path,
        status_path=status_path,
        request_path=request_path,
        out=out,
    )

    assert report["status"] == "pending_returned_artifacts"
    assert report["provider_calls_executed"] is False
    assert report["secret_values_rendered"] is False
    assert report["coalescing_status"]["accepted_packet_count"] == 0
    assert report["coalescing_status"]["accepted_role_count"] == 0
    assert report["runner_request_status"] == "ready_for_trusted_runner"
    assert set(report["refreshed_reports"]) == {
        "cli_shell_coalescing_status",
        "cli_shell_coalescing_runner_request",
    }
    assert report["acceptance_refresh"] == {
        "performed": False,
        "reason": "noncanonical_paths_do_not_refresh_canonical_acceptance",
    }
    assert "acceptance_summary" not in report
    written_request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    assert all(packet["delegated_roles"] for packet in written_request["packets"])
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert written["root"] == "."
    assert written["status"] == report["status"]
    assert written["refreshed_reports"] == report["refreshed_reports"]


def test_cli_shell_coalescing_collect_rejects_invalid_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "invalid_plan.yml"
    status_path = tmp_path / "status.yml"
    request_path = tmp_path / "request.yml"
    out = tmp_path / "collect.yml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "report_type": "agentlab_cli_shell_coalescing_plan",
                "status": "fail",
                "eligible_group_count": 0,
                "materialized_session_packets": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_cli_shell_coalescing_collect(
        ROOT,
        plan_path=plan_path,
        status_path=status_path,
        request_path=request_path,
        out=out,
    )
    assert report["status"] == "invalid_coalescing_state"
    assert report["coalescing_status"]["status"] == "fail"

    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-collect",
            "--plan",
            str(plan_path),
            "--status",
            str(status_path),
            "--request",
            str(request_path),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 1


def test_cli_shell_coalescing_collect_rejects_secret_shaped_paths_before_writing_sources(
    tmp_path: Path,
) -> None:
    secret = "sk-" + "a" * 40
    plan_path = tmp_path / f"{secret}.yml"
    status_path = tmp_path / "status.yml"
    request_path = tmp_path / "request.yml"
    out = tmp_path / "collect.yml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "report_type": "agentlab_cli_shell_coalescing_plan",
                "status": "fail",
                "eligible_group_count": 0,
                "materialized_session_packets": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_cli_shell_coalescing_collect(
        ROOT,
        plan_path=plan_path,
        status_path=status_path,
        request_path=request_path,
        out=out,
    )

    written = out.read_text(encoding="utf-8")
    assert report["status"] == "unsafe_report_rejected"
    assert report["secret_values_detected"] is True
    assert report["secret_values_rendered"] is False
    assert secret not in written
    assert not status_path.exists()
    assert not request_path.exists()


def test_cli_shell_coalescing_collect_cli_is_wired(tmp_path: Path, monkeypatch) -> None:
    import cli_shell_coalescing_collect as direct_collect_module

    out = tmp_path / "cli_shell_coalescing_collect.yml"
    captured: dict[str, Path | None] = {}

    def fake_write(
        root: Path,
        report_out: Path,
        plan_path: Path | None = None,
        status_path: Path | None = None,
        request_path: Path | None = None,
    ) -> dict:
        captured.update(
            {
                "root": root,
                "out": report_out,
                "plan": plan_path,
                "status": status_path,
                "request": request_path,
            }
        )
        report = {
            "status": "pending_returned_artifacts",
            "provider_calls_executed": False,
            "secret_values_rendered": False,
        }
        report_out.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
        return report

    monkeypatch.setattr(direct_collect_module, "write_cli_shell_coalescing_collect", fake_write)
    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-collect",
            "--out",
            str(out),
            "--plan",
            "plan.yml",
            "--status",
            "status.yml",
            "--request",
            "request.yml",
        ],
    )

    assert result.exit_code == 0
    assert captured["root"] == ROOT
    assert captured["out"] == out
    assert captured["plan"] == Path("plan.yml")
    assert captured["status"] == Path("status.yml")
    assert captured["request"] == Path("request.yml")
