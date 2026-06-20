from __future__ import annotations

from pathlib import Path
import yaml

from agent_runtime.recovery.replanning import replan_phase


def recover_failed_phase(
    project_brain_dir: Path,
    phase_id: str,
    acceptance_result_path: Path,
    out_dir: Path,
) -> dict:
    """Read phase acceptance outcome, runs recovery algorithms, and writes the replanning plan."""
    if not acceptance_result_path.exists():
        raise FileNotFoundError(f"acceptance result path does not exist: {acceptance_result_path}")
        
    acceptance_result = yaml.safe_load(acceptance_result_path.read_text(encoding="utf-8")) or {}
    
    # Run replanning
    replan_report = replan_phase(
        acceptance_result=acceptance_result,
        project_brain_dir=project_brain_dir,
        out_dir=out_dir,
    )
    
    return replan_report
