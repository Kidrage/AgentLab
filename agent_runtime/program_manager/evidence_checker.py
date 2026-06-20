from __future__ import annotations

from pathlib import Path
from typing import Any


def check_evidence(phase_plan: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    """Scan the evidence directory and check if all required evidence items are present."""
    plan = phase_plan.get("task_packet") or phase_plan
    required_evidence = plan.get("evidence_required") or []

    evidence_files = []
    if evidence_dir.exists() and evidence_dir.is_dir():
        evidence_files = sorted(
            str(path.relative_to(evidence_dir))
            for path in evidence_dir.glob("**/*")
            if path.is_file()
        )

    missing_evidence = []
    for expected in required_evidence:
        # Match if expected string is exactly equal or if it matches the name of any file in evidence_files
        found = False
        for file in evidence_files:
            if file == expected or expected in file or Path(file).name == expected:
                found = True
                break
        if not found:
            missing_evidence.append(expected)

    has_missing = len(missing_evidence) > 0

    return {
        "required_evidence": required_evidence,
        "evidence_files": evidence_files,
        "missing_evidence": missing_evidence,
        "has_missing": has_missing,
    }
