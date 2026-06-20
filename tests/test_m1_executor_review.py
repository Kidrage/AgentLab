from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.executors.phase_connector import ingest_phase_executor_result, review_phase_executor_result
from agent_runtime.executors.task_packet import create_task_packet


def _phase(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "project": "DemoProject",
                "phase_id": "phase_001",
                "goal": "Write unit tests for executor review",
                "outputs": ["test_file.py"],
                "acceptance_criteria": ["all_required_outputs_have_evidence"],
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
            "test_results": {"passed": True},
        }
    }
    (path / "executor_result.yml").write_text(yaml.safe_dump(result), encoding="utf-8")
    # write real evidence.yml file to make acceptance pass
    (path / "evidence.yml").write_text("passed: true\n", encoding="utf-8")
    return path


def test_executor_review_and_acceptance(tmp_path: Path) -> None:
    phase_plan = _phase(tmp_path / "phase_plan.yml")
    create_task_packet(phase_plan, "claude_code_handoff", tmp_path / "packet")
    
    result_dir = _executor_result_dir(tmp_path / "result")
    ingest_dir = tmp_path / "ingest"
    
    ingest_phase_executor_result(result_dir, tmp_path / "packet" / "task_packet.yml", ingest_dir)
    
    review_dir = tmp_path / "review"
    review = review_phase_executor_result(ingest_dir / "ingested_result.yml", phase_plan, review_dir)
    
    # Assertions
    assert review["phase_id"] == "phase_001"
    assert review["executor_result_status"] == "PASS"
    assert review["diff_verdict"] == "PASS"
    assert review["phase_acceptance"]["verdict"] == "PASS"
    assert review["accepted"] is True
    assert (review_dir / "executor_phase_review.yml").is_file()
