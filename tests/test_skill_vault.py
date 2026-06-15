from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skill_vault import ensure_skill_vault_layout, list_vault_skills, move_skill_status, register_skill


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
