from __future__ import annotations

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.program_manager.context_compressor import write_phase_summary, compact_project_memory


def test_write_phase_summary(tmp_path: Path):
    summary_data = {
        "verdict": "PASS",
        "outputs": ["main.py", "README.md"],
        "risks": ["unresolved_auth_dependency"],
        "next_action": "next_phase",
    }
    
    # Generate summary
    out_file = write_phase_summary(tmp_path, "phase_01", summary_data)
    
    assert out_file.is_file()
    assert (tmp_path / "phase_summaries" / "phase_01.md").is_file()
    assert (tmp_path / "phase_summaries" / "phase_01_summary.md").is_file()
    
    content = out_file.read_text(encoding="utf-8")
    assert "# Phase Summary: phase_01" in content
    assert "verdict: PASS" in content
    assert "outputs: main.py, README.md" in content


def test_compact_project_memory(tmp_path: Path):
    decision_log_path = tmp_path / "decision_log.yml"
    
    # Write duplicate decision entries
    duplicate_data = {
        "entries": [
            {"decision_id": "dec_1", "outcome": "approved"},
            {"decision_id": "dec_1", "outcome": "approved"},
            {"decision_id": "dec_2", "outcome": "rejected"},
        ]
    }
    yaml.dump(duplicate_data, decision_log_path.open("w", encoding="utf-8"))
    
    res = compact_project_memory(tmp_path)
    assert res["status"] == "memory_compacted"
    
    # Check that duplicates were removed
    compacted = yaml.safe_load(decision_log_path.read_text(encoding="utf-8"))
    assert len(compacted["entries"]) == 2
    assert compacted["entries"][0]["decision_id"] == "dec_1"
    assert compacted["entries"][1]["decision_id"] == "dec_2"
