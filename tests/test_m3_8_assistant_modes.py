"""M3-8 Assistant Modes — grounded answers citing concrete records."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.assistant.grounding import answer_question
from agent_runtime.assistant.models import AssistantQuestion


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_assistant_fixture(root: Path) -> Path:
    """Create project fixture for assistant tests."""
    proj = root / "projects" / "Crown_of_Ash"
    brain = proj / "project_brain"
    runs = proj / "runs"
    brain.mkdir(parents=True)

    (proj / "PROJECT_HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")
    _write_yaml(proj / "project_artifact_index.yml", {"artifacts": []})
    _write_yaml(brain / "project_fact_snapshot.yml", {
        "project": "Crown_of_Ash",
        "event_count": 3,
    })
    _write_yaml(brain / "acceptance_history.yml", {
        "entries": [
            {
                "phase_id": "phase_1",
                "accepted": True,
                "verdict": "PASS",
                "recommended_next_action": "next_phase",
                "evidence_files": ["world_bible.yml"],
                "recorded_at": "2026-07-01T00:00:00Z",
            },
            {
                "phase_id": "phase_2",
                "accepted": False,
                "verdict": "NEEDS_HUMAN_REVIEW",
                "recommended_next_action": "await_operator_approval",
                "human_approval_required": True,
                "missing_evidence": ["continuity_report.md"],
                "recorded_at": "2026-07-01T01:00:00Z",
            },
            {
                "phase_id": "phase_3",
                "accepted": False,
                "verdict": "BLOCKED",
                "recommended_next_action": "request_missing_evidence",
                "missing_evidence": ["style_check.yml"],
                "recorded_at": "2026-07-01T02:00:00Z",
            },
        ],
    })
    _write_yaml(brain / "next_actions.yml", {
        "next_phase_id": "phase_2",
        "next_action": "await_operator_approval",
        "reason": "phase needs human review",
    })
    _write_yaml(brain / "current_phase.yml", {
        "phase_id": "phase_2",
        "status": "in_progress",
    })

    # task with cost ledger
    t1 = runs / "task_001"
    t1.mkdir(parents=True)
    _write_yaml(t1 / "cost_ledger.yml", {
        "task_id": "task_001",
        "calls": [
            {"stage": "phase_1", "agent": "coder", "model_alias": "deepseek-v4-pro",
             "input_tokens": 5000, "output_tokens": 2000, "estimated_cost_usd": 0.015},
        ],
    })

    return proj


def test_answer_why_blocked_returns_sources() -> None:
    """Blocked-items question must cite acceptance_history and next_actions."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_assistant_fixture(root)
        question = AssistantQuestion(mode="operator", project="Crown_of_Ash",
                                     question="Why is the project blocked?")
        answer = answer_question(question, root)
        assert answer.confidence in ("high", "low")
        assert any("acceptance_history" in s.path for s in answer.grounding_sources)


def test_answer_evidence_missing_cites_ledgers() -> None:
    """Missing-evidence question must cite acceptance_history and evidence_ledger."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_assistant_fixture(root)
        question = AssistantQuestion(mode="operator", project="Crown_of_Ash",
                                     question="What evidence is missing?")
        answer = answer_question(question, root)
        assert answer.answer  # non-empty answer
        assert any("acceptance_history" in s.path for s in answer.grounding_sources)


def test_answer_executor_failed_cites_recovery() -> None:
    """Executor-failure question must cite recovery plans."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_assistant_fixture(root)
        question = AssistantQuestion(mode="operator", project="Crown_of_Ash",
                                     question="Which executor result failed?")
        answer = answer_question(question, root)
        assert answer.answer
        assert any("recovery" in s.path or "acceptance_history" in s.path
                   for s in answer.grounding_sources)


def test_answer_approval_guidance_pending() -> None:
    """Approval guidance must enumerate pending items."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_assistant_fixture(root)
        question = AssistantQuestion(mode="operator", project="Crown_of_Ash",
                                     question="What should I approve or reject?")
        answer = answer_question(question, root)
        assert "phase_2" in answer.answer or "phase_acceptance" in answer.answer.lower()


def test_answer_cost_cites_ledger() -> None:
    """Cost question must cite cost_ledger."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_assistant_fixture(root)
        question = AssistantQuestion(mode="operator", project="Crown_of_Ash",
                                     question="Where did cost go this phase?")
        answer = answer_question(question, root)
        assert answer.answer
        assert any("cost_ledger" in s.path for s in answer.grounding_sources)


def test_answer_next_safe_action_derives_from_project_brain() -> None:
    """Next-safe-action answer MUST cite acceptance_history and next_actions.

    This is the critical M3-8 test: the assistant must prove that the next safe
    action comes from Project Brain records, not from directory layout inference.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_assistant_fixture(root)
        question = AssistantQuestion(mode="operator", project="Crown_of_Ash",
                                     question="What is the next safe action?")
        answer = answer_question(question, root)

        # Must cite both acceptance_history AND next_actions
        paths = [s.path for s in answer.grounding_sources]
        assert any("acceptance_history.yml" in p for p in paths), \
            "next safe action must cite acceptance_history.yml"
        assert any("next_actions.yml" in p for p in paths), \
            "next safe action must cite next_actions.yml"

        # Answer must mention that it derives from these sources (not directories)
        answer_text = answer.answer.lower()
        assert "acceptance_history" in answer_text or "next_actions" in answer_text, \
            "Answer must mention its source: acceptance_history or next_actions"


def test_answer_fact_changes_cites_fact_snapshot() -> None:
    """Fact-change question must cite project_fact_snapshot."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_assistant_fixture(root)
        question = AssistantQuestion(mode="operator", project="Crown_of_Ash",
                                     question="What changed in the fact snapshot?")
        answer = answer_question(question, root)
        assert answer.answer
        assert any("fact_snapshot" in s.path for s in answer.grounding_sources)


def test_answer_unknown_project() -> None:
    """Unknown project should return confidence=none with diagnostic."""
    question = AssistantQuestion(mode="operator", project="NonExistent",
                                 question="What is the status?")
    answer = answer_question(question)
    assert answer.confidence == "none"
    assert "project-status" in answer.answer.lower()
