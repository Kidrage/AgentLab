from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ALLOWED_RESULT_STATUSES = {
    "PASS",
    "FAIL",
    "BLOCKED",
    "PARTIAL",
    "CANCELLED",
}


def load_executor_result_envelope(result_dir: Path) -> dict[str, Any]:
    """Load and validate an executor result envelope from a result directory."""
    envelope_path = result_dir / "execution_result_envelope.yml"
    result_path = result_dir / "executor_result.yml"
    source_path = result_path if result_path.exists() else envelope_path
    if not source_path.exists():
        raise ValueError("executor result must include executor_result.yml or execution_result_envelope.yml")

    raw = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    envelope = raw.get("executor_result") or raw
    if not isinstance(envelope, dict):
        raise ValueError("executor result envelope must be a mapping")

    validation = validate_executor_result_envelope(envelope)
    if not validation["valid"]:
        joined = "; ".join(validation["errors"])
        raise ValueError(f"invalid executor result envelope: {joined}")
    return envelope


def validate_executor_result_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    _require_any(envelope, ("task_packet_id", "task_id", "phase_id"), errors, "task identity")
    _require_any(envelope, ("executor_id", "provider_id"), errors, "executor identity")
    _require_text(envelope, "source", errors)
    _require_text(envelope, "summary", errors)

    status = str(envelope.get("status") or "").upper()
    if not status:
        errors.append("status is required")
    elif status not in ALLOWED_RESULT_STATUSES:
        errors.append(f"status must be one of {sorted(ALLOWED_RESULT_STATUSES)}")

    changed_files = envelope.get("changed_files")
    if not isinstance(changed_files, list):
        errors.append("changed_files must be a list")
    elif not changed_files and not envelope.get("no_change_rationale"):
        errors.append("changed_files may be empty only with no_change_rationale")

    _require_any(envelope, ("test_results", "test_status", "claimed_tests"), errors, "test evidence summary")
    artifacts = envelope.get("artifacts") or envelope.get("output_artifacts") or envelope.get("evidence_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts/output_artifacts/evidence_artifacts must be a non-empty list")

    safety_attestation = envelope.get("safety_attestation")
    if not isinstance(safety_attestation, dict):
        errors.append("safety_attestation must be supplied as a mapping")
    elif safety_attestation.get("secrets_exposed") is not False:
        errors.append("safety_attestation.secrets_exposed must be false")

    if "provider_id" in envelope and "executor_id" not in envelope:
        warnings.append("provider_id is accepted as legacy executor identity; prefer executor_id")
    if "task_id" in envelope and "task_packet_id" not in envelope:
        warnings.append("task_id is accepted as legacy task identity; prefer task_packet_id")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _require_any(envelope: dict[str, Any], fields: tuple[str, ...], errors: list[str], label: str) -> None:
    if not any(envelope.get(field) for field in fields):
        errors.append(f"{label} is required; expected one of {', '.join(fields)}")


def _require_text(envelope: dict[str, Any], field: str, errors: list[str]) -> None:
    value = envelope.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} is required")
