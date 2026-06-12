from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from command_runner import run_logged_command


def test_command_runner_blocks_clone_in_repo_profile(tmp_path: Path, monkeypatch) -> None:
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("subprocess.run", fake_run)
    result = run_logged_command(
        agentlab_root=tmp_path,
        run_dir=tmp_path / "run",
        workspace_root=tmp_path,
        command="git clone https://github.com/x/y",
        repo_mode="repo_profile",
    )

    assert result["blocked_by_policy"] is True
    assert called is False
    ledger = yaml.safe_load((tmp_path / "run" / "resource_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["commands"]["clone_commands_blocked"] == 1


def test_command_runner_pending_approval_for_build(tmp_path: Path, monkeypatch) -> None:
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("subprocess.run", fake_run)
    result = run_logged_command(
        agentlab_root=tmp_path,
        run_dir=tmp_path / "run",
        workspace_root=tmp_path,
        command="cmake --build build",
        repo_mode="repo_build_test",
    )

    assert result["pending_approval"] is True
    assert called is False
    ledger = yaml.safe_load((tmp_path / "run" / "resource_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["commands"]["approval_required"]