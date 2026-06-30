from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.executors.phase_connector import ingest_phase_executor_result, review_phase_executor_result
from agent_runtime.executors.task_packet import create_task_packet


FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "executor_results"


def _phase(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "project": "RepoRepair",
                "phase_id": "phase_2_patch_packet",
                "goal": "Verify external CLI executor result fixtures",
                "outputs": ["test_evidence", "acceptance_report"],
                "allowed_files": ["tests/test_executor_result_contract_fixtures.py"],
                "forbidden_files": [".env", ".git/**"],
                "acceptance_criteria": ["executor_result_contract_valid", "evidence_consumed"],
                "evidence_required": ["task_packet.yml", "test_evidence.yml", "acceptance_report.yml"],
                "human_decision_points": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("fixture_id", "executor_type", "expected_status"),
    [
        ("codex_local_pass", "codex_handoff", "PASS"),
        ("claude_code_pass", "claude_code_handoff", "PASS"),
        ("hermes_pass", "hermes_handoff", "PASS"),
    ],
)
def test_external_cli_executor_result_fixtures_pass_contract_and_acceptance(
    tmp_path: Path,
    fixture_id: str,
    executor_type: str,
    expected_status: str,
) -> None:
    phase = _phase(tmp_path / "phase.yml")
    create_task_packet(phase, executor_type, tmp_path / "packet")

    report = ingest_phase_executor_result(
        FIXTURE_ROOT / fixture_id,
        tmp_path / "packet" / "task_packet.yml",
        tmp_path / "ingest",
    )
    review = review_phase_executor_result(tmp_path / "ingest" / "ingested_result.yml", phase, tmp_path / "review")

    assert report["result_status"] == expected_status
    assert report["contract_validation"]["valid"] is True
    assert report["phase_acceptance"]["accepted"] is True
    assert report["phase_acceptance"]["executor_evidence_status"]["has_supporting_evidence"] is True
    assert review["accepted"] is True
    assert review["external_auto_execution_allowed"] is False


def test_external_cli_executor_failure_fixture_cannot_close_phase(tmp_path: Path) -> None:
    phase = _phase(tmp_path / "phase.yml")
    create_task_packet(phase, "human_contractor", tmp_path / "packet")

    report = ingest_phase_executor_result(
        FIXTURE_ROOT / "generic_contractor_fail",
        tmp_path / "packet" / "task_packet.yml",
        tmp_path / "ingest",
    )
    review = review_phase_executor_result(tmp_path / "ingest" / "ingested_result.yml", phase, tmp_path / "review")

    assert report["result_status"] == "FAIL"
    assert report["contract_validation"]["valid"] is True
    assert report["phase_acceptance"]["accepted"] is False
    assert report["phase_acceptance"]["verdict"] == "RETRY"
    assert review["accepted"] is False
