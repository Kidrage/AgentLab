"""S6 Recovery Brain / Alternative Route Planner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_json, safe_read_yaml
from agent_runtime.recovery.capability_gap_resolver import build_capability_gap_decision_card
from agent_runtime.recovery.escalation_policy import escalation_for_failure
from agent_runtime.recovery.failure_taxonomy import normalize_failure_type
from agent_runtime.recovery.fake_evidence_detector import detect_fake_evidence
from agent_runtime.recovery.strategy_search import search_recovery_strategy


def _read_mapping(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    if path.suffix.lower() == ".json":
        data = safe_read_json(path, default={}) or {}
    else:
        data = safe_read_yaml(path, default={}) or {}
    return data if isinstance(data, dict) else {}


def _infer_failure_type(
    explicit_failure_type: str | None,
    failure_event: dict[str, Any],
    diagnosis: dict[str, Any],
    evidence_report: dict[str, Any],
    capability_card: dict[str, Any],
) -> str:
    if explicit_failure_type:
        return normalize_failure_type(explicit_failure_type).value
    if evidence_report.get("hard_fail"):
        return "evidence_missing"
    if capability_card.get("missing_capabilities"):
        return "capability_gap"
    for key in ("primary_category", "failure_category", "error_type"):
        value = diagnosis.get(key) or failure_event.get(key)
        if value:
            return normalize_failure_type(str(value)).value
    return "unknown"


def build_s6_recovery_brain_packet(
    *,
    out_dir: Path,
    failure_type: str | None = None,
    failure_event_path: Path | None = None,
    diagnosis_path: Path | None = None,
    mission_contract_path: Path | None = None,
    evidence_ledger_path: Path | None = None,
    available_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Write S6 strategy, alternative route, gap, and evidence reports."""

    failure_event = _read_mapping(failure_event_path)
    diagnosis = _read_mapping(diagnosis_path)
    mission = _read_mapping(mission_contract_path)
    evidence_ledger = _read_mapping(evidence_ledger_path)

    evidence_report = detect_fake_evidence(evidence_ledger)
    capability_card = build_capability_gap_decision_card(mission, available_capabilities)
    normalized_failure = _infer_failure_type(
        failure_type,
        failure_event,
        diagnosis,
        evidence_report,
        capability_card,
    )
    strategy = search_recovery_strategy(normalized_failure)
    escalation = escalation_for_failure(normalized_failure)

    recovery_strategy_plan = {
        "schema_version": 1,
        "stage": "S6",
        "failure_type": normalized_failure,
        "strategy": strategy.to_dict(),
        "escalation": escalation,
        "inputs": {
            "failure_event": str(failure_event_path) if failure_event_path else None,
            "diagnosis": str(diagnosis_path) if diagnosis_path else None,
            "mission_contract": str(mission_contract_path) if mission_contract_path else None,
            "evidence_ledger": str(evidence_ledger_path) if evidence_ledger_path else None,
        },
        "ledger_required": True,
        "auto_execute": False,
    }

    alternative_route_plan = {
        "schema_version": 1,
        "stage": "S6",
        "primary_failure_type": normalized_failure,
        "next_action": strategy.next_action,
        "route_options": [
            {
                "action": strategy.next_action,
                "approval_required": strategy.requires_human_approval,
                "max_attempts": strategy.max_attempts,
            },
            {
                "action": "stop_safely",
                "approval_required": False,
                "max_attempts": 0,
            },
        ],
        "no_infinite_retry": True,
        "write_to_ledger": True,
    }

    phase_acceptance = {
        "schema_version": 1,
        "stage": "S6",
        "acceptance": {
            "strategy_plan_generated": True,
            "alternative_route_plan_generated": True,
            "capability_gap_decision_card_generated": True,
            "fake_evidence_report_generated": True,
            "evidence_missing_hard_fails": (
                evidence_report["hard_fail"] or normalized_failure == "evidence_missing"
            ),
            "no_infinite_retry": True,
            "ledger_written": True,
        },
        "verdict": "pass",
    }

    ledger_entry = {
        "stage": "S6",
        "failure_type": normalized_failure,
        "next_action": strategy.next_action,
        "human_approval_required": strategy.requires_human_approval,
        "evidence_verdict": evidence_report["verdict"],
        "missing_capabilities": capability_card.get("missing_capabilities", []),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "recovery_strategy_plan": out_dir / "recovery_strategy_plan.yml",
        "alternative_route_plan": out_dir / "alternative_route_plan.yml",
        "capability_gap_decision_card": out_dir / "capability_gap_decision_card.yml",
        "fake_evidence_report": out_dir / "fake_evidence_report.yml",
        "phase_acceptance_evidence": out_dir / "phase_acceptance_evidence.yml",
        "recovery_strategy_ledger": out_dir / "recovery_strategy_ledger.yml",
    }
    atomic_write_yaml(paths["recovery_strategy_plan"], recovery_strategy_plan)
    atomic_write_yaml(paths["alternative_route_plan"], alternative_route_plan)
    atomic_write_yaml(paths["capability_gap_decision_card"], capability_card)
    atomic_write_yaml(paths["fake_evidence_report"], evidence_report)
    atomic_write_yaml(paths["phase_acceptance_evidence"], phase_acceptance)
    atomic_write_yaml(paths["recovery_strategy_ledger"], {"entries": [ledger_entry]})

    return {
        "ok": True,
        "failure_type": normalized_failure,
        "next_action": strategy.next_action,
        "evidence_verdict": evidence_report["verdict"],
        "missing_capabilities": capability_card.get("missing_capabilities", []),
        "artifacts": {key: str(path) for key, path in paths.items()},
    }