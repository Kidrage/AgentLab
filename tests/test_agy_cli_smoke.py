from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.agy_cli_smoke import build_agy_cli_smoke_report
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_agy_cli_smoke_dry_run_reports_command_without_private_context(tmp_path: Path) -> None:
    report = build_agy_cli_smoke_report(ROOT, live=False, smoke_dir=tmp_path / "smoke")

    assert report["report_type"] == "agentlab_agy_cli_session_smoke"
    assert report["live"] is False
    assert report["private_project_context_loaded"] is False
    assert report["secret_values_rendered"] is False
    assert report["prompt_scope"] == "non_private_session_reachability_smoke"
    assert report["status"] in {"configured", "blocked"}
    assert report["invocation_contract"] == "agy_coder"
    assert "<non_private_prompt>" in report["command_shape"]
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "Crown_of_Ash" not in rendered
    assert "sk-" not in rendered


def test_agy_cli_smoke_live_pass_with_fake_runner(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int, log_path: Path) -> subprocess.CompletedProcess[str]:
        assert args[0] == "agy"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="AGENTLAB_AGY_CLI_SMOKE_OK\n", stderr="")

    report = build_agy_cli_smoke_report(
        ROOT,
        live=True,
        command_runner=fake_runner,
        smoke_dir=tmp_path / "smoke",
    )

    assert report["status"] == "pass"
    assert report["expected_token_present"] is True
    assert "reason" not in report


def test_agy_cli_smoke_classifies_localhost_bind_denied(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int, log_path: Path) -> subprocess.CompletedProcess[str]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "CLI failed to start - listen tcp 127.0.0.1:0: bind: operation not permitted",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    report = build_agy_cli_smoke_report(
        ROOT,
        live=True,
        command_runner=fake_runner,
        smoke_dir=tmp_path / "smoke",
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "agy_localhost_bind_denied"
    assert "127.0.0.1:0" in report["log_excerpt"]


def test_agy_cli_smoke_timeout_omits_null_returncode(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int, log_path: Path) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, timeout, output="partial", stderr="timeout")

    report = build_agy_cli_smoke_report(
        ROOT,
        live=True,
        command_runner=fake_runner,
        smoke_dir=tmp_path / "smoke",
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "agy_cli_timeout"
    assert "returncode" not in report


def test_agy_cli_smoke_timeout_after_expected_token_counts_as_session_pass(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int, log_path: Path) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, timeout, output="AGENTLAB_AGY_CLI_SMOKE_OK\n", stderr="")

    report = build_agy_cli_smoke_report(
        ROOT,
        live=True,
        command_runner=fake_runner,
        smoke_dir=tmp_path / "smoke",
    )

    assert report["status"] == "pass"
    assert report["reason"] == "agy_cli_expected_token_observed_before_process_timeout"
    assert report["expected_token_present"] is True
    assert report["process_exit_status"] == "timeout_after_expected_token"
    assert "returncode" not in report


def test_agy_cli_smoke_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "agy_cli_smoke.yml"

    result = runner.invoke(app, ["agy-cli-smoke", "--out", str(out)])

    assert out.exists()
    assert (tmp_path / "agy_cli_smoke" / "task_packet.yml").exists()
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_agy_cli_session_smoke"
    if report["status"] == "blocked":
        assert result.exit_code == 1
    else:
        assert result.exit_code == 0
