from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.recovery.replanning import replan_phase


def recover_failed_phase(
    project_brain_dir: Path,
    phase_id: str,
    acceptance_result_path: Path,
    out_dir: Path,
) -> dict:
    """Read a failed acceptance result and generate the phase recovery artifacts."""
    acceptance_result = _load_acceptance_result(acceptance_result_path)
    resolved_phase_id = _resolve_phase_id(
        requested_phase_id=phase_id,
        acceptance_result=acceptance_result,
    )
    acceptance_result["phase_id"] = resolved_phase_id

    out_dir.mkdir(parents=True, exist_ok=True)
    replan_report = replan_phase(
        acceptance_result=acceptance_result,
        project_brain_dir=project_brain_dir,
        out_dir=out_dir,
    )

    recovery_summary = _build_recovery_summary(
        phase_id=resolved_phase_id,
        acceptance_result_path=acceptance_result_path,
        acceptance_result=acceptance_result,
        replan_report=replan_report,
    )
    atomic_write_yaml(out_dir / "phase_recovery.yml", recovery_summary)

    return replan_report


def _load_acceptance_result(path: Path) -> dict[str, Any]:
    """Load the YAML acceptance result produced by the phase acceptance gate."""
    if not path.exists():
        raise FileNotFoundError(f"acceptance result path does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"acceptance result path is not a file: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"acceptance result must be a YAML mapping: {path}")
    return dict(raw)


def _resolve_phase_id(
    requested_phase_id: str,
    acceptance_result: dict[str, Any],
) -> str:
    """Return a stable phase id and guard against accidental cross-phase recovery."""
    normalized_requested = _normalize_phase_id(requested_phase_id)
    result_phase_id = _normalize_phase_id(str(acceptance_result.get("phase_id", "")))

    if result_phase_id and normalized_requested and result_phase_id != normalized_requested:
        raise ValueError(
            "acceptance result phase_id does not match requested phase: "
            f"{result_phase_id} != {normalized_requested}"
        )
    if result_phase_id:
        return result_phase_id
    if normalized_requested:
        return normalized_requested
    return "unknown"


def _normalize_phase_id(value: str) -> str:
    """Trim phase ids from CLI/config inputs without inventing aliases."""
    return value.strip()


def _build_recovery_summary(
    phase_id: str,
    acceptance_result_path: Path,
    acceptance_result: dict[str, Any],
    replan_report: dict[str, Any],
) -> dict[str, Any]:
    """Build the durable recovery summary consumed by follow-up tooling."""
    missing_evidence = acceptance_result.get("missing_evidence") or []
    scope_status = acceptance_result.get("scope_status") or {}
    test_results = acceptance_result.get("test_results") or {}

    return {
        "phase_id": phase_id,
        "acceptance_result_path": str(acceptance_result_path),
        "acceptance_verdict": acceptance_result.get("verdict", "UNKNOWN"),
        "failure_reason": replan_report.get("failure_reason", "unknown"),
        "recommended_next_action": replan_report.get("recommended_next_action", "retry_same"),
        "retry_count": replan_report.get("retry_count", 0),
        "signals": {
            "missing_evidence_count": len(missing_evidence),
            "has_scope_violations": bool(scope_status.get("has_violations")),
            "tests_passed": bool(test_results.get("passed", True)),
            "budget_exceeded": bool(
                test_results.get("budget_exceeded")
                or acceptance_result.get("budget_exceeded")
            ),
        },
        "artifacts": {
            "replan_plan_yml": "replan_plan.yml",
            "replan_plan_md": "replan_plan.md",
            "capability_gap_decision_card_yml": (
                "capability_gap_decision_card.yml"
                if replan_report.get("failure_reason") == "capability_gap"
                else None
            ),
        },
    }
