"""Tests for skill_backup plan_rsync, dry_run, and execute behavior."""

from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skill_backup import (
    BackupPlan,
    backup_status,
    dry_run_rsync_command,
    execute_rsync,
    load_backup_policy,
    plan_rsync_command,
    resolve_local_skill_vault_path,
    resolve_remote_skill_vault_path,
)


def _write_config(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "backup_policy.yml").write_text(
        "version: 1\nskill_vault_backup:\n  enabled: true\n  source: memory/global/skills\n  remote_subdir: memory/global/skills\n  dry_run_default: true\n",
        encoding="utf-8",
    )


def _write_ssh_config(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "backup_policy.yml").write_text(
        "version: 1\n"
        "skill_vault_backup:\n"
        "  enabled: true\n"
        "  source: memory/global/skills\n"
        "  remote_subdir: memory/global/skills\n"
        "ssh:\n"
        "  host: truenas.local\n"
        "  port: 22\n"
        "  user: testuser\n"
        "  remote_base_path: /mnt/pool/agentlab\n",
        encoding="utf-8",
    )


def test_load_backup_policy_returns_dict(tmp_path: Path) -> None:
    _write_config(tmp_path)
    policy = load_backup_policy(tmp_path)
    assert isinstance(policy, dict)
    assert "skill_vault_backup" in policy


def test_resolve_local_skill_vault_path_returns_absolute(tmp_path: Path) -> None:
    _write_config(tmp_path)
    local = resolve_local_skill_vault_path(tmp_path)
    assert isinstance(local, Path)


def test_plan_rsync_disabled_returns_not_ready(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "backup_policy.yml").write_text(
        "version: 1\nskill_vault_backup:\n  enabled: false\n",
        encoding="utf-8",
    )
    plan = plan_rsync_command(tmp_path, dry_run=True)
    assert plan.ready is False
    assert "disabled" in (plan.error or "").lower()


def test_plan_rsync_dry_run_does_not_execute(tmp_path: Path) -> None:
    _write_config(tmp_path)
    plan = plan_rsync_command(tmp_path, dry_run=True)
    assert plan.dry_run is True
    if plan.ready:
        assert "--dry-run" in plan.command


def test_plan_rsync_missing_remote_returns_not_ready(tmp_path: Path) -> None:
    """Without SSH config, plan should be not ready with clear error."""
    _write_config(tmp_path)
    plan = plan_rsync_command(tmp_path, dry_run=False)
    assert plan.ready is False
    assert plan.error is not None
    assert "missing" in plan.error.lower() or "ssh" in plan.error.lower()


def test_dry_run_rsync_command_returns_dict(tmp_path: Path) -> None:
    _write_config(tmp_path)
    result = dry_run_rsync_command(tmp_path)
    assert isinstance(result, dict)
    assert result["dry_run"] is True


def test_execute_rsync_without_config_returns_error(tmp_path: Path) -> None:
    _write_config(tmp_path)
    result = execute_rsync(tmp_path)
    assert result["executed"] is False
    assert result["ready"] is False
    assert result["error"] is not None


def test_backup_status_returns_enabled_flag(tmp_path: Path) -> None:
    _write_config(tmp_path)
    status = backup_status(tmp_path)
    assert isinstance(status, dict)
    assert "enabled" in status
    assert "ready" in status


def test_backup_status_with_ssh_config(tmp_path: Path) -> None:
    _write_ssh_config(tmp_path)
    status = backup_status(tmp_path)
    assert isinstance(status, dict)
    # With SSH config present, the plan should be ready (rsync command can be built)
    # but actual connectivity requires key/password at runtime
    assert status["enabled"] is True


def test_resolve_remote_skill_vault_path_raises_without_config(tmp_path: Path) -> None:
    _write_config(tmp_path)
    try:
        resolve_remote_skill_vault_path(tmp_path)
        assert False, "Expected ValueError without SSH config"
    except ValueError as exc:
        assert "missing" in str(exc).lower() or "ssh" in str(exc).lower()


def test_resolve_remote_skill_vault_path_with_env_override(tmp_path: Path) -> None:
    _write_config(tmp_path)
    os.environ["AGENTLAB_SKILL_VAULT_BACKUP_REMOTE"] = "testuser@testhost:/mnt/pool"
    try:
        remote = resolve_remote_skill_vault_path(tmp_path)
        assert "testuser@testhost" in remote
    finally:
        os.environ.pop("AGENTLAB_SKILL_VAULT_BACKUP_REMOTE", None)


def test_plan_rsync_execute_false_dry_run_true(tmp_path: Path) -> None:
    """plan_rsync_command with dry_run=True should include --dry-run flag."""
    _write_ssh_config(tmp_path)
    plan = plan_rsync_command(tmp_path, dry_run=True)
    assert plan.dry_run is True
    if plan.ready:
        assert "--dry-run" in plan.command


def test_plan_rsync_execute_true_dry_run_false(tmp_path: Path) -> None:
    """plan_rsync_command with dry_run=False should NOT include --dry-run flag."""
    _write_ssh_config(tmp_path)
    plan = plan_rsync_command(tmp_path, dry_run=False)
    assert plan.dry_run is False
    if plan.ready:
        assert "--dry-run" not in plan.command
