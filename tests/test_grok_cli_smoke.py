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
    assert "<non_private_prompt>" in report["command_shape"]
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "Crown_of_Ash" not in rendered
    assert "sk-" not in rendered


def test_grok_cli_smoke_live_pass_with_fake_runner() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        assert args[0] == "hermes"
        assert "-z" in args
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
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if args == ["hermes", "status"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="Provider: xAI Grok OAuth\nModel: grok-build-0.1\n",
                stderr="",
            )
        if args == ["hermes", "auth", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth (1 credentials):\n  #1 loopback_pkce oauth logged in\n",
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
    assert report["diagnostics"]["commands"]["status"]["status"] == "pass"
    assert report["diagnostics"]["commands"]["auth_list"]["logged_in_marker_present"] is True
    assert report["diagnostics"]["commands"]["auth_list"]["not_authenticated_marker_present"] is False
    assert report["diagnostics"]["auth_status"] == "authenticated_but_settings_fetch_failed"
    assert report["diagnostics"]["auth_session_healthy"] is False
    assert report["diagnostics"]["model_catalog_visible"] is True
    assert report["diagnostics"]["settings_fetch_failed"] is True


def test_grok_cli_smoke_classifies_transport_failure() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if args == ["hermes", "status"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="Environment\n", stderr="")
        if args == ["hermes", "auth", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth (1 credentials):\n  #1 loopback_pkce oauth logged in\n",
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
        if args == ["hermes", "status"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="Provider: xAI Grok OAuth\nModel: grok-build-0.1\n",
                stderr="",
            )
        if args == ["hermes", "auth", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth (1 credentials):\n  #1 loopback_pkce oauth logged in\n",
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
        if args == ["hermes", "status"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="Provider: xAI Grok OAuth\nModel: grok-build-0.1\n",
                stderr="",
            )
        if args == ["hermes", "auth", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="xai-oauth (1 credentials):\n  #1 loopback_pkce oauth not authenticated\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="ERROR Settings fetch failed after 3 attempts",
        )

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    status = report["diagnostics"]["commands"]["status"]
    auth_list = report["diagnostics"]["commands"]["auth_list"]
    assert status["default_model_marker_present"] is True
    assert status["model_catalog_visible"] is True
    assert auth_list["logged_in_marker_present"] is False
    assert auth_list["not_authenticated_marker_present"] is True
    assert report["diagnostics"]["auth_status"] == "not_authenticated"
    assert report["diagnostics"]["auth_session_healthy"] is False
    assert report["diagnostics"]["model_catalog_visible"] is True


def test_grok_cli_smoke_timeout_omits_null_returncode() -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if args in (["hermes", "status"], ["hermes", "auth", "list"]):
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(args, timeout, output="", stderr="ERROR Settings fetch failed after 3 attempts")

    report = build_grok_cli_smoke_report(ROOT, live=True, command_runner=fake_runner)

    assert report["status"] == "blocked"
    assert report["reason"] == "grok_cli_settings_fetch_failed"
    assert "returncode" not in report


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
