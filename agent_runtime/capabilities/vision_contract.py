"""Vision artifact contracts for S9 mock-first perception."""

from __future__ import annotations

from pathlib import Path

from .media_artifact import HUMAN_REVIEW_RISK, write_contract


def write_vision_contract(
    *,
    input_artifact: str,
    out_dir: Path,
    observations: list[str],
    summary: str,
    evidence_artifacts: list[str],
    confidence: str,
    mock: bool,
) -> Path:
    if not mock:
        raise ValueError("vision contracts require --mock unless a reviewed backend is configured")
    data = {
        "input_artifact": input_artifact,
        "modality": "vision",
        "observations": observations,
        "summary": summary,
        "evidence_artifacts": evidence_artifacts,
        "model_or_tool": "mock_vision_contract",
        "confidence": confidence,
        "risk": HUMAN_REVIEW_RISK,
    }
    return write_contract(out_dir, "vision_result.yml", data)
