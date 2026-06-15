from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skill_vault import (
    ensure_skill_vault_layout,
    list_vault_skills,
    migrate_project_run_draft_to_vault,
    move_skill_status,
    register_skill,
)


def _write_config(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "config" / "skill_vault.yml").write_text(
        "version: 1\nenabled: true\nlocal_root: memory/global/skills\n",
        encoding="utf-8",
    )


def test_ensure_layout_registry_and_manifest(tmp_path: Path) -> None:
    _write_config(tmp_path)
    root = ensure_skill_vault_layout(tmp_path)
    for rel in [
        "registry.yml",
        "MANIFEST.yml",
        "inbox/self_learned",
        "inbox/external_imports",
        "inbox/discovered",
        "drafts",
        "approved",
        "staging",
        "active",
        "rejected",
        "retired",
        "quarantine",
    ]:
        assert (root / rel).exists()


def test_register_and_move_skill_updates_registry(tmp_path: Path) -> None:
    _write_config(tmp_path)
    draft = ensure_skill_vault_layout(tmp_path) / "drafts" / "skill_demo"
    draft.mkdir(parents=True)
    (draft / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    register_skill(tmp_path, "skill_demo", draft, {"name": "Demo", "project": "Demo", "task_ids": ["task_1"]})
    assert list_vault_skills(tmp_path, project="Demo")[0]["id"] == "skill_demo"
    approved = move_skill_status(tmp_path, "skill_demo", "drafts", "approved")
    assert approved.exists()
    registry = yaml.safe_load((tmp_path / "memory/global/skills/registry.yml").read_text(encoding="utf-8"))
    assert registry["skills"]["skill_demo"]["status"] == "approved"


def _make_draft(root: Path, project: str, task_id: str, skill_id: str) -> Path:
    """Create a minimal skill draft under projects/<project>/runs/<task_id>/skill_drafts/<skill_id>."""
    draft_dir = root / "projects" / project / "runs" / task_id / "skill_drafts" / skill_id
    draft_dir.mkdir(parents=True)
    (draft_dir / "SKILL.md").write_text(f"# {skill_id}\n\nTest skill draft.\n", encoding="utf-8")
    (draft_dir / "metadata.yml").write_text(
        f"name: {skill_id}\nproject: {project}\ntask_ids:\n  - {task_id}\n",
        encoding="utf-8",
    )
    return draft_dir


def test_execute_true_forces_dry_run_false(tmp_path: Path) -> None:
    """execute=True must force dry_run=False regardless of dry_run param."""
    _write_config(tmp_path)
    _make_draft(tmp_path, "AgentLab", "task_test", "skill_exec_test")
    result = migrate_project_run_draft_to_vault(
        tmp_path,
        "AgentLab",
        dry_run=True,
        execute=True,
    )
    assert result["dry_run"] is False
    assert result["project"] == "AgentLab"


def test_dry_run_does_not_write_to_vault(tmp_path: Path) -> None:
    """dry_run=True, execute=False returns planned without copying files."""
    _write_config(tmp_path)
    _make_draft(tmp_path, "AgentLab", "task_test", "skill_dry")
    result = migrate_project_run_draft_to_vault(
        tmp_path,
        "AgentLab",
        dry_run=True,
        execute=False,
    )
    assert result["dry_run"] is True
    assert len(result["migrations"]) >= 1
    item = result["migrations"][0]
    assert item["skill_id"] == "skill_dry"
    assert item["status"] == "planned"
    target = tmp_path / item["target"]
    assert not target.exists(), "dry-run must not create vault files"


def test_execute_true_migrates_real_files(tmp_path: Path) -> None:
    """execute=True (forces dry_run=False) must copy draft files into vault."""
    _write_config(tmp_path)
    _make_draft(tmp_path, "AgentLab", "task_test", "skill_exec_real")
    result = migrate_project_run_draft_to_vault(
        tmp_path,
        "AgentLab",
        dry_run=True,
        execute=True,
    )
    assert result["dry_run"] is False
    assert len(result["migrations"]) >= 1
    item = result["migrations"][0]
    assert item["skill_id"] == "skill_exec_real"
    assert item["status"] == "migrated"
    target_dir = tmp_path / item["target"]
    assert target_dir.exists(), "execute must create vault skill directory"
    assert (target_dir / "SKILL.md").exists()
    assert (target_dir / "metadata.yml").exists()
    # Verify registry entry
    assert list_vault_skills(tmp_path, project="AgentLab"), "registry should list migrated skill"


def test_repeated_migration_is_idempotent(tmp_path: Path) -> None:
    """Second migration of the same skill must return already_exists."""
    _write_config(tmp_path)
    _make_draft(tmp_path, "AgentLab", "task_test", "skill_idem")
    # First migration
    result1 = migrate_project_run_draft_to_vault(tmp_path, "AgentLab", dry_run=True, execute=True)
    assert result1["migrations"][0]["status"] == "migrated"
    # Second migration — same draft
    result2 = migrate_project_run_draft_to_vault(tmp_path, "AgentLab", dry_run=True, execute=True)
    item2 = result2["migrations"][0]
    assert item2["skill_id"] == "skill_idem"
    assert item2["status"] == "already_exists"
    # Target directory should still exist and contain files
    target = tmp_path / item2["target"]
    assert target.exists()
    assert (target / "SKILL.md").exists()


def test_draft_not_found_is_skipped(tmp_path: Path) -> None:
    """When no valid drafts exist, migrations list is empty (no crash)."""
    _write_config(tmp_path)
    # No draft directories at all — function should handle gracefully
    result = migrate_project_run_draft_to_vault(
        tmp_path,
        "AgentLab",
        dry_run=True,
        execute=False,
    )
    assert result["project"] == "AgentLab"
    assert result["dry_run"] is True
    assert result["migrations"] == []

    # Create a draft directory that lacks SKILL.md (invalid draft)
    invalid = tmp_path / "projects" / "AgentLab" / "runs" / "task_x" / "skill_drafts" / "bad_skill"
    invalid.mkdir(parents=True)
    (invalid / "metadata.yml").write_text("name: bad\n", encoding="utf-8")
    result2 = migrate_project_run_draft_to_vault(tmp_path, "AgentLab", dry_run=True, execute=False)
    assert not any(m["skill_id"] == "bad_skill" for m in result2["migrations"]), \
        "drafts without SKILL.md must be skipped silently"
