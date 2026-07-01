"""M3-6 Observability Timeline — unified event stream and failure narrative."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


SUPPORTED_EVENT_TYPES = frozenset({
    "task_packet_created",
    "executor_assigned",
    "executor_result_received",
    "evidence_consumed",
    "phase_acceptance_verdict",
    "acceptance_history_written",
    "next_action_recalculated",
    "state_transition_proposed",
    "state_transition_applied",
    "state_transition_rejected",
    "approval_requested",
    "approval_resolved",
    "capability_gap_raised",
    "recovery_started",
    "recovery_resolved",
    "budget_warning",
    "artifact_promoted",
    "artifact_archived",
    "operator_action_recorded",
})

UI_LINK_PREFIX = "/api/tasks"


def build_timeline(project_root: Path) -> list[dict[str, Any]]:
    """Build a unified observability timeline from all event sources.

    Scans:
    - project_brain/acceptance_history.yml → acceptance events
    - project_brain/project_fact_snapshot.yml → state transition events
    - runs/*/executor_result.yml → executor events
    - runs/*/evidence_ledger.yml → evidence events
    - runs/*/decision_cards/*.yml → approval events
    - runs/*/capability_gaps/*.yml → capability gap events
    - runs/*/recovery/*.yml → recovery events
    - runs/*/phase_acceptance.yml → artifact promotion events
    - project_brain/operator_action_ledger.yml → UI/TUI operator actions
    """
    timeline: list[dict[str, Any]] = []
    brain_dir = project_root / "project_brain"
    runs_dir = project_root / "runs"
    project = project_root.name

    # ── acceptance history events ──────────────────────────────────────
    ah = _load_yaml(brain_dir / "acceptance_history.yml", {})
    history_entries = ah.get("entries") if isinstance(ah, dict) else []
    history_entries = history_entries if isinstance(history_entries, list) else []
    for entry in history_entries:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("phase_id")
        accepted = bool(entry.get("accepted"))
        verdict = str(entry.get("verdict") or "")
        recorded = entry.get("recorded_at") or ""

        timeline.append(_event("phase_acceptance_verdict", recorded, {
            "phase_id": pid, "verdict": verdict, "accepted": accepted,
            "source": "project_brain/acceptance_history.yml",
        }))
        if accepted:
            timeline.append(_event("acceptance_history_written", recorded, {
                "phase_id": pid,
                "source": "project_brain/acceptance_history.yml",
            }))
        na = entry.get("recommended_next_action")
        if na:
            timeline.append(_event("next_action_recalculated", recorded, {
                "phase_id": pid, "next_action": na,
                "source": "project_brain/acceptance_history.yml",
            }))
        st = entry.get("state_transition")
        if isinstance(st, dict):
            if st.get("applied"):
                timeline.append(_event("state_transition_applied", recorded, {
                    "phase_id": pid,
                    "applied_event_ids": st.get("applied_event_ids"),
                    "source": "project_brain/acceptance_history.yml",
                }))
            elif st.get("proposal_supplied"):
                timeline.append(_event("state_transition_proposed", recorded, {
                    "phase_id": pid,
                    "source": "project_brain/acceptance_history.yml",
                }))

    # ── fact snapshot events ───────────────────────────────────────────
    fs = _load_yaml(brain_dir / "project_fact_snapshot.yml", {})
    if isinstance(fs, dict) and fs.get("events"):
        for event in fs["events"]:
            if isinstance(event, dict):
                ts = str(event.get("timestamp") or event.get("recorded_at") or "")
                timeline.append(_event("state_transition_applied", ts, {
                    "event_id": event.get("event_id"),
                    "source": "project_brain/project_fact_snapshot.yml",
                }))

    # ── operator action audit events ───────────────────────────────────
    oal = _load_yaml(brain_dir / "operator_action_ledger.yml", {})
    action_entries = oal.get("entries") if isinstance(oal, dict) else []
    action_entries = action_entries if isinstance(action_entries, list) else []
    for entry in action_entries:
        if not isinstance(entry, dict):
            continue
        timeline.append(_event("operator_action_recorded", str(entry.get("recorded_at") or ""), {
            "action": entry.get("action"),
            "target_type": entry.get("target_type"),
            "target_id": entry.get("target_id"),
            "actor": entry.get("actor"),
            "source_surface": entry.get("source_surface"),
            "source": "project_brain/operator_action_ledger.yml",
        }))

    # ── run directory events ───────────────────────────────────────────
    if runs_dir.exists():
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            task_id = task_dir.name

            # task_packet_created
            tp_path = task_dir / "task_packet.yml"
            if tp_path.exists():
                tp = _load_yaml(tp_path, {})
                if isinstance(tp, dict):
                    timeline.append(_event("task_packet_created",
                        str(tp.get("created_at") or ""), {
                            "task_id": task_id,
                            "phase_id": tp.get("phase_id"),
                            "source": _rel(task_dir),
                        }))

            # executor_result_received
            er_path = task_dir / "executor_result.yml"
            if not er_path.exists():
                er_path = task_dir / "execution_result_envelope.yml"
            if er_path.exists():
                er = _load_yaml(er_path, {})
                env = (er.get("executor_result") or er) if isinstance(er, dict) else {}
                if isinstance(env, dict):
                    status = env.get("status")
                    timeline.append(_event("executor_result_received",
                        str(env.get("finished_at") or env.get("recorded_at") or ""), {
                            "task_id": task_id,
                            "executor_id": env.get("executor_id") or env.get("provider_id"),
                            "status": status,
                            "source": _rel(er_path),
                            "ui_link": f"{UI_LINK_PREFIX}/{project}/{task_id}/events",
                        }))
                    if status == "FAIL":
                        timeline.append(_event("recovery_started",
                            str(env.get("finished_at") or ""), {
                                "task_id": task_id,
                                "source": _rel(er_path),
                            }))

            # recovery_resolved
            rec_dir = task_dir / "recovery"
            if rec_dir.is_dir():
                rp_path = rec_dir / "recovery_plan.yml"
                if rp_path.exists():
                    rp = _load_yaml(rp_path, {})
                    if isinstance(rp, dict):
                        timeline.append(_event("recovery_resolved",
                            str(rp.get("created_at") or ""), {
                                "task_id": task_id,
                                "recommended_action": rp.get("recommended_action"),
                                "source": _rel(rp_path),
                            }))

            # evidence_consumed
            ev_path = task_dir / "evidence_ledger.yml"
            if ev_path.exists():
                ev = _load_yaml(ev_path, {})
                if isinstance(ev, dict) and ev.get("files"):
                    timeline.append(_event("evidence_consumed", "", {
                        "task_id": task_id,
                        "evidence_count": ev.get("evidence_count"),
                        "source": _rel(ev_path),
                    }))

            # approval events
            dc_dir = task_dir / "decision_cards"
            if dc_dir.is_dir():
                for card_path in sorted(dc_dir.glob("*.yml")):
                    card = _load_yaml(card_path, {})
                    if isinstance(card, dict):
                        s = card.get("status") or "pending"
                        etype = "approval_resolved" if s in ("approved", "rejected") else "approval_requested"
                        timeline.append(_event(etype,
                            str(card.get("resolved_at") or card.get("created_at") or ""), {
                                "task_id": task_id,
                                "card_file": card_path.name,
                                "status": s,
                                "source": _rel(card_path),
                            }))

            # capability_gap_raised
            cg_dir = task_dir / "capability_gaps"
            if cg_dir.is_dir() and any(cg_dir.iterdir()):
                for cg_path in sorted(cg_dir.glob("*.yml")):
                    timeline.append(_event("capability_gap_raised", "", {
                        "task_id": task_id,
                        "source": _rel(cg_path),
                    }))

            # artifact_promoted / artifact_archived
            pa_path = task_dir / "phase_acceptance.yml"
            if pa_path.exists():
                pa = _load_yaml(pa_path, {})
                if isinstance(pa, dict):
                    st = pa.get("state_transition")
                    if isinstance(st, dict):
                        ts = str(pa.get("recorded_at") or "")
                        if st.get("applied"):
                            timeline.append(_event("artifact_promoted", ts, {
                                "task_id": task_id,
                                "source": _rel(pa_path),
                            }))
                        if st.get("archive_receipt"):
                            timeline.append(_event("artifact_archived", ts, {
                                "task_id": task_id,
                                "source": _rel(pa_path),
                            }))

    # sort: entries with time first, then empty-time at end
    timeline.sort(key=lambda e: ("z" + e["time"] if not e["time"] else "a" + e["time"]))
    return timeline


def build_failure_narrative(project_root: Path, phase_id: str | None = None) -> dict[str, Any]:
    """Build a failure narrative: root cause → impact → recovery → next action.

    Aggregates all failure/recovery events related to a phase (or all phases)
    and produces a human-readable narrative with next safe action.
    """
    timeline = build_timeline(project_root)
    brain_dir = project_root / "project_brain"

    # collect failure and recovery events
    failures = [e for e in timeline if e["event_type"] in {
        "executor_result_received", "recovery_started", "recovery_resolved",
        "capability_gap_raised",
    }]
    if phase_id:
        failures = [e for e in failures
                    if e.get("data", {}).get("phase_id") == phase_id
                    or e.get("data", {}).get("task_id", "").startswith(phase_id)]

    fail_events = [e for e in failures if e["data"].get("status") == "FAIL"]
    recovery_started = [e for e in failures if e["event_type"] == "recovery_started"]
    recovery_resolved = [e for e in failures if e["event_type"] == "recovery_resolved"]
    capability_gaps = [e for e in failures if e["event_type"] == "capability_gap_raised"]

    # derive root cause from executor results
    root_causes: list[str] = []
    for fe in fail_events:
        root_causes.append(
            f"Task {fe['data'].get('task_id')} failed: executor={fe['data'].get('executor_id')}"
        )
    for cg in capability_gaps:
        root_causes.append(f"Capability gap in task {cg['data'].get('task_id')}")

    # impacted tasks
    impacted_tasks = list({e["data"].get("task_id") for e in fail_events if e["data"].get("task_id")})

    # recovery options
    recovery_options: list[str] = []
    for rr in recovery_resolved:
        action = rr["data"].get("recommended_action")
        if action:
            recovery_options.append(action)

    # next safe action from Project Brain
    next_actions = _load_yaml(brain_dir / "next_actions.yml", {})
    if isinstance(next_actions, dict):
        next_safe = next_actions.get("next_action")
    else:
        next_safe = None

    return {
        "schema_version": 1,
        "phase_id": phase_id,
        "root_cause": root_causes[0] if len(root_causes) == 1 else "; ".join(root_causes) if root_causes else "no failure events found",
        "impacted_tasks": impacted_tasks,
        "failure_count": len(fail_events),
        "recovery_in_progress": len(recovery_started) > len(recovery_resolved),
        "recovery_resolved": len(recovery_resolved) > 0,
        "recovery_options": recovery_options,
        "capability_gaps_pending": len([e for e in capability_gaps if e["data"].get("status", "") != "resolved"]),
        "next_safe_action": next_safe,
        "source_documents": {
            "acceptance_history": _rel(brain_dir / "acceptance_history.yml"),
            "next_actions": _rel(brain_dir / "next_actions.yml"),
        },
    }


def _event(event_type: str, time: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a single timeline event dict."""
    return {
        "event_type": event_type,
        "time": time,
        "data": data,
    }


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else default


def _rel(path: Path) -> str:
    return path.name
