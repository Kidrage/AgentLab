"""Capability gap decision cards."""

from __future__ import annotations

from pathlib import Path

import yaml

from .registry import CapabilityRegistry


def write_capability_gap_card(
    *,
    registry: CapabilityRegistry,
    capability_id: str,
    out_dir: Path,
    reason: str,
) -> Path:
    record = registry.get(capability_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "capability_gap_decision_card.yml"
    data = {
        "required_capability": capability_id,
        "reason": reason,
        "available_backends": [],
        "missing_backend_reason": record.missing_backend_reason or "capability is not available without explicit backend configuration",
        "approval_options": [
            "configure_local_mock_backend",
            "approve_external_backend_after_review",
            "skip_capability_and_continue_without_fabricated_result",
        ],
        "recommended_next_action": "request_approval_or_configure_backend",
        "risk_notes": [
            "do_not_execute_external_tools_automatically",
            "do_not_fabricate_perception_results",
            "write explicit artifact contracts only",
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
