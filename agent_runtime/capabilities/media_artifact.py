"""Shared media artifact contract helpers for S9."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .result_verifier import require_evidence, require_non_empty


HUMAN_REVIEW_RISK = "human_review_required"


def write_contract(out_dir: Path, filename: str, data: dict[str, Any]) -> Path:
    require_non_empty(data.get("confidence"), "confidence")
    require_evidence(list(data.get("evidence_artifacts") or []))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
