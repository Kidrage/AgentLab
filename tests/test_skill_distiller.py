from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skill_distiller import distill_skill_draft, list_skill_drafts, redact_sensitive_text


def _write_config(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "config" / "skill_distillation.yml").write_text(
        "enabled: true\nthresholds:\n  max_source_chars_per_file: 12000\n",
        encoding="utf-8",
    )
    (root / "config" / "model_pricing.yml").write_text(
        "version: 1\ncurrency: USD\nmodels: {}\n",
        encoding="utf-8",
    )


def _write_run(root: Path, project: str = "Demo", task_id: str = "task_001") -> Path:
    _write_config(root)
    project_dir = root / "projects" / project
    run_dir = project_dir / "runs" / task_id
    run_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text("# Memory\n- Reusable validation repair procedure.\n", encoding="utf-8")
    (run_dir / "task_events.jsonl").write_text('{"event":"VALIDATION_PASSED"}\n', encoding="utf-8")
    (run_dir / "06_implementation_report.md").write_text("# Implementation\n- Run audit before pytest.\n", encoding="utf-8")
    (run_dir / "07_validation_report.md").write_text("# Validation\npytest passed\n", encoding="utf-8")
    (run_dir / "learning_review.yml").write_text("name: reusable_validation_repair\n", encoding="utf-8")
    (run_dir / "skill_candidates").mkdir()
    (run_dir / "skill_candidates" / "candidate.yml").write_text("name: candidate_skill\n", encoding="utf-8")
    return run_dir


def test_distill_generates_required_artifacts(tmp_path: Path) -> None:
    _write_run(tmp_path)
    result = distill_skill_draft(tmp_path, "Demo", "task_001")
    draft_dir = Path(result["draft_path"])
    durable_dir = Path(result["durable_path"])
    assert durable_dir == tmp_path / "memory" / "global" / "skills" / "drafts" / result["draft_id"]
    for name in ["SKILL.md", "metadata.yml", "validation_plan.yml", "evidence_map.yml", "source_trace.yml", "origin_pointer.yml"]:
        assert (draft_dir / name).exists()
        assert (durable_dir / name).exists()
    pointer = tmp_path / "projects" / "Demo" / "runs" / "task_001" / "skill_drafts" / result["draft_id"] / "POINTER.yml"
    assert pointer.exists()
    assert not (pointer.parent / "SKILL.md").exists()
    skill_md = (durable_dir / "SKILL.md").read_text(encoding="utf-8")
    for heading in ["## When to use", "## Inputs and assumptions", "## Procedure", "## Validation checklist", "## Failure recovery", "## Anti-patterns", "## Evidence summary", "## Limits"]:
        assert heading in skill_md
    metadata = yaml.safe_load((draft_dir / "metadata.yml").read_text(encoding="utf-8"))
    assert metadata["status"] == "draft"
    assert metadata["source_type"] == "project_memory_distillation"
    assert metadata["manual_approval_required"] is True
    trace = yaml.safe_load((draft_dir / "source_trace.yml").read_text(encoding="utf-8"))
    assert any(item.get("sha256") for item in trace["sources"] if item["exists"])
    evidence = yaml.safe_load((draft_dir / "evidence_map.yml").read_text(encoding="utf-8"))
    assert evidence["evidence"][0]["claim"]
    plan = yaml.safe_load((draft_dir / "validation_plan.yml").read_text(encoding="utf-8"))
    assert plan["validation"]["mode"] == "local_dry_run"


def test_missing_files_create_warnings(tmp_path: Path) -> None:
    _write_config(tmp_path)
    (tmp_path / "projects" / "Demo" / "runs" / "task_missing").mkdir(parents=True)
    result = distill_skill_draft(tmp_path, "Demo", "task_missing")
    assert result["warnings"]


def test_list_skill_drafts(tmp_path: Path) -> None:
    _write_run(tmp_path)
    result = distill_skill_draft(tmp_path, "Demo", "task_001")
    drafts = list_skill_drafts(tmp_path, "Demo")
    assert [draft for draft in drafts if draft["id"] == result["draft_id"]]


def test_redaction_removes_sensitive_values() -> None:
    text = "api_key=abc123456789 email test@example.com /" + "Users" + "/name/project sk-abcdef1234567890"
    redacted = redact_sensitive_text(text)
    assert "test@example.com" not in redacted
    assert "/" + "Users" + "/name" not in redacted
    assert "sk-abcdef" not in redacted
    assert "abc123456789" not in redacted
