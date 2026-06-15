from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skill_vault import migrate_project_run_draft_to_vault


def _legacy(root: Path) -> Path:
    draft = root / "projects" / "Demo" / "runs" / "task_1" / "skill_drafts" / "skill_old"
    draft.mkdir(parents=True)
    (draft / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    (draft / "metadata.yml").write_text("id: skill_old\nname: Old\nproject: Demo\ntask_ids:\n  - task_1\n", encoding="utf-8")
    return draft


def test_migrate_dry_run_does_not_modify(tmp_path: Path) -> None:
    _legacy(tmp_path)
    result = migrate_project_run_draft_to_vault(tmp_path, "Demo", dry_run=True, execute=False)
    assert result["migrations"][0]["status"] == "planned"
    assert not (tmp_path / "memory/global/skills/drafts/skill_old").exists()


def test_migrate_execute_copies_and_leaves_pointer(tmp_path: Path) -> None:
    _legacy(tmp_path)
    result = migrate_project_run_draft_to_vault(tmp_path, "Demo", dry_run=False, execute=True)
    assert result["migrations"][0]["status"] == "migrated"
    assert (tmp_path / "memory/global/skills/drafts/skill_old/SKILL.md").exists()
    assert (tmp_path / "projects/Demo/runs/task_1/skill_drafts/skill_old/POINTER.yml").exists()
