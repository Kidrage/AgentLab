from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skill_backup import dry_run_rsync_command, execute_rsync


def _config(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "config" / "backup_policy.yml").write_text(
        "skill_vault_backup:\n  enabled: true\n  source: memory/global/skills\n  remote_subdir: memory/global/skills\n  dry_run_default: true\n",
        encoding="utf-8",
    )
    (root / "config" / "skill_vault.yml").write_text("local_root: memory/global/skills\n", encoding="utf-8")


def test_backup_dry_run_outputs_rsync_plan_without_execute(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path)
    monkeypatch.setenv("AGENTLAB_SKILL_VAULT_BACKUP_REMOTE", "user@example:/backup")
    result = dry_run_rsync_command(tmp_path)
    assert result["dry_run"] is True
    assert "rsync" in result["command"]
    assert "--dry-run" in result["command"]
    assert result["ready"] is True


def test_backup_execute_missing_ssh_config_is_clear_error(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path)
    monkeypatch.delenv("AGENTLAB_SKILL_VAULT_BACKUP_REMOTE", raising=False)
    monkeypatch.delenv("AGENTLAB_BACKUP_SSH_USER", raising=False)
    monkeypatch.delenv("AGENTLAB_BACKUP_SSH_HOST", raising=False)
    monkeypatch.delenv("AGENTLAB_BACKUP_REMOTE_BASE", raising=False)
    result = execute_rsync(tmp_path)
    assert result["executed"] is False
    assert "Missing SSH backup config" in result["error"]
