"""Audio artifact contracts for S9 mock-first perception."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .media_artifact import HUMAN_REVIEW_RISK, write_contract


def write_audio_contract(
    *,
    input_artifact: str,
    out_dir: Path,
    duration: float,
    observations: list[str],
    transcript: str,
    features: dict[str, Any],
    summary: str,
    evidence_artifacts: list[str],
    confidence: str,
    mock: bool,
) -> Path:
    if not mock:
        raise ValueError("audio contracts require --mock unless a reviewed backend is configured")
    data = {
        "input_artifact": input_artifact,
        "duration": duration,
        "observations": observations,
        "transcript": transcript,
        "features": features,
        "summary": summary,
        "evidence_artifacts": evidence_artifacts,
        "model_or_tool": "mock_audio_contract",
        "confidence": confidence,
        "risk": HUMAN_REVIEW_RISK,
    }
    return write_contract(out_dir, "audio_result.yml", data)
