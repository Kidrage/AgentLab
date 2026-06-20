import pytest
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.executors.task_packet import create_task_packet


def _phase(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "project": "DemoProject",
                "phase_id": "phase_001",
                "goal": "Write unit tests for executor policy",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_unauthorized_executor_blocks(tmp_path: Path) -> None:
    phase_plan = _phase(tmp_path / "phase_plan.yml")
    out_dir = tmp_path / "packet"
    
    # unauthorized executor should raise ValueError
    with pytest.raises(ValueError) as exc:
        create_task_packet(phase_plan, "evil_hacker_executor", out_dir)
    assert "Unauthorized executor type" in str(exc.value)


def test_authorized_executor_allowed(tmp_path: Path) -> None:
    phase_plan = _phase(tmp_path / "phase_plan.yml")
    out_dir = tmp_path / "packet"
    
    # Authorized executors
    for executor in ["mock_executor", "claude_code_handoff", "hermes_handoff", "codex_handoff", "manual_patch_submitter"]:
        packet = create_task_packet(phase_plan, executor, out_dir / executor)
        assert packet["task_packet"]["executor_type"] == executor
