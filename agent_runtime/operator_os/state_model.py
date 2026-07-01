"""Normalized read model for M3 Operator OS surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.costing.facade import build_cost_state
from agent_runtime.operator_os.stage_scope import active_stage_scope
from agent_runtime.operator_os.timeline import build_timeline

REQUIRED_PROJECT_BRAIN_FILES = [
    "PROJECT_HANDOFF.md",
    "project_artifact_index.yml",
    "project_fact_snapshot.yml",
    "acceptance_history.yml",
    "next_actions.yml",
]

# ── M3-1 standard status enumeration ──────────────────────────────────────
PHASE_STATUS_ENUM = {
    "accepted",
    "rejected",
    "needs_human_review",
    "needs_evidence",
    "paused",
    "blocked",
    "retryable",
    "ready",
    "needs_project_brain",
    "needs_operator_state_inputs",
}

TASK_STATUS_ENUM = {
    "pending",
    "in_progress",
    "completed",
    "blocked",
    "retryable",
    "paused",
    "failed",
    "needs_evidence",
}


def build_operator_state(root: Path, project: str = "AgentLab") -> dict[str, Any]:
    """Build the single read model consumed by M3 UI, TUI, CLI, and assistant modes."""
    root = root.resolve()
    project_root = root / "projects" / project
    brain_dir = project_root / "project_brain"
    runs_dir = project_root / "runs"
    read_errors: list[dict[str, str]] = []

    acceptance_history = _load_yaml(brain_dir / "acceptance_history.yml", {"entries": []}, root, read_errors)
    history_entries = acceptance_history.get("entries") if isinstance(acceptance_history, dict) else []
    history_entries = history_entries if isinstance(history_entries, list) else []
    accepted_phase_ids = [
        str(entry.get("phase_id"))
        for entry in history_entries
        if isinstance(entry, dict) and entry.get("accepted") and entry.get("phase_id")
    ]
    latest_acceptance = next(
        (entry for entry in reversed(history_entries) if isinstance(entry, dict)),
        None,
    )
    next_action = _load_yaml(brain_dir / "next_actions.yml", {}, root, read_errors)
    fact_snapshot = _load_yaml(brain_dir / "project_fact_snapshot.yml", {}, root, read_errors)
    artifact_index = _load_yaml(project_root / "project_artifact_index.yml", {}, root, read_errors)
    missing_brain_files = [
        name
        for name in REQUIRED_PROJECT_BRAIN_FILES
        if not _brain_file_path(project_root, brain_dir, name).exists()
    ]

    executor_results = _read_executor_results(runs_dir, root, read_errors)
    approvals = _read_approvals(history_entries, runs_dir, root, read_errors)
    recovery_plans = _read_recovery_plans(runs_dir, root, read_errors)
    capability_gaps = _read_capability_gaps(runs_dir, root, read_errors)
    evidence_ledgers = _read_evidence_ledgers(runs_dir, root, read_errors)
    cost_state = build_cost_state(project_root, accepted_phase_ids=accepted_phase_ids)
    phase_statuses = _classify_phase_statuses(history_entries, brain_dir, root, read_errors)

    return {
        "schema_version": 2,
        "stage": "M3_OPERATOR_OS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage_scope": active_stage_scope(),
        "project": {
            "id": project,
            "root": _relative_or_name(root, project_root),
            "status": _derive_project_status(brain_dir.exists(), missing_brain_files, latest_acceptance),
        },
        "source_policy": {
            "single_read_model": True,
            "progress_source": "project_brain/acceptance_history.yml + project_brain/next_actions.yml",
            "canonical_fact_source": "project_brain/project_fact_snapshot.yml",
            "artifact_current_source": "project_artifact_index.yml",
            "directory_layout_is_not_truth": True,
        },
        "project_brain": {
            "present": brain_dir.exists(),
            "path": _relative_or_name(root, brain_dir),
            "required_files": list(REQUIRED_PROJECT_BRAIN_FILES),
            "missing_files": missing_brain_files,
            "healthy": brain_dir.exists() and not missing_brain_files,
        },
        "phase_progress": {
            "accepted_phase_ids": accepted_phase_ids,
            "latest_acceptance": _compact_acceptance(latest_acceptance),
            "history_entry_count": len(history_entries),
            "phase_statuses": phase_statuses,
        },
        "next_action": {
            "source": _relative_or_name(root, brain_dir / "next_actions.yml"),
            "data": next_action if isinstance(next_action, dict) else {},
        },
        "facts": {
            "source": _relative_or_name(root, brain_dir / "project_fact_snapshot.yml"),
            "event_count": fact_snapshot.get("event_count") if isinstance(fact_snapshot, dict) else None,
            "project": fact_snapshot.get("project") if isinstance(fact_snapshot, dict) else None,
        },
        "artifacts": {
            "source": _relative_or_name(root, project_root / "project_artifact_index.yml"),
            "index_present": bool(artifact_index),
        },
        "executor_results": executor_results,
        "approvals": approvals,
        "recovery_plans": recovery_plans,
        "capability_gaps": capability_gaps,
        "evidence_ledgers": evidence_ledgers,
        "cost_state": cost_state,
        "timeline": build_timeline(project_root, read_errors),
        "read_errors": read_errors,
        "safety": {
            "ui_may_infer_progress_from_directories": False,
            "ui_may_write_production_content": False,
            "mutations_require_operator_action_contract": True,
        },
    }


# ── helper: YAML loader ──────────────────────────────────────────────────

def _load_yaml(
    path: Path,
    default: Any,
    root: Path | None = None,
    read_errors: list[dict[str, str]] | None = None,
) -> Any:
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if data is not None else default
    except Exception as exc:
        if read_errors is not None:
            read_errors.append({
                "path": _relative_or_name(root or path.parent, path),
                "error": f"{type(exc).__name__}: {exc}",
            })
        return default


def _brain_file_path(project_root: Path, brain_dir: Path, name: str) -> Path:
    if name == "PROJECT_HANDOFF.md":
        return project_root / name
    if name == "project_artifact_index.yml":
        return project_root / name
    return brain_dir / name


# ── helpers: project status derivation ────────────────────────────────────

def _derive_project_status(brain_present: bool, missing_brain_files: list[str], latest_acceptance: dict[str, Any] | None) -> str:
    if not brain_present:
        return "needs_project_brain"
    if missing_brain_files:
        return "needs_operator_state_inputs"
    if latest_acceptance and not latest_acceptance.get("accepted"):
        return str(latest_acceptance.get("verdict") or "needs_attention").lower()
    return "ready"


def _compact_acceptance(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    return {
        "phase_id": entry.get("phase_id"),
        "accepted": bool(entry.get("accepted")),
        "verdict": entry.get("verdict"),
        "recommended_next_action": entry.get("recommended_next_action"),
        "evidence_files": entry.get("evidence_files") or [],
        "recorded_at": entry.get("recorded_at"),
    }


# ── M3-1: phase status classification ────────────────────────────────────

def _classify_phase_statuses(
    history_entries: list[dict[str, Any]],
    brain_dir: Path,
    root: Path | None = None,
    read_errors: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    """Derive per-phase status from acceptance history.

    Returns {phase_id: status_enum} where status_enum is one of:
    accepted, rejected, needs_human_review, needs_evidence, paused, blocked, retryable.
    """
    statuses: dict[str, str] = {}
    current_phase = _load_yaml(brain_dir / "current_phase.yml", {}, root, read_errors)
    if isinstance(current_phase, dict) and current_phase.get("phase_id"):
        pid = str(current_phase["phase_id"])
        raw_status = str(current_phase.get("status") or "")
        if raw_status == "paused":
            statuses[pid] = "paused"
        elif raw_status == "blocked":
            statuses[pid] = "blocked"

    for entry in history_entries:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("phase_id") or "")
        if not pid:
            continue
        if pid in statuses and statuses[pid] in ("accepted", "rejected"):
            continue
        accepted = bool(entry.get("accepted"))
        verdict = str(entry.get("verdict") or "").lower()
        missing_evidence = entry.get("missing_evidence")
        if accepted:
            statuses[pid] = "accepted"
        elif "human_review" in verdict or "needs_human_review" in verdict:
            statuses[pid] = "needs_human_review"
        elif missing_evidence and (isinstance(missing_evidence, list) and missing_evidence):
            statuses[pid] = "needs_evidence"
        elif "retry" in verdict:
            statuses[pid] = "retryable"
        elif "blocked" in verdict:
            statuses[pid] = "blocked"
        elif "reject" in verdict:
            statuses[pid] = "rejected"
        else:
            statuses[pid] = "needs_human_review"
    return statuses


# ── M3-1: executor results reader ─────────────────────────────────────────

def _read_executor_results(
    runs_dir: Path,
    root: Path | None = None,
    read_errors: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Collect executor result envelopes from all task run directories."""
    results: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return results
    for task_dir in sorted(runs_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        envelope_path = task_dir / "execution_result_envelope.yml"
        result_path = task_dir / "executor_result.yml"
        source = result_path if result_path.exists() else envelope_path
        if not source.exists():
            continue
        data = _load_yaml(source, {}, root, read_errors)
        if not isinstance(data, dict):
            continue
        envelope = data.get("executor_result") or data
        results.append({
            "task_id": task_dir.name,
            "source": _relative_or_name(runs_dir.parent, source),
            "status": envelope.get("status"),
            "executor_id": envelope.get("executor_id") or envelope.get("provider_id"),
            "summary": envelope.get("summary"),
            "changed_files_count": len(envelope.get("changed_files") or []),
            "has_test_evidence": bool(
                envelope.get("test_results")
                or envelope.get("test_status")
                or envelope.get("claimed_tests")
            ),
            "safety_attestation": envelope.get("safety_attestation"),
        })
    return results


# ── M3-1: approvals reader ────────────────────────────────────────────────

def _read_approvals(
    history_entries: list[dict[str, Any]],
    runs_dir: Path,
    root: Path | None = None,
    read_errors: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Extract pending and resolved approvals from acceptance history and decision cards."""
    approvals: list[dict[str, Any]] = []
    for entry in history_entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("human_approval_required"):
            approvals.append({
                "phase_id": entry.get("phase_id"),
                "type": "phase_acceptance",
                "status": "approved" if entry.get("accepted") else "pending",
                "verdict": entry.get("verdict"),
                "recorded_at": entry.get("recorded_at"),
                "source": "acceptance_history",
            })

    if runs_dir.exists():
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            dc_dir = task_dir / "decision_cards"
            if not dc_dir.is_dir():
                continue
            for card_path in sorted(dc_dir.glob("*.yml")):
                card = _load_yaml(card_path, {}, root, read_errors)
                if isinstance(card, dict):
                    approvals.append({
                        "task_id": task_dir.name,
                        "type": "decision_card",
                        "card_file": card_path.name,
                        "status": card.get("status") or "pending",
                        "question": card.get("question"),
                        "source": "decision_card",
                    })
    return approvals


# ── M3-1: recovery plans reader ───────────────────────────────────────────

def _read_recovery_plans(
    runs_dir: Path,
    root: Path | None = None,
    read_errors: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Collect recovery plans from task run directories."""
    plans: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return plans
    for task_dir in sorted(runs_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        recovery_dir = task_dir / "recovery"
        if not recovery_dir.is_dir():
            continue
        plan_path = recovery_dir / "recovery_plan.yml"
        if not plan_path.exists():
            plan_path = recovery_dir / "recovery_plan.md"
        if not plan_path.exists():
            continue
        plans.append({
            "task_id": task_dir.name,
            "source": _relative_or_name(runs_dir.parent, plan_path),
            "format": plan_path.suffix.lstrip("."),
        })
        diag_path = recovery_dir / "failure_diagnosis.yml"
        if diag_path.exists():
            diag = _load_yaml(diag_path, {}, root, read_errors)
            if isinstance(diag, dict):
                plans[-1]["failure_category"] = diag.get("failure_category")
                plans[-1]["confidence"] = diag.get("confidence")
                plans[-1]["recommended_action"] = diag.get("recommended_action")
    return plans


# ── M3-1: capability gaps reader ──────────────────────────────────────────

def _read_capability_gaps(
    runs_dir: Path,
    root: Path | None = None,
    read_errors: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Collect capability gap records from task run directories."""
    gaps: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return gaps
    for task_dir in sorted(runs_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        gap_dir = task_dir / "capability_gaps"
        if gap_dir.is_dir():
            for gap_path in sorted(gap_dir.glob("*.yml")):
                gap = _load_yaml(gap_path, {}, root, read_errors)
                if isinstance(gap, dict):
                    gaps.append({
                        "task_id": task_dir.name,
                        "capability": gap.get("capability") or gap.get("capability_id"),
                        "status": gap.get("status") or "unresolved",
                        "recommended_action": gap.get("recommended_action"),
                        "source": "capability_gap",
                    })
        dc_dir = task_dir / "decision_cards"
        if dc_dir.is_dir():
            for card_path in sorted(dc_dir.glob("*capability*.yml")):
                card = _load_yaml(card_path, {}, root, read_errors)
                if isinstance(card, dict):
                    gaps.append({
                        "task_id": task_dir.name,
                        "capability": card.get("capability") or card.get("capability_id"),
                        "status": card.get("status") or "pending",
                        "recommended_action": card.get("recommended_action"),
                        "source": "decision_card",
                    })
    return gaps


# ── M3-1: evidence ledger reader ──────────────────────────────────────────

def _read_evidence_ledgers(
    runs_dir: Path,
    root: Path | None = None,
    read_errors: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Collect evidence ledger summaries from task run directories."""
    ledgers: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return ledgers
    for task_dir in sorted(runs_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        ledger_path = task_dir / "evidence_ledger.yml"
        if not ledger_path.exists():
            continue
        ledger = _load_yaml(ledger_path, {}, root, read_errors)
        if not isinstance(ledger, dict):
            continue
        ledgers.append({
            "task_id": task_dir.name,
            "source": _relative_or_name(runs_dir.parent, ledger_path),
            "evidence_count": ledger.get("evidence_count"),
            "file_count": len(ledger.get("files") or []),
        })
    return ledgers


# ── helpers: formatting ───────────────────────────────────────────────────

def _relative_or_name(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name
