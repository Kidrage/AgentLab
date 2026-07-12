from __future__ import annotations

import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import run_task
from skill_injector import inject_skills_into_workflow_plan
from skill_retriever import match_active_skills


def _write_policy(root: Path, *, max_skills: int = 3, high_risk_requires_approval: bool = True) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "skill_injection_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": True,
            "retrieval": {
                "max_skills_per_task": max_skills,
                "min_confidence": 0.0,
                "high_risk_requires_approval": high_risk_requires_approval,
                "default_injected_agents": ["Coder", "TesterAuditor"],
            },
            "matching": {"trigger_weight": 3, "applies_to_weight": 2, "summary_weight": 1},
            "usage": {"write_task_usage": True, "append_active_skill_ledger": True},
        }, sort_keys=False),
        encoding="utf-8",
    )


def _active_skill(
    root: Path,
    skill_id: str,
    *,
    status: str = "active",
    default_injection: bool | None = None,
    triggers: list[str] | None = None,
    applies_to: list[str] | None = None,
    risk_level: str = "low",
    confidence: float = 0.8,
) -> Path:
    skill_dir = root / "skills" / "active" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": 1,
        "skill_id": skill_id,
        "name": skill_id.replace("_", " ").title(),
        "skill_name": skill_id,
        "status": status,
        "triggers": triggers or [skill_id],
        "applies_to": applies_to or [],
        "summary": f"{skill_id} summary",
        "load_tokens": 100,
        "expected_saving_tokens": 500,
        "risk_level": risk_level,
        "permissions": {"can_read_repo": True, "can_modify_files": risk_level == "high"},
        "confidence": confidence,
    }
    if default_injection is not None:
        metadata["default_injection"] = default_injection
    (skill_dir / "metadata.yml").write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
    (skill_dir / "usage_ledger.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "skill_id": skill_id, "entries": []}, sort_keys=False),
        encoding="utf-8",
    )
    return skill_dir


def test_active_skill_can_match_task_goal_by_trigger(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    _active_skill(tmp_path, "pytest_repair", triggers=["pytest failed"], applies_to=["test_repair"])

    result = match_active_skills(tmp_path, task_text="Fix pytest failed import errors.")

    assert [s["skill_id"] for s in result["selected"]] == ["pytest_repair"]
    assert "matched trigger" in result["selected"][0]["reason"]


def test_negated_trigger_phrase_does_not_match_skill(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    _active_skill(tmp_path, "narrative_chapter_writer_lite", triggers=["小说章节", "长篇小说"])

    result = match_active_skills(
        tmp_path,
        task_text="这是长期沉浸式展览生成系统，不是小说章节，也不是长篇小说。",
    )

    assert result["selected"] == []


def test_positive_trigger_phrase_still_matches_skill(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    _active_skill(tmp_path, "narrative_chapter_writer_lite", triggers=["小说章节", "长篇小说"])

    result = match_active_skills(tmp_path, task_text="请继续写这个长篇小说的第 8 章。")

    assert [s["skill_id"] for s in result["selected"]] == ["narrative_chapter_writer_lite"]


def test_retired_or_inactive_skill_is_ignored(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    _active_skill(tmp_path, "old_skill", status="retired", triggers=["pytest failed"])

    result = match_active_skills(tmp_path, task_text="pytest failed")

    assert result["selected"] == []


def test_default_injection_false_skill_is_not_auto_injected(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    _active_skill(
        tmp_path,
        "story_long_write",
        default_injection=False,
        triggers=["灰烬王冠", "写第"],
        applies_to=["fiction_chapter_pipeline", "Writer"],
        confidence=0.95,
    )
    _active_skill(
        tmp_path,
        "narrative_chapter_writer_lite",
        triggers=["灰烬王冠", "写第"],
        applies_to=["narrative_light_chapter", "Writer"],
        confidence=0.8,
    )

    result = match_active_skills(tmp_path, task_text="灰烬王冠 写第10章")

    assert [s["skill_id"] for s in result["selected"]] == ["narrative_chapter_writer_lite"]
    rejected = {s["skill_id"]: s["reason"] for s in result["rejected"]}
    assert rejected["story_long_write"] == "default_injection is false"


def test_max_skills_per_task_respected(tmp_path: Path) -> None:
    _write_policy(tmp_path, max_skills=1)
    _active_skill(tmp_path, "skill_one", triggers=["pytest"])
    _active_skill(tmp_path, "skill_two", triggers=["pytest"])

    result = match_active_skills(tmp_path, task_text="pytest repair needed")

    assert len(result["selected"]) == 1
    assert any("max skills per task exceeded" in r["reason"] for r in result["rejected"])


def test_workflow_plan_records_selected_skills_and_usage_ledgers(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    _active_skill(tmp_path, "pytest_repair", triggers=["pytest failed"], applies_to=["test_repair"])
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_0001_skill"
    run_dir.mkdir(parents=True)
    plan_path = run_dir / "workflow_plan.yml"
    plan_path.write_text("project: Demo\ntask_id: task_0001_skill\n", encoding="utf-8")

    result = inject_skills_into_workflow_plan(
        tmp_path,
        plan_path,
        project="Demo",
        task_id="task_0001_skill",
        task_text="pytest failed in validation",
        record_usage=True,
    )

    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert plan["skills"]["selected"][0]["skill_id"] == "pytest_repair"
    assert result["selected"][0]["injected_into"] == ["Coder", "TesterAuditor"]
    usage = yaml.safe_load((run_dir / "skill_usage.yml").read_text(encoding="utf-8"))
    assert usage["selected"][0]["skill_id"] == "pytest_repair"
    ledger = yaml.safe_load((tmp_path / "skills" / "active" / "pytest_repair" / "usage_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["entries"][0]["task_id"] == "task_0001_skill"


def test_writer_route_injects_skills_into_writer_roles(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    _active_skill(tmp_path, "narrative_chapter_writer_lite", triggers=["灰烬王冠"], applies_to=["narrative_light_chapter"])
    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_crown_rewrite_ch10"
    run_dir.mkdir(parents=True)
    plan_path = run_dir / "workflow_plan.yml"
    plan_path.write_text(
        yaml.safe_dump(
            {"route": {"route_key": "narrative_light_chapter", "agents": ["Supervisor", "Writer"]}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = inject_skills_into_workflow_plan(
        tmp_path,
        plan_path,
        project="Crown_of_Ash",
        task_id="task_crown_rewrite_ch10",
        task_text="按照《灰烬王冠》重构蓝图及角色圣经，撰写第10章。",
        record_usage=True,
    )

    assert result["selected"][0]["skill_id"] == "narrative_chapter_writer_lite"
    assert result["selected"][0]["injected_into"] == ["Writer"]
    usage = yaml.safe_load((run_dir / "skill_usage.yml").read_text(encoding="utf-8"))
    assert usage["selected"][0]["injected_into"] == ["Writer"]


def test_high_risk_skill_requires_approval_if_policy_says_so(tmp_path: Path) -> None:
    _write_policy(tmp_path, high_risk_requires_approval=True)
    _active_skill(tmp_path, "dangerous_repair", triggers=["pytest"], risk_level="high")

    result = match_active_skills(tmp_path, task_text="pytest failed")

    assert result["selected"] == []
    assert result["rejected"][0]["reason"] == "high-risk skill requires approval before injection"


def test_prepare_write_plan_records_selected_skills_and_usage(tmp_path: Path, monkeypatch) -> None:
    _write_policy(tmp_path)
    _active_skill(tmp_path, "pytest_repair", triggers=["pytest failed"], applies_to=["test_repair"])
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_0001_skill"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Please fix pytest failed validation.", encoding="utf-8")
    monkeypatch.setattr(run_task, "runtime_context", lambda project: (tmp_path, project or "Demo"))

    result = CliRunner().invoke(
        run_task.app,
        ["prepare", "--project", "Demo", "--task-id", "task_0001_skill", "--write-plan"],
    )

    assert result.exit_code == 0, result.output
    plan = yaml.safe_load((run_dir / "workflow_plan.yml").read_text(encoding="utf-8"))
    assert plan["skills"]["selected"][0]["skill_id"] == "pytest_repair"
    assert (run_dir / "skill_usage.yml").exists()
