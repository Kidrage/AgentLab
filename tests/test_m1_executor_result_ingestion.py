from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.executors.phase_connector import ingest_phase_executor_result
from agent_runtime.executors.task_packet import create_task_packet


def _phase(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "project": "DemoProject",
                "phase_id": "phase_001",
                "goal": "Write unit tests for result ingestion",
                "outputs": ["test_file.py"],
                "acceptance_criteria": ["tests_pass"],
                "evidence_required": ["evidence.yml"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _executor_result_dir(path: Path) -> Path:
    path.mkdir()
    result = {
        "executor_result": {
            "packet_id": "DemoProject_phase_001_task",
            "executor_type": "claude_code_handoff",
            "summary": "Mock task execution succeeded.",
            "changed_files": ["tests/test_file.py"],
            "artifacts": ["evidence.yml"],
            "commands_run": ["pytest tests/test_file.py"],
            "tests_run": ["pytest"],
            "test_results": {"passed": True},
            "risks": [],
            "unresolved_issues": [],
            "evidence_paths": ["/tmp/result/evidence.yml"],
            "proposed_next_action": "Proceed to next phase",
        }
    }
    (path / "executor_result.yml").write_text(yaml.safe_dump(result), encoding="utf-8")
    (path / "evidence.yml").write_text("passed: true\n", encoding="utf-8")
    return path


def test_executor_result_ingestion(tmp_path: Path) -> None:
    phase_plan = _phase(tmp_path / "phase_plan.yml")
    packet = create_task_packet(phase_plan, "claude_code_handoff", tmp_path / "packet")

    result_dir = _executor_result_dir(tmp_path / "result")
    ingest_dir = tmp_path / "ingest"

    report = ingest_phase_executor_result(result_dir, tmp_path / "packet" / "task_packet.yml", ingest_dir)

    # Assertions
    assert report["phase_id"] == "phase_001"
    assert report["result_status"] == "PASS"
    assert report["changed_files"] == ["tests/test_file.py"]
    assert report["artifacts"] == ["evidence.yml"]
    assert report["accepted_without_review"] is False
    assert (ingest_dir / "ingested_result.yml").is_file()
    assert (ingest_dir / "phase_evidence" / "evidence_ledger.yml").is_file()

    loaded = yaml.safe_load((ingest_dir / "ingested_result.yml").read_text(encoding="utf-8"))
    assert loaded["changed_files"] == ["tests/test_file.py"]
    assert loaded["artifacts"] == ["evidence.yml"]
    assert loaded["phase_acceptance"]["verdict"] == "PASS"



