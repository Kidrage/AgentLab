from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skills.incubation import default_incubation_policy, propose_internal_skill_candidates, write_incubation_artifacts


def _registry() -> dict:
    return {"external_skills": [{
        "skill_id": "ecc.planner",
        "source": "ecc",
        "display_name": "ECC Planner",
        "capabilities": ["planning"],
        "suitable_task_types": ["repo_patch"],
        "risk": {"level": "medium", "reasons": ["external_dependency_risk"], "requires_approval": True},
        "license": {"name": "unknown"},
    }]}


def _usage() -> dict:
    return {"entries": [
        {"skill_id": "ecc.planner", "event": "used", "success": True, "quality_score": 0.9},
        {"skill_id": "ecc.planner", "event": "used", "success": True, "quality_score": 0.9},
    ]}


def test_incubation_artifacts_written(tmp_path: Path) -> None:
    candidates = propose_internal_skill_candidates(_registry(), _usage(), default_incubation_policy())
    paths = write_incubation_artifacts(tmp_path, task_id="task_xxx", candidates=candidates, warnings=[])
    assert paths["candidates"].exists()
    assert paths["report"].exists()
    data = yaml.safe_load(paths["candidates"].read_text(encoding="utf-8"))
    assert data["candidates"]


def test_incubation_empty_usage_writes_warning(tmp_path: Path) -> None:
    paths = write_incubation_artifacts(tmp_path, task_id="task_empty", candidates=[], warnings=["warning: usage ledger not found"])
    data = yaml.safe_load(paths["candidates"].read_text(encoding="utf-8"))
    assert data["candidates"] == []
    assert "usage ledger not found" in paths["report"].read_text(encoding="utf-8")


def test_incubation_report_never_contains_source_code_copy(tmp_path: Path) -> None:
    candidates = propose_internal_skill_candidates(_registry(), _usage(), default_incubation_policy())
    paths = write_incubation_artifacts(tmp_path, task_id="task_xxx", candidates=candidates)
    report = paths["report"].read_text(encoding="utf-8")
    data = yaml.safe_load(paths["candidates"].read_text(encoding="utf-8"))
    assert "source_code_copied: false" in report
    assert data["candidates"][0]["safety"]["source_code_copied"] is False
    assert data["candidates"][0]["safety"]["license_review_required"] is True