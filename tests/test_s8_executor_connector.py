from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

import yaml
from typer.testing import CliRunner

from agent_runtime.executors.phase_connector import ingest_phase_executor_result, review_phase_executor_result
from agent_runtime.executors.task_packet import create_task_packet
from run_task import app


def _phase(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "project": "RepoRepair",
                "phase_id": "phase_2_patch_packet",
                "goal": "Create patch task packet and execute safely",
                "outputs": ["task_packet", "test_evidence", "acceptance_report"],
                "acceptance_criteria": ["all_required_outputs_have_evidence", "no_policy_bypass_or_external_auto_execution"],
                "evidence_required": ["task_packet.yml", "test_evidence.yml", "acceptance_report.yml"],
                "human_decision_points": ["approve_phase_close"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _result_dir(path: Path, changed_files: list[str] | None = None) -> Path:
    path.mkdir()
    envelope = {
        "task_id": "phase_2_patch_packet",
        "provider_id": "agentlab.mock_patch",
        "source": "mock_executor",
        "status": "PASS",
        "changed_files": changed_files or ["tests/test_s8_executor_connector.py"],
        "claimed_tests": ["pytest tests/test_s8_executor_connector.py"],
        "output_artifacts": ["test_evidence.yml"],
        "summary": "Mock phase execution result",
        "safety_attestation": {"secrets_exposed": False},
    }
    (path / "execution_result_envelope.yml").write_text(yaml.safe_dump(envelope), encoding="utf-8")
    (path / "test_evidence.yml").write_text("passed: true\n", encoding="utf-8")
    return path


def test_task_packet_defaults_are_approval_safe(tmp_path: Path) -> None:
    packet = create_task_packet(_phase(tmp_path / "phase.yml"), "cline", tmp_path / "packet")
    assert packet["task_packet"]["rollback_required"] is True
    assert packet["connector_contract"]["requires_human_approval"] is True
    assert packet["connector_contract"]["auto_execute"] is False


def test_result_ingest_collects_evidence_and_does_not_accept(tmp_path: Path) -> None:
    packet = create_task_packet(_phase(tmp_path / "phase.yml"), "mock_executor", tmp_path / "packet")
    assert packet["connector_contract"]["auto_execute"] is True
    result = ingest_phase_executor_result(_result_dir(tmp_path / "result"), tmp_path / "packet" / "task_packet.yml", tmp_path / "ingest")
    assert result["accepted_without_review"] is False
    assert result["diff_report"]["verdict"] == "PASS"
    assert (tmp_path / "ingest" / "phase_evidence" / "evidence_ledger.yml").is_file()
    assert (tmp_path / "ingest" / "executor_result_ledger.yml").is_file()


def test_executor_review_uses_phase_acceptance(tmp_path: Path) -> None:
    phase = _phase(tmp_path / "phase.yml")
    create_task_packet(phase, "mock_executor", tmp_path / "packet")
    ingest_phase_executor_result(_result_dir(tmp_path / "result"), tmp_path / "packet" / "task_packet.yml", tmp_path / "ingest")
    review = review_phase_executor_result(tmp_path / "ingest" / "ingested_result.yml", phase, tmp_path / "review")
    assert review["accepted"] is True
    assert review["external_auto_execution_allowed"] is False


def test_forbidden_changed_file_blocks_review(tmp_path: Path) -> None:
    phase = _phase(tmp_path / "phase.yml")
    create_task_packet(phase, "mock_executor", tmp_path / "packet")
    result = ingest_phase_executor_result(_result_dir(tmp_path / "result", [".env"]), tmp_path / "packet" / "task_packet.yml", tmp_path / "ingest")
    assert result["diff_report"]["verdict"] == "FAIL"
    review = review_phase_executor_result(tmp_path / "ingest" / "ingested_result.yml", phase, tmp_path / "review")
    assert review["accepted"] is False


def test_s8_cli_packet_ingest_review(tmp_path: Path) -> None:
    runner = CliRunner()
    phase = _phase(tmp_path / "phase.yml")
    packet = runner.invoke(app, ["executor-task-create", "--phase-plan", str(phase), "--executor-type", "mock_executor", "--out", str(tmp_path / "packet")])
    assert packet.exit_code == 0, packet.output
    ingest = runner.invoke(app, ["executor-result-ingest", "--result-dir", str(_result_dir(tmp_path / "result")), "--task-packet", str(tmp_path / "packet" / "task_packet.yml"), "--out", str(tmp_path / "ingest")])
    assert ingest.exit_code == 0, ingest.output
    review = runner.invoke(app, ["executor-review", "--ingested-result", str(tmp_path / "ingest" / "ingested_result.yml"), "--phase-plan", str(phase), "--out", str(tmp_path / "review")])
    assert review.exit_code == 0, review.output
