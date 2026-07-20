from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.program_manager.phase_acceptance import accept_phase
from agent_runtime.program_manager.project_brain import build_project_brain, build_project_plan
from agent_runtime.program_manager.project_fact_state import load_project_fact_snapshot
from agent_runtime.program_manager.project_state_contract import compile_project_state_contract, load_project_state_templates
from agent_runtime.program_manager.state_transition_validator import validate_state_transition_proposal
from agent_runtime.program_manager.state_template_evolution import (
    build_state_template_candidate,
    transition_state_template_candidate,
)


def _mission(path: Path, task_type: str = "creative_longform", goal: str = "Write a long epic novel") -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "task_id": "mission_state",
                "task_type": task_type,
                "user_goal": goal,
                "intent_summary": goal,
                "required_capabilities": [{"capability": "local_search"}],
                "risk_flags": ["long_running_project"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _phase(project_brain: Path, phase_id: str = "draft_batch") -> Path:
    phase = {
        "project": "NovelDemo",
        "project_brain_dir": str(project_brain),
        "phase_id": phase_id,
        "goal": "Advance durable project facts",
        "outputs": ["continuity_ledger"],
        "evidence_required": [],
        "human_decision_points": [],
        "state_contract": {
            "project_brain_dir": str(project_brain),
            "contract_ref": "project_state_contract.yml",
            "snapshot_ref": "project_fact_snapshot.yml",
            "transition_artifact": "state_transition_proposal.yml",
            "transition_proposal_required": True,
        },
    }
    path = project_brain / f"{phase_id}.yml"
    path.write_text(yaml.safe_dump(phase, sort_keys=False), encoding="utf-8")
    return path


def _proposal(evidence: Path, event: dict) -> None:
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "state_transition_proposal.yml").write_text(
        yaml.safe_dump({"state_transition_proposal": {"phase_id": "draft_batch", "events": [event]}}, sort_keys=False),
        encoding="utf-8",
    )


def test_project_brain_initializes_fact_state_contract_and_phase_refs(tmp_path: Path) -> None:
    build_project_brain(_mission(tmp_path / "mission.yml"), "NovelDemo", tmp_path / "brain")

    assert (tmp_path / "brain" / "project_state_contract.yml").is_file()
    assert (tmp_path / "brain" / "project_fact_events.jsonl").is_file()
    assert (tmp_path / "brain" / "project_fact_snapshot.yml").is_file()

    phase = build_project_plan(tmp_path / "brain", tmp_path / "plan")
    assert phase["state_contract"]["contract_ref"] == "project_state_contract.yml"
    assert "project_fact_snapshot.yml" in phase["must_read_artifacts"]


def test_acceptance_applies_valid_state_transition_proposal(tmp_path: Path) -> None:
    build_project_brain(_mission(tmp_path / "mission.yml"), "NovelDemo", tmp_path / "brain")
    phase_path = _phase(tmp_path / "brain")
    evidence = tmp_path / "evidence"
    _proposal(
        evidence,
        {
            "event_type": "create",
            "target_kind": "entity",
            "target_type": "character",
            "target_id": "hero",
            "to_status": "dead",
            "evidence_refs": ["chapter_010.md"],
        },
    )

    result = accept_phase(phase_path, evidence, tmp_path / "accepted")
    snapshot = load_project_fact_snapshot(tmp_path / "brain")

    assert result["accepted"] is True
    assert result["state_transition_status"]["applied"] is True
    assert snapshot["project"] == "NovelDemo"
    assert snapshot["entities"]["character"]["hero"]["status"] == "dead"


def test_managed_project_brain_acceptance_refreshes_knowledge_shards(tmp_path: Path) -> None:
    brain = tmp_path / "projects" / "NovelDemo" / "project_brain"
    brain.mkdir(parents=True)
    build_project_brain(_mission(tmp_path / "mission.yml"), "NovelDemo", brain)
    phase_path = _phase(brain)
    evidence = tmp_path / "evidence"
    _proposal(
        evidence,
        {
            "event_type": "create",
            "target_kind": "entity",
            "target_type": "character",
            "target_id": "rag_hero",
            "to_status": "dead",
            "evidence_refs": ["chapter_010.md"],
        },
    )

    result = accept_phase(phase_path, evidence, tmp_path / "accepted")

    assert result["accepted"] is True
    assert result["knowledge_sync"]["status"] == "SYNCED"
    assert result["knowledge_sync"]["namespaces"] == [
        "project.NovelDemo",
        "domain.longform_narrative",
    ]


def test_acceptance_blocks_invalid_state_transition(tmp_path: Path) -> None:
    build_project_brain(_mission(tmp_path / "mission.yml"), "NovelDemo", tmp_path / "brain")
    phase_path = _phase(tmp_path / "brain")
    evidence = tmp_path / "evidence"
    _proposal(
        evidence,
        {
            "event_type": "create",
            "target_kind": "entity",
            "target_type": "character",
            "target_id": "hero",
            "to_status": "dead",
            "evidence_refs": ["chapter_010.md"],
        },
    )
    accept_phase(phase_path, evidence, tmp_path / "accepted_1")

    evidence_2 = tmp_path / "evidence_2"
    _proposal(
        evidence_2,
        {
            "event_type": "create",
            "target_kind": "entity",
            "target_type": "character",
            "target_id": "hero",
            "to_status": "active",
            "evidence_refs": ["chapter_011.md"],
        },
    )

    result = accept_phase(phase_path, evidence_2, tmp_path / "accepted_2")
    snapshot = load_project_fact_snapshot(tmp_path / "brain")

    assert result["accepted"] is False
    assert result["state_transition_status"]["valid"] is False
    assert "project_fact_state_validated" in result["missing_evidence"]
    assert snapshot["entities"]["character"]["hero"]["status"] == "dead"


def test_contract_compiler_selects_non_novel_presets() -> None:
    templates = load_project_state_templates(ROOT)
    algorithm = compile_project_state_contract(
        {"project": "AlgoDemo", "task_type": "algorithm_research", "user_goal": "Build an algorithm prototype"},
        domain_presets=templates,
    )
    modeling = compile_project_state_contract(
        {"project": "ModelApp", "task_type": "product", "user_goal": "Build a modeling app with asset pipeline"},
        domain_presets=templates,
    )

    assert algorithm["selected_preset"] == "algorithm_prototype_project"
    assert "experiment" in algorithm["entity_types"]
    assert modeling["selected_preset"] == "modeling_app_project"
    assert "schema" in modeling["entity_types"]


def test_crown_of_ash_style_request_selects_epic_chronicle_preset() -> None:
    templates = load_project_state_templates(ROOT)
    contract = compile_project_state_contract(
        {
            "project": "Crown_of_Ash",
            "task_type": "creative_longform",
            "user_goal": "Generate a Crown of Ash epic chronicle with worldbuilding, branch timelines, and saga arcs.",
            "intent_summary": "史诗级世界观编年史与超长篇生成任务",
        },
        domain_presets=templates,
    )

    assert contract["selected_preset"] == "epic_chronicle_project"
    assert "timeline_branch" in contract["entity_types"]
    assert "cosmic_force" in contract["entity_types"]
    assert "power_stage" in contract["entity_types"]
    assert "chronology" in contract["dimensions"]
    assert contract["status_sequences"]["power_stage"][-1] == "spent"


def test_epic_chronicle_echo_requires_source_branch() -> None:
    templates = load_project_state_templates(ROOT)
    contract = compile_project_state_contract(
        {"project": "Crown_of_Ash", "task_type": "creative_longform", "user_goal": "epic chronicle"},
        domain_presets=templates,
    )
    result = validate_state_transition_proposal(
        contract,
        {"entities": {}, "artifacts": {}},
        {
            "events": [
                {
                    "event_type": "echo",
                    "target_kind": "entity",
                    "target_type": "timeline_event",
                    "target_id": "alicia-awakening",
                    "to_status": "active",
                    "evidence_refs": ["大纲/01_平行时间线与余震共鸣.md"],
                    "facts": {},
                }
            ]
        },
        required=True,
    )

    assert result["valid"] is False
    assert "facts.source_branch_id" in result["errors"][0]


def test_state_template_candidate_lifecycle(tmp_path: Path) -> None:
    candidate = build_state_template_candidate(
        tmp_path,
        name="video-asset-retirement",
        purpose="Retain asset retirement rules for video projects.",
        evidence_refs=["phase_2"],
        proposed_changes={"add_invariant": "retired_asset_cannot_be_referenced"},
    )
    approved = transition_state_template_candidate(tmp_path, candidate["id"], "approved")
    staged = transition_state_template_candidate(tmp_path, candidate["id"], "staging")
    validated = transition_state_template_candidate(tmp_path, candidate["id"], "validated")
    active = transition_state_template_candidate(tmp_path, candidate["id"], "active")

    assert approved["status"] == "approved"
    assert staged["status"] == "staging"
    assert validated["status"] == "validated"
    assert active["status"] == "active"
    with pytest.raises(ValueError):
        transition_state_template_candidate(tmp_path, candidate["id"], "validated")
