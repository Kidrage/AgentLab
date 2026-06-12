from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skills.usage_ledger import default_skill_usage_ledger, load_skill_usage_ledger, record_skill_event, write_skill_usage_ledger


def test_skill_usage_ledger_records_planned_event(tmp_path: Path) -> None:
    ledger = default_skill_usage_ledger("task_001")
    record_skill_event(ledger, task_id="task_001", skill_id="ecc.planner", source="ecc", event="planned", reason="repo_patch planning candidate")
    path = tmp_path / "skill_usage_ledger.yml"
    write_skill_usage_ledger(path, ledger)
    loaded = load_skill_usage_ledger(path)
    assert loaded["entries"][0]["event"] == "planned"
    assert loaded["entries"][0]["skill_id"] == "ecc.planner"


def test_skill_usage_ledger_records_rejected_event() -> None:
    ledger = default_skill_usage_ledger("task_001")
    entry = record_skill_event(ledger, task_id="task_001", skill_id="ecc.planner", source="ecc", event="rejected", reason="external skill disabled by policy")
    assert entry["event"] == "rejected"
    assert entry["success"] is None
