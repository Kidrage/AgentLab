"""Tests for truenas_sync dry-run, SSH config, SMB fallback, and rsync arg handling."""

from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from truenas_sync import (
    DEFAULT_EXCLUDES,
    _build_memory_sync_items,
    _build_rsync_command,
    _is_excluded,
    _load_backup_policy,
    _matches_pattern,
    _ssh_command,
    _ssh_config,
    _ssh_dest,
    build_backup_status,
    get_truenas_status,
    run_truenas_sync,
    utc_now,
)


def _write_policy(root: Path, content: str) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "backup_policy.yml").write_text(content, encoding="utf-8")


def _write_ssh_policy(root: Path) -> None:
    _write_policy(
        root,
        "version: 1\n"
        "targets:\n"
        "  truenas:\n"
        "    enabled: true\n"
        "    transport: ssh\n"
        "    ssh:\n"
        "      host: truenas.local\n"
        "      port: 22\n"
        "      user: testuser\n"
        "      identity_file: ~/.ssh/id_ed25519\n"
        "      remote_base_path: /mnt/pool/agentlab\n",
    )


def _write_smb_policy(root: Path) -> None:
    _write_policy(
        root,
        "version: 1\n"
        "targets:\n"
        "  truenas:\n"
        "    enabled: true\n"
        "    transport: smb_mount\n"
        "    mount_path: /Volumes/truenas\n"
        "    protocol_url: smb://truenas.local/share\n",
    )


def test_utc_now_returns_iso_string() -> None:
    result = utc_now()
    assert isinstance(result, str)
    assert "T" in result


def test_load_backup_policy_returns_dict(tmp_path: Path) -> None:
    _write_policy(tmp_path, "version: 1\n")
    policy = _load_backup_policy(tmp_path)
    assert isinstance(policy, dict)


def test_get_truenas_status_disabled(tmp_path: Path) -> None:
    _write_policy(tmp_path, "version: 1\ntargets:\n  truenas:\n    enabled: false\n")
    status = get_truenas_status(tmp_path, write_probe=False)
    assert status["status"] == "warn"
    assert status["enabled"] is False


def test_get_truenas_status_ssh_no_config(tmp_path: Path) -> None:
    _write_ssh_policy(tmp_path)
    # Remove SSH host to test clean failure
    (tmp_path / "config" / "backup_policy.yml").write_text(
        "version: 1\ntargets:\n  truenas:\n    enabled: true\n    transport: ssh\n",
        encoding="utf-8",
    )
    status = get_truenas_status(tmp_path, write_probe=False)
    assert status["status"] == "fail"


def test_get_truenas_status_smb_no_mount(tmp_path: Path) -> None:
    _write_smb_policy(tmp_path)
    status = get_truenas_status(tmp_path, write_probe=False)
    # mount path /Volumes/truenas won't exist on this machine
    assert status["status"] == "fail"


def test_ssh_config_returns_dict(tmp_path: Path) -> None:
    _write_ssh_policy(tmp_path)
    from truenas_sync import _truenas_config
    cfg = _truenas_config(tmp_path)
    ssh = _ssh_config(cfg)
    assert isinstance(ssh, dict)
    assert ssh["host"] == "truenas.local"
    assert ssh["port"] == 22
    assert ssh["user"] == "testuser"


def test_ssh_command_builds_list(tmp_path: Path) -> None:
    _write_ssh_policy(tmp_path)
    from truenas_sync import _truenas_config
    cfg = _truenas_config(tmp_path)
    ssh = _ssh_config(cfg)
    cmd = _ssh_command(ssh)
    assert isinstance(cmd, list)
    assert cmd[0] == "ssh"


def test_ssh_dest_returns_user_at_host(tmp_path: Path) -> None:
    _write_ssh_policy(tmp_path)
    from truenas_sync import _truenas_config
    cfg = _truenas_config(tmp_path)
    ssh = _ssh_config(cfg)
    dest = _ssh_dest(ssh)
    assert dest == "testuser@truenas.local"


def test_build_rsync_command_returns_list(tmp_path: Path) -> None:
    _write_ssh_policy(tmp_path)
    from truenas_sync import _truenas_config
    cfg = _truenas_config(tmp_path)
    ssh = _ssh_config(cfg)
    cmd = _build_rsync_command(ssh, tmp_path, "test/path", dry_run=True)
    assert isinstance(cmd, list)
    assert "rsync" in cmd[0]
    assert "--dry-run" in cmd
    assert "--ignore-existing" in cmd  # never overwrite remote


def test_build_rsync_command_no_shell_true(tmp_path: Path) -> None:
    """rsync command must be a list, not a shell string (no shell=True)."""
    _write_ssh_policy(tmp_path)
    from truenas_sync import _truenas_config
    cfg = _truenas_config(tmp_path)
    ssh = _ssh_config(cfg)
    cmd = _build_rsync_command(ssh, tmp_path, "test/path", dry_run=False)
    assert isinstance(cmd, list)
    for part in cmd:
        assert isinstance(part, str)


def test_run_truenas_sync_dry_run_no_ssh_connection(tmp_path: Path) -> None:
    """dry-run should not attempt real SSH connection; should fail cleanly."""
    _write_ssh_policy(tmp_path)
    project_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_001"
    project_dir.mkdir(parents=True)
    result = run_truenas_sync(
        tmp_path,
        project="TestProject",
        task_id="task_001",
        dry_run=True,
        execute=False,
        write_probe=False,
    )
    assert isinstance(result, dict)
    assert result["dry_run"] is True


def test_run_truenas_sync_dry_run_true_when_execute_false(tmp_path: Path) -> None:
    """dry_run=True + execute=False must keep dry_run=True."""
    _write_ssh_policy(tmp_path)
    project_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_001"
    project_dir.mkdir(parents=True)
    result = run_truenas_sync(
        tmp_path,
        project="TestProject",
        task_id="task_001",
        dry_run=True,
        execute=False,
        write_probe=False,
    )
    assert result["dry_run"] is True


def test_run_truenas_sync_forces_dry_run_false_when_execute_true(tmp_path: Path) -> None:
    """execute=True should force dry_run=False, but without valid SSH it should fail cleanly."""
    _write_ssh_policy(tmp_path)
    project_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_001"
    project_dir.mkdir(parents=True)
    result = run_truenas_sync(
        tmp_path,
        project="TestProject",
        task_id="task_001",
        dry_run=True,
        execute=True,
        write_probe=False,
    )
    assert result["dry_run"] is False


def test_is_excluded_matches_git_and_venv() -> None:
    assert _is_excluded(".git/config", DEFAULT_EXCLUDES) is True
    assert _is_excluded(".venv/bin/python", DEFAULT_EXCLUDES) is True
    assert _is_excluded("agent_runtime/__pycache__/foo.cpython-311.pyc", DEFAULT_EXCLUDES) is True


def test_matches_pattern_handles_wildcards() -> None:
    assert _matches_pattern("foo/bar.py", "**/*.py") is True
    assert _matches_pattern(".git/config", ".git/**") is True
    assert _matches_pattern("node_modules/pkg/index.js", "node_modules/**") is True


def test_build_backup_status_returns_dict(tmp_path: Path) -> None:
    _write_ssh_policy(tmp_path)
    (tmp_path / "projects" / "TestProject").mkdir(parents=True)
    (tmp_path / "projects" / "TestProject" / "project_config.yml").write_text(
        "github:\n  backup:\n    enabled: false\n",
        encoding="utf-8",
    )
    status = build_backup_status(tmp_path, project="TestProject")
    assert isinstance(status, dict)
    assert "github" in status
    assert "truenas" in status
    assert "ledger" in status


def test_repository_handoff_memory_is_in_sync_items(tmp_path: Path) -> None:
    repository_memory = tmp_path / "memory" / "repositories" / "sample-id"
    repository_memory.mkdir(parents=True)
    (repository_memory / "HandOff.md").write_text("# HandOff\n", encoding="utf-8")

    items = _build_memory_sync_items(tmp_path, {})

    assert any(
        item["local_abs"] == tmp_path / "memory" / "repositories"
        and item["remote_path"] == "memory/repositories/"
        for item in items
    )
