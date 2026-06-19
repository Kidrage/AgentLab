"""Document artifact contracts for S9 mock-first extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .media_artifact import HUMAN_REVIEW_RISK, write_contract


def write_document_contract(
    *,
    input_artifact: str,
    out_dir: Path,
    pages: int,
    extracted_text: str,
    tables: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    citations: list[str],
    evidence_artifacts: list[str],
    confidence: str,
    mock: bool,
) -> Path:
    if not mock:
        raise ValueError("document contracts require --mock unless a reviewed backend is configured")
    data = {
        "input_artifact": input_artifact,
        "pages": pages,
        "extracted_text": extracted_text,
        "tables": tables,
        "figures": figures,
        "citations": citations,
        "evidence_artifacts": evidence_artifacts,
        "model_or_tool": "mock_document_contract",
        "confidence": confidence,
        "risk": HUMAN_REVIEW_RISK,
    }
    return write_contract(out_dir, "document_result.yml", data)
