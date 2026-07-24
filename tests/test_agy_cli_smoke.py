from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

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
    assert report["prompt_scope"] == "non_private_observer_session_reachability_smoke"
    assert report["status"] in {"configured", "blocked"}
    assert report["invocation_contract"] == "agy_observer"
    assert "--model gemini-3.5-flash-high" in report["command_shape"]
    assert "--sandbox" in report["command_shape"]
    assert len(report["command_variants"]) == 1
    assert "<non_private_prompt>" in report["command_shape"]
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    packet = yaml.safe_load((tmp_path / "smoke" / "task_packet.yml").read_text(encoding="utf-8"))
    assert packet["role"] == "Observer"
    assert "Writer" not in rendered
    assert "Crown_of_Ash" not in rendered
    assert "sk-" not in rendered


def test_agy_cli_smoke_live_pass_with_fake_runner(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int, log_path: Path) -> subprocess.CompletedProcess[str]:
        assert args[0] == "agy"
        assert args[args.index("--model") + 1] == "gemini-3.5-flash-high"
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


def test_agy_cli_smoke_real_subprocess_does_not_inherit_direct_api_keys(
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def fake_subprocess_run(args, **kwargs):
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="AGENTLAB_AGY_CLI_SMOKE_OK\n",
            stderr="",
        )

    direct_api_keys = {
        "GEMINI_API_KEY": "gemini-secret",
        "GOOGLE_API_KEY": "google-secret",
        "GOOGLE_GENAI_API_KEY": "genai-secret",
        "GOOGLE_GENERATIVE_AI_API_KEY": "generative-secret",
        "GOOGLE_AI_API_KEY": "ai-secret",
        "GOOGLE_GEMINI_API_KEY": "alternate-secret",
        "GENAI_API_KEY": "generic-secret",
    }
    with patch.dict(
        "agent_runtime.agy_cli_smoke.os.environ",
        {**direct_api_keys, "AGY_OAUTH_SESSION": "preserved-session"},
        clear=False,
    ), patch(
        "agent_runtime.agy_cli_smoke.shutil.which", return_value="/usr/bin/agy"
    ), patch(
        "agent_runtime.agy_cli_smoke.subprocess.run",
        side_effect=fake_subprocess_run,
    ):
        report = build_agy_cli_smoke_report(
            ROOT,
            live=True,
            smoke_dir=tmp_path / "smoke",
        )

    assert report["status"] == "pass"
    process_env = observed["env"]
    assert process_env["AGY_OAUTH_SESSION"] == "preserved-session"
    assert all(name not in process_env for name in direct_api_keys)


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


def test_agy_cli_smoke_rejects_expected_token_after_unresolved_model(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int, log_path: Path) -> subprocess.CompletedProcess[str]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "Failed to resolve model flag: model is not recognized as a known model",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="AGENTLAB_AGY_CLI_SMOKE_OK\n",
            stderr="",
        )

    report = build_agy_cli_smoke_report(
        ROOT,
        live=True,
        command_runner=fake_runner,
        smoke_dir=tmp_path / "smoke",
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "agy_model_flag_unresolved"
    assert report["expected_token_present"] is True
    assert report["attempts"][0]["model_resolution_failed"] is True


def test_agy_cli_smoke_fails_closed_without_governed_contract_or_model(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    report = build_agy_cli_smoke_report(
        root,
        live=False,
        smoke_dir=tmp_path / "smoke",
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "agy_cli_invalid_command_template"
    assert report["command_variants"] == []


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
