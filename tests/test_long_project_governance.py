from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.brain.mission_contract import build_mission_contract
from agent_runtime.context_governance.packers.narrative_packer import NarrativePacker
from agent_runtime.context_governance.schemas import ContextBudget, ContextProfile
from agent_runtime.executors.task_packet import create_task_packet


def test_chinese_novel_request_gets_longform_governance() -> None:
    contract = build_mission_contract(
        "我要写本长篇小说，先出蓝图和20章，需要人物设定、世界观、势力、关系和章节大纲。",
        project_id="NovelDemo",
        task_id="novel_001",
        agentlab_root=ROOT,
    )

    assert contract["project_type"] == "longform_text_project"
    governance = contract["long_project_governance"]
    assert governance["enabled"] is True
    assert "project_bible" in governance["required_plan_artifacts"]
    assert "outline" in governance["required_plan_artifacts"]
    assert "scene_cards" in governance["required_plan_artifacts"]
    assert governance["must_read_artifacts"]
    assert "设定/**/*.md" in governance["must_read_artifacts"]
    assert "must_read_artifacts_must_be_nonempty_for_long_projects" in governance["dispatch_gates"]


def test_narrative_packer_uses_real_refs_and_gap_cards(tmp_path: Path) -> None:
    agentlab_root = tmp_path
    config_dir = agentlab_root / "config"
    project_root = agentlab_root / "projects" / "NovelDemo"
    run_dir = project_root / "runs" / "task_001"
    (project_root / "设定" / "角色").mkdir(parents=True)
    (project_root / "大纲").mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir).mkdir()
    (config_dir / "long_project_governance.yml").write_text(
        (ROOT / "config" / "long_project_governance.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_root / "设定" / "角色" / "主角.md").write_text("# 主角\n冷静，目标清晰。\n", encoding="utf-8")
    (project_root / "大纲" / "大纲.md").write_text("# 第一卷\n逃亡与觉醒。\n", encoding="utf-8")
    (run_dir / "user_request.md").write_text("继续写下一批章节。", encoding="utf-8")

    pack = NarrativePacker().pack(
        ContextProfile(task_id="task_001", information_type="narrative_or_novel"),
        ContextBudget(task_id="task_001"),
        "继续写下一批章节。",
        run_dir,
    ).as_dict()

    dumped = yaml.safe_dump(pack, allow_unicode=True)
    assert "placeholder" not in dumped.lower()
    assert "设定/角色/主角.md" in dumped
    assert "大纲/大纲.md" in dumped
    assert "missing_scene_cards" in dumped
    assert "missing_continuity_ledger" in dumped


def test_task_packet_blocks_failed_plan_self_check(tmp_path: Path) -> None:
    phase = tmp_path / "phase_plan.yml"
    phase.write_text(
        yaml.safe_dump(
            {
                "project": "NovelDemo",
                "phase_id": "draft_batch",
                "goal": "Draft chapters 21-30",
                "plan_status": "needs_revision",
                "missing_facts": [{"fact": "scene_cards", "reason": "No next-batch cards"}],
                "self_check": {"passed": False},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="self-check"):
        create_task_packet(phase, "claude_code_handoff", tmp_path / "out")


def test_task_packet_allows_only_ready_or_approved_plan_status(tmp_path: Path) -> None:
    phase = tmp_path / "phase_plan.yml"
    phase.write_text(
        yaml.safe_dump(
            {
                "project": "NovelDemo",
                "phase_id": "draft_batch",
                "goal": "Draft chapters 31-40",
                "plan_status": "blocked_until_user_approval",
                "self_check": {"passed": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot be dispatched"):
        create_task_packet(phase, "claude_code_handoff", tmp_path / "out")
