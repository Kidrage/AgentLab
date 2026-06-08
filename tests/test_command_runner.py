from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
import yaml

from command_runner import (
    is_command_allowed,
    normalize_command,
    run_logged_command,
    run_validation_commands_if_present,
    safe_resolve_cwd,
    validate_command_paths,
)
from execution_log import load_execution_log


def _agentlab_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_allowed_command_executes_and_writes_execution_log(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    (workspace / "ok.py").write_text("x = 1\n", encoding="utf-8")

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m py_compile ok.py",
        cwd=".",
        workspace_root=workspace,
    )

    assert result["command_id"].startswith("cmd_")
    assert result["exit_code"] == 0
    assert result["blocked_by_policy"] is False
    assert (run_dir / "execution_log.yml").exists()
    assert (run_dir / result["stdout_path"]).exists()
    assert (run_dir / result["stderr_path"]).exists()
    assert result["stdout_sha256"]
    assert result["stderr_sha256"]


def test_dangerous_command_is_blocked_and_not_logged(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="rm -rf .",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is True
    assert result["command_id"] is None
    log = load_execution_log(run_dir)
    assert not log or not log.get("commands")


def test_cwd_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError):
        safe_resolve_cwd(tmp_path.parent, workspace)
    with pytest.raises(ValueError):
        safe_resolve_cwd("/", workspace)


def test_nonzero_exit_code_writes_execution_log(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    (workspace / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m py_compile broken.py",
        workspace_root=workspace,
    )

    assert result["exit_code"] != 0
    assert result["command_id"].startswith("cmd_")
    assert (run_dir / "execution_log.yml").exists()


def test_timeout_is_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", "pytest"), timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m pytest tests -q",
        workspace_root=workspace,
        timeout_sec=1,
    )

    assert result["timed_out"] is True
    assert result["exit_code"] is None
    assert result["command_id"].startswith("cmd_")


def test_validation_commands_success_generates_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    (workspace / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (run_dir / "validation_commands.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "workspace_root": ".",
            "commands": [{
                "name": "py_compile",
                "command": "python -m py_compile ok.py",
                "cwd": ".",
                "timeout_sec": 60,
                "required": True,
            }],
        }),
        encoding="utf-8",
    )

    summary = run_validation_commands_if_present(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        workspace_root=workspace,
    )

    assert summary["ran"] is True
    assert summary["all_required_passed"] is True
    assert "command_id: cmd_" in summary["summary_markdown"]
    assert "Result: all required validation commands passed" in summary["summary_markdown"]


def test_validation_commands_required_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    (workspace / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (run_dir / "validation_commands.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "workspace_root": ".",
            "commands": [{
                "name": "py_compile",
                "command": "python -m py_compile broken.py",
                "cwd": ".",
                "timeout_sec": 60,
                "required": True,
            }],
        }),
        encoding="utf-8",
    )

    summary = run_validation_commands_if_present(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        workspace_root=workspace,
    )

    assert summary["ran"] is True
    assert summary["all_required_passed"] is False
    assert summary["failed_required"]
    assert "required validation commands failed" in summary["summary_markdown"]


def test_normalize_and_policy_reject_python_script() -> None:
    assert normalize_command("python -m pytest tests -q") == ["python", "-m", "pytest", "tests", "-q"]
    allowed, reason = is_command_allowed("python script.py", {
        "allowed_executables": ["python"],
        "allowed_python_modules": ["pytest", "py_compile"],
        "blocked_executables": [],
        "blocked_substrings": [],
    })
    assert allowed is False
    assert "script execution" in reason


def test_py_compile_allows_workspace_relative_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    (workspace / "ok.py").write_text("x = 1\n", encoding="utf-8")

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m py_compile ok.py",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is False
    assert result["exit_code"] == 0
    assert result["command_id"].startswith("cmd_")


def test_py_compile_rejects_absolute_path_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command=["python", "-m", "py_compile", str(outside)],
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is True
    assert result["command_id"] is None
    assert "workspace" in result["blocked_reason"].lower()


def test_py_compile_rejects_parent_path_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    (tmp_path / "outside.py").write_text("x = 1\n", encoding="utf-8")

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m py_compile ../outside.py",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is True
    assert result["command_id"] is None
    assert "workspace" in result["blocked_reason"].lower()


def test_pytest_allows_workspace_tests_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)
    run_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m pytest tests -q",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is False
    assert result["exit_code"] == 0
    assert result["command_id"].startswith("cmd_")


def test_pytest_rejects_absolute_path_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    outside_tests = tmp_path / "outside_tests"
    workspace.mkdir()
    outside_tests.mkdir()
    run_dir.mkdir()

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command=["python", "-m", "pytest", str(outside_tests), "-q"],
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is True
    assert result["command_id"] is None
    assert "workspace" in result["blocked_reason"].lower()


def test_pytest_rejects_parent_path_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    outside_tests = tmp_path / "outside_tests"
    workspace.mkdir()
    outside_tests.mkdir()
    run_dir.mkdir()

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m pytest ../outside_tests -q",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is True
    assert result["command_id"] is None
    assert "workspace" in result["blocked_reason"].lower()


def test_pytest_k_expression_is_not_treated_as_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)
    run_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="python -m pytest tests -q -k ok",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is False
    assert result["exit_code"] == 0


def test_git_read_only_command_is_allowed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="git status",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is False
    assert result["command_id"].startswith("cmd_")


def test_git_dash_c_outside_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command=["git", "status", "-C", str(tmp_path)],
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is True
    assert result["command_id"] is None


def test_git_output_option_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()

    result = run_logged_command(
        agentlab_root=_agentlab_root(),
        run_dir=run_dir,
        command="git diff --output=/tmp/x",
        workspace_root=workspace,
    )

    assert result["blocked_by_policy"] is True
    assert result["command_id"] is None


def test_validate_command_paths_rejects_parent_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    ok, reason = validate_command_paths(["python", "-m", "py_compile", "../outside.py"], workspace)

    assert ok is False
    assert "workspace" in reason.lower()
