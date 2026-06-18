from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_runtime.brain.acceptance_builder import build_acceptance_gates
from agent_runtime.brain.artifact_builder import build_required_artifacts
from agent_runtime.brain.assumption_builder import build_assumptions_and_unknowns
from agent_runtime.brain.domain_signals import classify_task_type
from agent_runtime.brain.domain_workflows import load_domain_workflow_templates, select_domain_workflow
from agent_runtime.brain.mission_contract import MissionTaskType, load_mission_contract, validate_mission_contract
from agent_runtime.brain.risk_builder import build_risks
from agent_runtime.brain.task_compiler import compile_task_packet


ROOT = Path(__file__).resolve().parents[1]


def _artifact_names(result) -> set[str]:
    return {artifact.name for artifact in result.contract.required_artifacts}


def _gate_text(result) -> str:
    return "\n".join(gate.description.lower() for gate in result.contract.acceptance_gates)


def _risk_ids(result) -> set[str]:
    return {risk.risk_id for risk in result.contract.risks}


def _risk_text(result) -> str:
    return "\n".join(risk.risk_id + " " + risk.description for risk in result.contract.risks).lower()


def _capabilities(result) -> set[str]:
    return {capability.capability for capability in result.contract.required_capabilities}


def test_artifact_builder_merges_template_and_prompt_specific_artifacts() -> None:
    classification = classify_task_type("Fix repo CI and tests in GitHub Actions")
    template = select_domain_workflow(classification.task_type.value, classification.domain_signals)
    artifacts = build_required_artifacts(
        classification.task_type,
        "Fix repo CI and tests in GitHub Actions",
        template,
    )
    names = [artifact.name for artifact in artifacts]
    assert "test_results.md" in names
    assert "ci_results.md" in names
    assert len(names) == len(set(names))
    assert names.index("test_results.md") < names.index("ci_results.md")


def test_acceptance_builder_adds_prompt_specific_gates() -> None:
    classification = classify_task_type("Fix repo CI and tests in GitHub Actions")
    template = select_domain_workflow(classification.task_type.value, classification.domain_signals)
    gates = build_acceptance_gates(
        classification.task_type,
        "Fix repo CI and tests in GitHub Actions",
        template,
        ["repo_inspection", "code_edit", "test_execution"],
    )
    text = "\n".join(gate.description.lower() for gate in gates)
    assert "ci status" in text or "local equivalent" in text
    assert "test command output" in text
    assert len(text) > 100


def test_assumption_builder_adds_missing_repo_unknown() -> None:
    assumptions, unknowns, cards = build_assumptions_and_unknowns(
        "Fix the failing function and run tests.",
        "coding",
        ["primary=coding score=2"],
        ["repo_inspection", "code_edit", "test_execution"],
    )
    assert assumptions
    assert any("repository" in item.lower() or "path" in item.lower() for item in unknowns)
    assert any(card["kind"] == "missing_context" for card in cards)


def test_research_prompt_adds_freshness_and_citation_risks() -> None:
    result = compile_task_packet(
        "Research the latest company market competitors for a spatial audio startup and include sources."
    )
    assert result.contract.task_type in {MissionTaskType.RESEARCH, MissionTaskType.BUSINESS}
    assert result.selected_template_id in {"research_investigation", "business_strategy"}
    text = _gate_text(result)
    risks = _risk_text(result)
    assert "freshness" in text or "access dates" in text
    assert "no fake citations" in text or "source citations" in text
    assert "stale source" in risks
    assert "fake citation" in risks


def test_multimodal_prompt_adds_visual_risks_and_gates() -> None:
    result = compile_task_packet(
        "Analyze this screenshot image and video, extract text, and label visual uncertainty."
    )
    assert result.contract.task_type == MissionTaskType.MULTIMODAL
    assert result.selected_template_id == "multimodal_vision"
    assert "vision_observations.yml" in _artifact_names(result)
    assert "provenance" in _gate_text(result) or "input artifact" in _gate_text(result)
    assert "visual hallucination" in _risk_text(result)


def test_audio_prompt_adds_audio_specific_risks() -> None:
    result = compile_task_packet(
        "Analyze spatial audio music stems for HRTF, binaural balance, loudness, and listening notes."
    )
    assert result.contract.task_type == MissionTaskType.AUDIO_MUSIC
    assert result.selected_template_id == "audio_music"
    assert "audio_analysis_report.md" in _artifact_names(result)
    assert "objective measurements" in _gate_text(result)
    assert "subjective evaluation" in _risk_text(result)
    assert "playback environment" in _risk_text(result)


def test_local_ops_prompt_requires_human_approval() -> None:
    result = compile_task_packet(
        "Delete duplicate local files in this folder after cleanup dry-run and rollback plan."
    )
    assert result.contract.task_type == MissionTaskType.LOCAL_OPS
    assert result.selected_template_id == "local_ops_automation"
    assert result.contract.human_approval.required is True
    assert "dry_run_report.md" in _artifact_names(result)
    assert "rollback_plan.md" in _artifact_names(result)
    assert "dry-run" in _gate_text(result)
    assert "destructive change" in _risk_text(result)


def test_compiled_contract_contains_template_note_and_risks() -> None:
    result = compile_task_packet(
        "Fix a bug in this repository, update docs, run tests, and summarize the patch."
    )
    assert validate_mission_contract(result.contract) == []
    assert any(note == "compiled_by: task_compiler_s1_cdef" for note in result.contract.notes)
    assert any(note == f"domain_workflow_template: {result.selected_template_id}" for note in result.contract.notes)
    assert any(note == "deterministic_compiler: true" for note in result.contract.notes)
    assert result.contract.risks
    assert any("regression_risk" in risk_id for risk_id in _risk_ids(result))


def test_existing_s1_b_tests_still_pass() -> None:
    result = compile_task_packet(
        "Fix the pytest failure in this repository, patch the bug, run tests, and summarize changed files.",
        task_id="coding_bug",
        project="AgentLab",
    )
    assert result.contract.task_type in {MissionTaskType.CODING, MissionTaskType.DEBUGGING}
    assert {"repo_inspection", "code_edit", "test_execution"} <= _capabilities(result)
    assert {"patch_plan.md", "test_results.md", "acceptance_report.md"} <= _artifact_names(result)
    assert "primary=" in result.domain_signals[0]


def test_cli_summary_includes_selected_template(tmp_path: Path) -> None:
    output = tmp_path / "mission_contract.yml"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "compile_mission_contract.py"),
            "--task-id",
            "demo_s1_cdef",
            "--project",
            "AgentLab",
            "--prompt",
            "Research the latest market competitors for a spatial audio speaker startup and produce a sourced report.",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["selected_template_id"] in {"research_investigation", "business_strategy"}
    assert summary["required_capabilities_count"] >= 3
    assert output.exists()
    contract = load_mission_contract(output)
    assert validate_mission_contract(contract) == []


def test_text_integrity_guards_include_s1_cdef_files() -> None:
    from scripts import audit_text_integrity
    import importlib.util

    repo_spec = importlib.util.spec_from_file_location(
        "repository_text_integrity_s1cdef",
        ROOT / "tests" / "test_repository_text_integrity.py",
    )
    assert repo_spec and repo_spec.loader
    repository_text_integrity = importlib.util.module_from_spec(repo_spec)
    sys.modules["repository_text_integrity_s1cdef"] = repository_text_integrity
    repo_spec.loader.exec_module(repository_text_integrity)

    spec = importlib.util.spec_from_file_location(
        "check_remote_raw_integrity_s1cdef",
        ROOT / "scripts" / "check_remote_raw_integrity.py",
    )
    assert spec and spec.loader
    remote_module = importlib.util.module_from_spec(spec)
    sys.modules["check_remote_raw_integrity_s1cdef"] = remote_module
    spec.loader.exec_module(remote_module)

    expected = {
        "config/domain_workflow_templates.yml": 120,
        "config/artifact_contract_templates.yml": 20,
        "config/acceptance_gate_templates.yml": 20,
        "agent_runtime/brain/domain_workflows.py": 150,
        "agent_runtime/domain_workflows/models.py": 60,
        "agent_runtime/domain_workflows/loader.py": 100,
        "agent_runtime/domain_workflows/matcher.py": 50,
        "agent_runtime/domain_workflows/planner.py": 120,
        "agent_runtime/domain_workflows/renderer.py": 70,
        "agent_runtime/brain/risk_builder.py": 100,
        "agent_runtime/brain/assumption_builder.py": 120,
        "tests/test_domain_workflow_templates.py": 100,
        "tests/test_task_compiler_domain_refinement.py": 160,
        "tests/test_s2_domain_workflow_templates.py": 100,
        "tests/test_s2_workflow_planner.py": 120,
        "tests/test_s2_workflow_cli.py": 40,
        "docs/S2_DOMAIN_WORKFLOW_TEMPLATES.md": 80,
        "docs/DOMAIN_WORKFLOW_TEMPLATES.md": 80,
    }
    for path, minimum in expected.items():
        assert audit_text_integrity.MIN_LINE_COUNTS[path] >= minimum
        assert repository_text_integrity.MIN_LINE_COUNTS[path] >= minimum
        assert path in remote_module.CRITICAL_FILES
        assert remote_module.MIN_LINES[path] >= minimum


def test_no_dirty_untracked_files_are_staged() -> None:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    staged = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    forbidden = {
        "AGENTS.md",
        "acceptance_runs/stabilization/text_integrity_audit.json",
        "acceptance_runs/stabilization/text_integrity_audit.md",
    }
    assert not (staged & forbidden)


def test_direct_risk_builder_unknown_fallback() -> None:
    risks = build_risks("Please handle this.", "unknown", ["human_approval"], None)
    assert "ambiguous_goal_risk" in risks
    assert "capability_gap_risk" in risks
