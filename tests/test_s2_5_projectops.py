from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.project_ops.agent_packet import packet_from_dict, render_agent_packet_markdown
from agent_runtime.project_ops.project_router import init_project, project_status, route_invocation_to_project
from agent_runtime.project_ops.repo_hygiene import scan_repository_root
from agent_runtime.project_ops.task_compaction import compact_task


def test_repo_hygiene_flags_root_handoff(tmp_path: Path) -> None:
    (tmp_path / "agent_runtime").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "random_handoff.md").write_text("handoff", encoding="utf-8")
    report = scan_repository_root(tmp_path)
    assert not report.ok
    assert any(f.code == "forbidden_root_pattern" for f in report.findings)


def test_repo_hygiene_allows_explicit_canonical_handoff(tmp_path: Path) -> None:
    (tmp_path / "agent_runtime").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "PROJECT_HANDOFF.md").write_text("canonical handoff", encoding="utf-8")
    policy = {
        "root_policy": {
            "allowed_root_files": ["PROJECT_HANDOFF.md"],
            "allowed_root_dirs": ["agent_runtime", "config"],
            "ignored_runtime_dirs": [],
            "forbidden_root_patterns": ["*handoff*.md"],
        }
    }

    report = scan_repository_root(tmp_path, policy)

    assert report.ok
    assert not report.findings


def test_project_router_creates_new_project_for_creative() -> None:
    policy = {
        "routing": {
            "self_development_signals": ["AgentLab", "this repo"],
            "create_new_project_by_default_for": ["creative_longform"],
            "require_confirmation_when_ambiguous": True,
        }
    }
    decision = route_invocation_to_project(
        {"task_type": "creative_longform", "user_goal": "write a novel"},
        existing_projects=[],
        policy=policy,
    )
    assert decision.outcome == "create_new_project"
    assert decision.project_id != "AgentLab"


def test_project_router_routes_agentlab_self_development() -> None:
    policy = {
        "routing": {
            "self_development_signals": ["AgentLab", "this repo"],
            "create_new_project_by_default_for": ["creative_longform"],
            "require_confirmation_when_ambiguous": True,
        }
    }
    decision = route_invocation_to_project(
        {"task_type": "coding", "user_goal": "repair AgentLab repository"},
        existing_projects=[],
        policy=policy,
    )
    assert decision.outcome == "self_development_project"
    assert decision.project_id == "AgentLab"


def test_project_init_and_status(tmp_path: Path) -> None:
    result = init_project(tmp_path, "example_project", "creative", "Example Project")
    assert (tmp_path / "projects" / "example_project" / "project.yml").exists()
    assert (tmp_path / "projects" / "example_project" / "project_brain" / "decision_log.yml").exists()
    assert result.project_id == "example_project"
    status = project_status(tmp_path, "example_project")
    assert status["project"]["project_id"] == "example_project"
    assert status["task_counts"]["active"] == 0


def test_task_compaction_preserves_raw_and_writes_outputs(tmp_path: Path) -> None:
    task_dir = tmp_path / "projects" / "demo" / "tasks" / "closed" / "task_0001"
    task_dir.mkdir(parents=True)
    (task_dir / "final_report.md").write_text("decision accepted. reusable pattern.", encoding="utf-8")
    result = compact_task("demo", "task_0001", task_dir)
    compact_dir = task_dir / "task_compact"
    assert compact_dir.exists()
    assert (compact_dir / "artifact_index.yml").exists()
    assert (task_dir / "final_report.md").exists()
    assert result.memory_promotion_count >= 1


def test_agent_packet_validates_and_renders() -> None:
    packet = packet_from_dict(
        {
            "packet_id": "packet_001",
            "project_id": "demo",
            "task_id": "task_0001",
            "sender": "lead",
            "receiver": "qa",
            "purpose": "review",
            "max_context_budget_tokens": 1200,
            "must_read": ["artifact_index.yml"],
            "summary": {"what_changed": "compact done"},
            "requested_action": {"type": "review"},
            "forbidden": ["reread_full_raw_logs"],
        }
    )
    text = render_agent_packet_markdown(packet)
    assert "Agent Packet" in text
    assert "artifact_index.yml" in text


def test_agent_packet_rejects_large_budget() -> None:
    with pytest.raises(ValueError):
        packet_from_dict(
            {
                "packet_id": "packet_001",
                "project_id": "demo",
                "task_id": "task_0001",
                "sender": "lead",
                "receiver": "qa",
                "purpose": "review",
                "max_context_budget_tokens": 9000,
                "must_read": ["artifact_index.yml"],
                "summary": {"what_changed": "compact done"},
                "requested_action": {"type": "review"},
                "forbidden": ["reread_full_raw_logs"],
            }
        )
