"""Normalized read model for M3 Operator OS surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.operator_os.stage_scope import active_stage_scope

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

    acceptance_history = _load_yaml(brain_dir / "acceptance_history.yml", {"entries": []})
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
    next_action = _load_yaml(brain_dir / "next_actions.yml", {})
    fact_snapshot = _load_yaml(brain_dir / "project_fact_snapshot.yml", {})
    artifact_index = _load_yaml(project_root / "project_artifact_index.yml", {})
    missing_brain_files = [
        name
        for name in REQUIRED_PROJECT_BRAIN_FILES
        if not _brain_file_path(project_root, brain_dir, name).exists()
    ]

    executor_results = _read_executor_results(runs_dir)
    approvals = _read_approvals(history_entries, runs_dir)
    recovery_plans = _read_recovery_plans(runs_dir)
    capability_gaps = _read_capability_gaps(runs_dir)
    evidence_ledgers = _read_evidence_ledgers(runs_dir)
    cost_state = _read_cost_state(runs_dir)
    phase_statuses = _classify_phase_statuses(history_entries, brain_dir)

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
        "timeline": _build_full_timeline(history_entries, runs_dir, brain_dir),
        "safety": {
            "ui_may_infer_progress_from_directories": False,
            "ui_may_write_production_content": False,
            "mutations_require_operator_action_contract": True,
        },
    }


# ── helper: YAML loader ──────────────────────────────────────────────────

def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else default


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
) -> dict[str, str]:
    """Derive per-phase status from acceptance history.

    Returns {phase_id: status_enum} where status_enum is one of:
    accepted, rejected, needs_human_review, needs_evidence, paused, blocked, retryable.
    """
    statuses: dict[str, str] = {}
    current_phase = _load_yaml(brain_dir / "current_phase.yml", {})
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

def _read_executor_results(runs_dir: Path) -> list[dict[str, Any]]:
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
        data = _load_yaml(source, {})
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
                card = _load_yaml(card_path, {})
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

def _read_recovery_plans(runs_dir: Path) -> list[dict[str, Any]]:
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
            diag = _load_yaml(diag_path, {})
            if isinstance(diag, dict):
                plans[-1]["failure_category"] = diag.get("failure_category")
                plans[-1]["confidence"] = diag.get("confidence")
                plans[-1]["recommended_action"] = diag.get("recommended_action")
    return plans


# ── M3-1: capability gaps reader ──────────────────────────────────────────

def _read_capability_gaps(runs_dir: Path) -> list[dict[str, Any]]:
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
                gap = _load_yaml(gap_path, {})
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
                card = _load_yaml(card_path, {})
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

def _read_evidence_ledgers(runs_dir: Path) -> list[dict[str, Any]]:
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
        ledger = _load_yaml(ledger_path, {})
        if not isinstance(ledger, dict):
            continue
        ledgers.append({
            "task_id": task_dir.name,
            "source": _relative_or_name(runs_dir.parent, ledger_path),
            "evidence_count": ledger.get("evidence_count"),
            "file_count": len(ledger.get("files") or []),
        })
    return ledgers


# ── M3-1: cost / budget state reader ──────────────────────────────────────

def _read_cost_state(runs_dir: Path) -> dict[str, Any]:
    """Aggregate cost state across all task runs."""
    cost_ledgers: list[dict[str, Any]] = []
    total_estimated_cost = 0.0
    has_cost = False
    if runs_dir.exists():
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            cost_path = task_dir / "cost_ledger.yml"
            if not cost_path.exists():
                continue
            ledger = _load_yaml(cost_path, {})
            if not isinstance(ledger, dict):
                continue
            calls = ledger.get("calls") or []
            task_total = 0.0
            for call in calls:
                if isinstance(call, dict) and call.get("estimated_cost_usd") is not None:
                    task_total += float(call["estimated_cost_usd"])
                    has_cost = True
            cost_ledgers.append({
                "task_id": task_dir.name,
                "call_count": len(calls),
                "estimated_cost_usd": round(task_total, 6),
            })
            total_estimated_cost += task_total

    global_ledger_path = runs_dir.parent.parent / "costs" / "cost_ledger.jsonl"
    global_present = global_ledger_path.exists() if runs_dir.exists() else False

    return {
        "total_estimated_cost_usd": round(total_estimated_cost, 6) if has_cost else None,
        "has_cost_data": has_cost or global_present,
        "global_cost_ledger_present": global_present,
        "per_task_ledgers": cost_ledgers,
    }


# ── M3-1 / M3-6: full timeline builder ────────────────────────────────────

def _build_full_timeline(
    history_entries: list[dict[str, Any]],
    runs_dir: Path,
    brain_dir: Path,
) -> list[dict[str, Any]]:
    """Build a unified timeline from all available event sources."""
    timeline: list[dict[str, Any]] = []

    # phase acceptance history events
    for entry in history_entries:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("phase_id")
        accepted = bool(entry.get("accepted"))
        verdict = entry.get("verdict")
        recorded = entry.get("recorded_at") or ""
        timeline.append({
            "event_type": "phase_acceptance_verdict",
            "time": recorded,
            "phase_id": pid,
            "verdict": verdict,
            "accepted": accepted,
            "source": "project_brain/acceptance_history.yml",
        })
        if accepted:
            timeline.append({
                "event_type": "acceptance_history_written",
                "time": recorded,
                "phase_id": pid,
                "source": "project_brain/acceptance_history.yml",
            })
        na = entry.get("recommended_next_action")
        if na:
            timeline.append({
                "event_type": "next_action_recalculated",
                "time": recorded,
                "phase_id": pid,
                "next_action": na,
                "source": "project_brain/acceptance_history.yml",
            })
        st = entry.get("state_transition")
        if isinstance(st, dict):
            if st.get("applied"):
                timeline.append({
                    "event_type": "state_transition_applied",
                    "time": recorded,
                    "phase_id": pid,
                    "applied_event_ids": st.get("applied_event_ids"),
                    "source": "project_brain/acceptance_history.yml",
                })
            elif st.get("proposal_supplied"):
                timeline.append({
                    "event_type": "state_transition_proposed",
                    "time": recorded,
                    "phase_id": pid,
                    "source": "project_brain/acceptance_history.yml",
                })

    # executor result events from run dirs
    if runs_dir.exists():
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            tp_path = task_dir / "task_packet.yml"
            if tp_path.exists():
                tp = _load_yaml(tp_path, {})
                if isinstance(tp, dict):
                    timeline.append({
                        "event_type": "task_packet_created",
                        "time": str(tp.get("created_at") or ""),
                        "task_id": task_dir.name,
                        "phase_id": tp.get("phase_id"),
                        "source": _relative_or_name(runs_dir.parent, tp_path),
                    })

            er_path = task_dir / "executor_result.yml"
            if not er_path.exists():
                er_path = task_dir / "execution_result_envelope.yml"
            if er_path.exists():
                er = _load_yaml(er_path, {})
                envelope = (er.get("executor_result") or er) if isinstance(er, dict) else {}
                if isinstance(envelope, dict):
                    timeline.append({
                        "event_type": "executor_result_received",
                        "time": str(envelope.get("finished_at") or envelope.get("recorded_at") or ""),
                        "task_id": task_dir.name,
                        "executor_id": envelope.get("executor_id") or envelope.get("provider_id"),
                        "status": envelope.get("status"),
                        "source": _relative_or_name(runs_dir.parent, er_path),
                    })
                    if envelope.get("status") == "FAIL":
                        timeline.append({
                            "event_type": "recovery_started",
                            "time": str(envelope.get("finished_at") or ""),
                            "task_id": task_dir.name,
                            "source": _relative_or_name(runs_dir.parent, er_path),
                        })

            rec_dir = task_dir / "recovery"
            if rec_dir.is_dir():
                rp_path = rec_dir / "recovery_plan.yml"
                if rp_path.exists():
                    rp = _load_yaml(rp_path, {})
                    if isinstance(rp, dict):
                        timeline.append({
                            "event_type": "recovery_resolved",
                            "time": str(rp.get("created_at") or ""),
                            "task_id": task_dir.name,
                            "recommended_action": rp.get("recommended_action"),
                            "source": _relative_or_name(runs_dir.parent, rp_path),
                        })

            ev_path = task_dir / "evidence_ledger.yml"
            if ev_path.exists():
                ev = _load_yaml(ev_path, {})
                if isinstance(ev, dict) and ev.get("files"):
                    timeline.append({
                        "event_type": "evidence_consumed",
                        "time": "",
                        "task_id": task_dir.name,
                        "evidence_count": ev.get("evidence_count"),
                        "source": _relative_or_name(runs_dir.parent, ev_path),
                    })

            dc_dir = task_dir / "decision_cards"
            if dc_dir.is_dir():
                for card_path in sorted(dc_dir.glob("*.yml")):
                    card = _load_yaml(card_path, {})
                    if isinstance(card, dict):
                        status = card.get("status") or "pending"
                        event_type = "approval_resolved" if status in ("approved", "rejected") else "approval_requested"
                        timeline.append({
                            "event_type": event_type,
                            "time": str(card.get("resolved_at") or card.get("created_at") or ""),
                            "task_id": task_dir.name,
                            "card_file": card_path.name,
                            "status": status,
                            "source": _relative_or_name(runs_dir.parent, card_path),
                        })

            cg_dir = task_dir / "capability_gaps"
            if cg_dir.is_dir() and any(cg_dir.iterdir()):
                for cg_path in sorted(cg_dir.glob("*.yml")):
                    timeline.append({
                        "event_type": "capability_gap_raised",
                        "time": "",
                        "task_id": task_dir.name,
                        "source": _relative_or_name(runs_dir.parent, cg_path),
                    })

            pa_path = task_dir / "phase_acceptance.yml"
            if pa_path.exists():
                pa = _load_yaml(pa_path, {})
                if isinstance(pa, dict):
                    st = pa.get("state_transition")
                    if isinstance(st, dict) and st.get("applied"):
                        timeline.append({
                            "event_type": "artifact_promoted",
                            "time": str(pa.get("recorded_at") or ""),
                            "task_id": task_dir.name,
                            "source": _relative_or_name(runs_dir.parent, pa_path),
                        })

    # fact snapshot state transition events
    fs = _load_yaml(brain_dir / "project_fact_snapshot.yml", {})
    if isinstance(fs, dict) and fs.get("events"):
        for event in fs["events"]:
            if isinstance(event, dict):
                timeline.append({
                    "event_type": "state_transition_applied",
                    "time": str(event.get("timestamp") or event.get("recorded_at") or ""),
                    "event_id": event.get("event_id"),
                    "source": "project_brain/project_fact_snapshot.yml",
                })

    # sort: entries with time first, empty-time entries last
    def _sort_key(item: dict[str, Any]) -> str:
        t = str(item.get("time") or "")
        return "z" + t if not t else "a" + t

    timeline.sort(key=_sort_key)
    return timeline


# ── helpers: formatting ───────────────────────────────────────────────────

def _relative_or_name(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name
