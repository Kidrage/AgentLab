from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.grok_cli_smoke import build_grok_cli_smoke_report
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_grok_cli_smoke_dry_run_reports_command_without_private_context() -> None:
    report = build_grok_cli_smoke_report(ROOT, live=False)

    assert report["report_type"] == "agentlab_grok_cli_session_smoke"
    assert report["live"] is False
    assert report["private_project_context_loaded"] is False
    assert report["secret_values_rendered"] is False
    assert report["prompt_scope"] == "non_private_session_reachability_smoke"
    assert report["tested_invocation_mode"] == "non_interactive_prompt_contract"
    assert report["interactive_cli_entrypoint"] == "hermes"
    assert report["local_cli_entrypoint_available"] is report["cli_entrypoint_available"]
    assert report["local_cli_entrypoint_is_internal_worker"] is True
    assert report["local_cli_requires_api_key"] is False
    assert report["non_interactive_prompt_contract_status"] == "not_tested"
    assert report["interactive_cli_start_is_not_task_contract_proof"] is True
    assert report["status"] in {"configured", "blocked"}
    assert report["command"] == "hermes"
    assert report["command_variants"] == [
        {
            "command": "hermes",
            "command_shape": (
                "hermes chat -Q --provider xai-oauth -m grok-4.3 "
                "-q <non_private_prompt>"
            ),
        }
    ]
    assert "<non_private_prompt>" in report["command_shape"]
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "Crown_of_Ash" not in rendered
    assert "sk-" not in rendered


def test_grok_cli_smoke_live_pass_with_fake_runner() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        assert args[0] == "hermes"
        assert args[:4] == ["hermes", "chat", "-Q", "--provider"]
        assert "-q" in args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="AGENTLAB_GROK_CLI_SMOKE_OK\n", stderr="")

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    assert report["status"] == "pass"
    assert report["expected_token_present"] is True
    assert report["settings_fetch_failed"] is False
    assert "reason" not in report
    assert "block_scope" not in report
    assert "reason" not in report["attempts"][0]
    assert "block_scope" not in report["attempts"][0]
    assert report["local_cli_entrypoint_is_internal_worker"] is True
    assert report["local_cli_requires_api_key"] is False
    assert report["non_interactive_prompt_contract_status"] == "pass"


def test_grok_cli_smoke_classifies_settings_fetch_failure() -> None:
    commands: list[list[str]] = []

    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if args == ["hermes", "auth", "status", "xai-oauth"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth: logged in\n",
                stderr="ERROR Settings fetch failed after 3 attempts",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="ERROR Settings fetch failed after 3 attempts",
        )

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    assert report["status"] == "blocked"
    assert report["reason"] == "grok_cli_settings_fetch_failed"
    assert report["settings_fetch_failed"] is True
    assert report["block_scope"] == "local_grok_session_health"
    assert report["cli_entrypoint_available"] is True
    assert report["local_cli_entrypoint_available"] is True
    assert report["local_cli_entrypoint_is_internal_worker"] is True
    assert report["local_cli_requires_api_key"] is False
    assert report["tested_invocation_mode"] == "non_interactive_prompt_contract"
    assert report["non_interactive_prompt_contract_status"] == "blocked"
    assert report["diagnostics"]["scope"] == "non_private_local_cli_diagnostics"
    assert report["diagnostics"]["loads_private_project_context"] is False
    assert set(report["diagnostics"]["commands"]) == {"xai_oauth_status"}
    auth_status = report["diagnostics"]["commands"]["xai_oauth_status"]
    assert auth_status["command_shape"] == "hermes auth status xai-oauth"
    assert auth_status["logged_in_marker_present"] is True
    assert auth_status["not_authenticated_marker_present"] is False
    assert report["diagnostics"]["auth_status"] == "authenticated_but_settings_fetch_failed"
    assert report["diagnostics"]["auth_session_healthy"] is False
    assert report["diagnostics"]["model_catalog_visible"] is False
    assert report["diagnostics"]["settings_fetch_failed"] is True
    assert commands[-1] == ["hermes", "auth", "status", "xai-oauth"]
    assert all(command[:2] not in (["hermes", "status"], ["hermes", "auth", "list"]) for command in commands)
    assert all(command[0] == "hermes" for command in commands)
    assert len(report["attempts"]) == 1


def test_grok_cli_smoke_classifies_transport_failure() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if args == ["hermes", "auth", "status", "xai-oauth"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth: logged in\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr=(
                "ERROR Settings fetch failed after 3 attempts\n"
                "request error: error sending request for url (https://cli-chat-proxy.grok.com/v1/responses)"
            ),
        )

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    assert report["status"] == "blocked"
    assert report["reason"] == "grok_cli_transport_or_proxy_failed"
    assert report["block_scope"] == "local_grok_network_or_proxy"
    assert report["settings_fetch_failed"] is True
    assert report["transport_failure_marker_present"] is True
    assert report["auth_failure_marker_present"] is False


def test_grok_cli_smoke_blocks_successful_exit_with_connection_error_text() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if args == ["hermes", "auth", "status", "xai-oauth"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth: logged in\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="API call failed after 3 retries: Connection error.\n",
            stderr="",
        )

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    assert report["status"] == "blocked"
    assert report["reason"] == "grok_cli_transport_or_proxy_failed"
    assert report["block_scope"] == "local_grok_network_or_proxy"
    assert report["transport_failure_marker_present"] is True
    assert report["settings_fetch_failed"] is False
    assert report["expected_token_present"] is False


def test_grok_cli_smoke_distinguishes_model_catalog_from_authentication() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if args == ["hermes", "auth", "status", "xai-oauth"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth: not authenticated\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="ERROR Settings fetch failed after 3 attempts",
        )

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    auth_status = report["diagnostics"]["commands"]["xai_oauth_status"]
    assert auth_status["logged_in_marker_present"] is False
    assert auth_status["not_authenticated_marker_present"] is True
    assert report["diagnostics"]["auth_status"] == "not_authenticated"
    assert report["diagnostics"]["auth_session_healthy"] is False
    assert report["diagnostics"]["model_catalog_visible"] is False


def test_grok_cli_smoke_timeout_omits_null_returncode() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if args == ["hermes", "auth", "status", "xai-oauth"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(args, timeout, output="", stderr="ERROR Settings fetch failed after 3 attempts")

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    assert report["status"] == "blocked"
    assert report["reason"] == "grok_cli_settings_fetch_failed"
    assert "returncode" not in report


def test_grok_cli_smoke_rejects_contract_with_wrong_executable(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "media_generation_backends.yml").write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "hermes_grok_oauth": {
                        "adapter_kind": "local_grok_cli",
                        "worker_id": "grok",
                        "role_owner": "ArtifactProducer",
                        "internal_worker": True,
                        "command": "hermes",
                        "command_contract": {
                            "session_smoke": (
                                "grok -p <prompt> --output-format plain --max-turns 3"
                            )
                        },
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="AGENTLAB_GROK_CLI_SMOKE_OK\n",
            stderr="",
        )

    report = build_grok_cli_smoke_report(
        tmp_path,
        live=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "grok_cli_contract_executable_mismatch"
    assert report["command"] == "hermes"
    assert report["contract_command"] == "grok"
    assert calls == []


def test_grok_cli_smoke_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "grok_cli_smoke.yml"

    result = runner.invoke(app, ["grok-cli-smoke", "--out", str(out)])

    assert out.exists()
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_grok_cli_session_smoke"
    if report["status"] == "blocked":
        assert result.exit_code == 1
    else:
        assert result.exit_code == 0
