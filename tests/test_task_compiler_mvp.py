from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from agent_runtime.brain.mission_contract import (
    MissionTaskType,
    load_mission_contract,
    validate_mission_contract,
    write_mission_contract,
)
from agent_runtime.brain.task_compiler import (
    TaskCompilationError,
    compile_task_packet,
    compile_task_to_contract,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "task_compiler_inputs"


def _capabilities(contract) -> set[str]:
    return {item.capability for item in contract.required_capabilities}


def _artifacts(contract) -> set[str]:
    return {item.name for item in contract.required_artifacts}


def _gate_text(contract) -> str:
    return "\n".join(gate.description.lower() for gate in contract.acceptance_gates)


def _decision_text(result) -> str:
    return json.dumps(result.decision_cards, sort_keys=True).lower()


def test_compile_coding_prompt_to_contract() -> None:
    result = compile_task_packet(
        "Fix the pytest failure in this repository, patch the bug, run tests, and summarize changed files.",
        task_id="coding_bug",
        project="AgentLab",
    )
    contract = result.contract
    assert contract.task_type in {MissionTaskType.CODING, MissionTaskType.DEBUGGING}
    assert validate_mission_contract(contract) == []
    assert {"repo_inspection", "code_edit", "test_execution"} <= _capabilities(contract)
    assert {"patch_plan.md", "test_results.md", "acceptance_report.md"} <= _artifacts(contract)
    assert "primary=" in result.domain_signals[0]


def test_compile_research_prompt_requires_sources() -> None:
    result = compile_task_packet(
        "Research the current company market position, compare competitors, and include sources and citations.",
        task_id="research_company",
    )
    contract = result.contract
    assert contract.task_type in {MissionTaskType.RESEARCH, MissionTaskType.BUSINESS}
    assert {"web_search", "source_citation"} <= _capabilities(contract)
    gates = _gate_text(contract)
    assert "no fake citations" in gates or "invented" in gates
    assert "source" in gates
    assert any("source" in warning.lower() for warning in result.warnings)


def test_compile_creative_longform_prompt_requires_outline_first() -> None:
    result = compile_task_packet(
        "Write a novel chapter with characters, worldbuilding, outline, continuity tracking, and revision notes."
    )
    contract = result.contract
    assert contract.task_type == MissionTaskType.CREATIVE_LONGFORM
    artifacts = _artifacts(contract)
    assert "outline.md" in artifacts
    assert "continuity_ledger.md" in artifacts
    assert "revision_notes.md" in artifacts
    assert "outline" in _gate_text(contract)
    assert "direct final longform" in _gate_text(contract)


def test_compile_multimodal_prompt_detects_image_understanding() -> None:
    result = compile_task_packet(
        "Analyze this UI screenshot and video, extract visible text, and summarize visual issues."
    )
    contract = result.contract
    assert contract.task_type == MissionTaskType.MULTIMODAL
    capabilities = _capabilities(contract)
    assert "image_understanding" in capabilities
    assert "video_understanding" in capabilities
    assert "capability_gap" in _decision_text(result)
    assert contract.human_approval.required is True


def test_compile_audio_music_prompt() -> None:
    result = compile_task_packet(
        "Analyze spatial audio music stems for HRTF, binaural balance, loudness, mix problems, and validation notes."
    )
    contract = result.contract
    assert contract.task_type == MissionTaskType.AUDIO_MUSIC
    assert "audio_analysis" in _capabilities(contract)
    artifacts = _artifacts(contract)
    assert "audio_task_brief.md" in artifacts
    assert "input_asset_manifest.yml" in artifacts
    assert "listening_or_validation_notes.md" in artifacts


def test_compile_document_processing_prompt() -> None:
    result = compile_task_packet("Extract tables from a PDF document, parse content, summarize it, and quality check OCR.")
    contract = result.contract
    assert contract.task_type == MissionTaskType.DOCUMENT_PROCESSING
    artifacts = _artifacts(contract)
    assert "parsed_content.md" in artifacts
    assert "table_outputs/" in artifacts
    assert "quality_check.md" in artifacts


def test_compile_data_analysis_prompt() -> None:
    result = compile_task_packet("Analyze CSV and XLSX spreadsheet dataframes, clean data, create charts, and report statistics.")
    contract = result.contract
    assert contract.task_type == MissionTaskType.DATA_ANALYSIS
    assert {"spreadsheet_processing", "data_analysis"} <= _capabilities(contract)
    artifacts = _artifacts(contract)
    assert "data_profile.md" in artifacts
    assert "cleaning_log.md" in artifacts
    assert "findings_report.md" in artifacts


def test_compile_local_ops_requires_approval() -> None:
    result = compile_task_packet("Delete duplicate local files in this folder after dry-run and write a rollback plan.")
    contract = result.contract
    assert contract.task_type == MissionTaskType.LOCAL_OPS
    assert contract.human_approval.required is True
    gates = _gate_text(contract)
    assert "dry-run" in gates
    assert "rollback" in gates
    assert "path scope" in gates or "path-scope" in gates


def test_compile_unknown_prompt_is_safe() -> None:
    result = compile_task_packet("Please handle this.")
    contract = result.contract
    assert contract.task_type == MissionTaskType.UNKNOWN
    assert contract.unknowns
    assert contract.human_approval.required is True
    assert "human_approval" in _capabilities(contract)
    assert "clarification" in _decision_text(result)


def test_empty_prompt_returns_structured_error() -> None:
    with pytest.raises(TaskCompilationError) as excinfo:
        compile_task_packet("   ")
    assert excinfo.value.errors == [
        {"field": "user_prompt", "message": "user_prompt cannot be empty", "code": "required"}
    ]
    assert "Traceback" not in str(excinfo.value)


def test_yaml_roundtrip_compiled_contract(tmp_path: Path) -> None:
    contract = compile_task_to_contract(
        "Fix the pytest failure in this repository and produce an acceptance report.",
        task_id="roundtrip",
        project="AgentLab",
        output_dir=tmp_path,
    )
    path = tmp_path / "mission_contract.yml"
    assert path.exists()
    loaded = load_mission_contract(path)
    assert validate_mission_contract(loaded) == []
    assert loaded.mission_id == contract.mission_id
    before = path.read_text(encoding="utf-8")
    write_mission_contract(loaded, path)
    after = path.read_text(encoding="utf-8")
    assert before == after


def test_compiler_does_not_execute_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_subprocess(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("Task compiler must not execute subprocesses")

    def blocked_urlopen(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("Task compiler must not open network URLs")

    def blocked_socket(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("Task compiler must not open sockets")

    monkeypatch.setattr(subprocess, "run", blocked_subprocess)
    monkeypatch.setattr(subprocess, "Popen", blocked_subprocess)
    monkeypatch.setattr(urllib.request, "urlopen", blocked_urlopen)
    monkeypatch.setattr(socket, "create_connection", blocked_socket)
    result = compile_task_packet("Research a company with citations and note all sources.")
    assert result.contract.task_type in {MissionTaskType.RESEARCH, MissionTaskType.BUSINESS}


def test_cli_writes_contract(tmp_path: Path) -> None:
    output = tmp_path / "mission_contract.yml"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "compile_mission_contract.py"),
            "--task-id",
            "demo_cli",
            "--project",
            "AgentLab",
            "--prompt",
            "Fix the pytest failure in this repository and produce an acceptance report.",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["task_id"] == "demo_cli"
    assert summary["output_path"] == str(output)
    contract = load_mission_contract(output)
    assert validate_mission_contract(contract) == []


def test_examples_compile_successfully() -> None:
    paths = sorted(EXAMPLE_DIR.glob("*.txt"))
    assert {path.name for path in paths} == {
        "audio_music_analysis.txt",
        "coding_bug.txt",
        "creative_novel.txt",
        "data_spreadsheet.txt",
        "document_pdf.txt",
        "local_ops_cleanup.txt",
        "multimodal_screenshot.txt",
        "research_company.txt",
        "unknown_ambiguous.txt",
    }
    for path in paths:
        prompt = path.read_text(encoding="utf-8")
        result = compile_task_packet(prompt, task_id=path.stem, project="AgentLab")
        assert validate_mission_contract(result.contract) == [], path.name
        assert result.contract.required_artifacts, path.name
        assert result.contract.acceptance_gates, path.name


def test_text_integrity_guards_include_s1_b_files() -> None:
    from scripts import audit_text_integrity
    import importlib.util

    repo_spec = importlib.util.spec_from_file_location(
        "repository_text_integrity_s1b",
        ROOT / "tests" / "test_repository_text_integrity.py",
    )
    assert repo_spec and repo_spec.loader
    repository_text_integrity = importlib.util.module_from_spec(repo_spec)
    sys.modules["repository_text_integrity_s1b"] = repository_text_integrity
    repo_spec.loader.exec_module(repository_text_integrity)

    spec = importlib.util.spec_from_file_location(
        "check_remote_raw_integrity_s1b",
        ROOT / "scripts" / "check_remote_raw_integrity.py",
    )
    assert spec and spec.loader
    remote_module = importlib.util.module_from_spec(spec)
    sys.modules["check_remote_raw_integrity_s1b"] = remote_module
    spec.loader.exec_module(remote_module)

    expected = {
        "agent_runtime/brain/task_compiler.py": 180,
        "agent_runtime/brain/domain_signals.py": 80,
        "agent_runtime/brain/artifact_builder.py": 100,
        "agent_runtime/brain/acceptance_builder.py": 100,
        "tests/test_task_compiler_mvp.py": 160,
        "docs/TASK_COMPILER.md": 80,
        "scripts/compile_mission_contract.py": 80,
    }
    for path, minimum in expected.items():
        assert audit_text_integrity.MIN_LINE_COUNTS[path] >= minimum
        assert repository_text_integrity.MIN_LINE_COUNTS[path] >= minimum
        assert path in remote_module.CRITICAL_FILES
        assert remote_module.MIN_LINES[path] >= minimum
