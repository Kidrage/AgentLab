from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "review_policy.yml"


@dataclass
class ReviewPolicy:
    enabled: bool = True
    verdict_thresholds: dict[str, str] = field(default_factory=dict)
    required_artifacts: list[str] = field(default_factory=list)
    optional_artifacts: list[str] = field(default_factory=list)
    safety_checks: dict[str, bool] = field(default_factory=dict)
    forbidden_paths: list[str] = field(default_factory=list)
    high_risk_paths: list[str] = field(default_factory=list)
    required_report_sections: list[str] = field(default_factory=list)
    retry_handoff: dict[str, bool] = field(default_factory=dict)
    max_text_bytes: int = 65536

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewPolicy":
        raw = data.get("review_policy", data) if isinstance(data, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            enabled=raw.get("enabled", True) is True,
            verdict_thresholds=dict(raw.get("verdict_thresholds") or {}),
            required_artifacts=[str(item) for item in raw.get("required_artifacts") or []],
            optional_artifacts=[str(item) for item in raw.get("optional_artifacts") or []],
            safety_checks=dict(raw.get("safety_checks") or {}),
            forbidden_paths=[str(item) for item in raw.get("forbidden_paths") or []],
            high_risk_paths=[str(item) for item in raw.get("high_risk_paths") or []],
            required_report_sections=[str(item) for item in raw.get("required_report_sections") or []],
            retry_handoff=dict(raw.get("retry_handoff") or {}),
            max_text_bytes=int(raw.get("max_text_bytes") or 65536),
        )


def load_review_policy(path: Path | None = None) -> ReviewPolicy:
    policy_path = path or DEFAULT_POLICY_PATH
    if not policy_path.exists():
        return ReviewPolicy.from_dict({})
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    return ReviewPolicy.from_dict(data)
