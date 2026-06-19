from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.program_manager.acceptance_contract import build_acceptance_contract


def accept_phase(phase_plan_path: Path, evidence_dir: Path, out_dir: Path) -> dict:
    phase_plan = yaml.safe_load(phase_plan_path.read_text(encoding="utf-8")) or {}
    contract = build_acceptance_contract(phase_plan)
    evidence_files = sorted(path.name for path in evidence_dir.glob("**/*") if path.is_file()) if evidence_dir.exists() else []
    missing = []
    for expected in contract["required_evidence"]:
        if not any(name == expected or expected in name for name in evidence_files):
            missing.append(expected)
    verdict = "PASS" if not missing and evidence_files else "NEEDS_EVIDENCE"
    result = {
        "phase_id": contract["phase_id"],
        "verdict": verdict,
        "accepted": verdict == "PASS",
        "missing_evidence": missing,
        "evidence_files": evidence_files,
        "human_approval_required": contract["human_approval_required"],
        "policy": {
            "external_auto_execution_allowed": False,
            "phase_close_requires_evidence": True,
        },
    }
    atomic_write_yaml(out_dir / "phase_acceptance.yml", result)
    return result
