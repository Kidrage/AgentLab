"""Collect trusted-runner results and refresh acceptance reports.

This module does not execute private role-session acceptance smoke commands. It is the post-run
collector: after a trusted runner or user terminal has run the private role-session commands,
it refreshes local status/audit reports and returns a compact verdict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml

try:
    from goal_acceptance_scope import acceptance_mode, load_goal_acceptance_scope
except ModuleNotFoundError:
    from agent_runtime.goal_acceptance_scope import acceptance_mode, load_goal_acceptance_scope


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _contains_secret_text(data: dict[str, Any]) -> bool:
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return "sk-" in rendered or "test-key" in rendered


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _request_path(root: Path, request_path: Path | None) -> Path:
    path = request_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml"
    )
    return path if path.is_absolute() else root / path


def _status_path(root: Path, request: dict[str, Any], request_path: Path) -> Path:
    package = request.get("local_runner_package") if isinstance(request.get("local_runner_package"), dict) else {}
    status_text = package.get("status_path")
    if status_text:
        path = Path(str(status_text))
        return path if path.is_absolute() else root / path
    return request_path.with_name("trusted_live_runner_status.yml")


def _pending_items(status: dict[str, Any]) -> list[dict[str, Any]]:
    items = status.get("items", []) if isinstance(status.get("items"), list) else []
    return [item for item in items if isinstance(item, dict) and item.get("status") != "pass"]


def _status_items(status: dict[str, Any]) -> list[dict[str, Any]]:
    items = status.get("items", []) if isinstance(status.get("items"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _selected_item_report(item_id: str, status_items: list[dict[str, Any]]) -> dict[str, Any]:
    selected = next((item for item in status_items if item.get("id") == item_id), None)
    if not selected:
        return {
            "selected_item_id": item_id,
            "selected_item_collect_status": "unknown_selected_item",
            "selected_item_status": "missing",
            "selected_item_accepted": False,
            "selected_item_expected_type": None,
            "selected_item_required_files_exist": False,
            "selected_item_returned_candidate_artifacts_accepted": False,
            "selected_item_acceptance_blocker": "selected_item_not_found",
            "selected_item_pending_reason": "selected_item_not_found",
            "selected_item_next_action": "check_selected_trusted_live_item_id",
            "selected_item_missing": [],
        }

    selected_status = str(selected.get("status") or "missing")
    selected_returned_accepted = selected.get("returned_candidate_artifacts_accepted") is True
    selected_accepted = selected_status == "pass" and selected_returned_accepted
    selected_acceptance_blocker = selected.get("acceptance_blocker")
    selected_pending_reason = selected.get("pending_reason")
    selected_next_action = selected.get("next_action")
    if selected_status == "pass" and not selected_returned_accepted:
        selected_acceptance_blocker = "returned_artifacts_not_accepted"
        selected_pending_reason = "status_pass_but_returned_artifacts_not_accepted"
        selected_next_action = "repair_trusted_live_runner_status_or_rerun_collect"
    selected_report = {
        "selected_item_id": item_id,
        "selected_item_collect_status": "pass" if selected_accepted else "pending_selected_item",
        "selected_item_status": selected_status,
        "selected_item_accepted": selected_accepted,
        "selected_item_expected_type": selected.get("expected_type"),
        "selected_item_required_files_exist": selected.get("required_files_exist"),
        "selected_item_returned_candidate_artifacts_accepted": selected_returned_accepted,
        "selected_item_acceptance_blocker": selected_acceptance_blocker,
        "selected_item_pending_reason": selected_pending_reason,
        "selected_item_next_action": selected_next_action,
        "selected_item_missing": selected.get("missing") or [],
    }
    if isinstance(selected.get("observed_error"), dict):
        selected_report["selected_item_observed_error"] = selected["observed_error"]
    if isinstance(selected.get("session_health_gate"), dict):
        selected_report["selected_item_session_health_gate"] = selected["session_health_gate"]
    if isinstance(selected.get("artifact_qc"), dict):
        selected_report["selected_item_artifact_qc"] = selected["artifact_qc"]
    return selected_report


def _selected_collect_path(collect_path: Path, item_id: str) -> Path:
    suffix = item_id
    prefix = "run_crown_internal_"
    if suffix.startswith(prefix):
        suffix = suffix[len(prefix):]
    for ending in ("_eval", "_smoke"):
        if suffix.endswith(ending):
            suffix = suffix[: -len(ending)]
    safe_suffix = "".join(char if char.isalnum() else "_" for char in suffix).strip("_") or "selected"
    return collect_path.with_name(f"{collect_path.stem}_{safe_suffix}{collect_path.suffix}")


def selected_collect_path(collect_path: Path, item_id: str) -> Path:
    """Return the canonical per-item collect path without writing reports."""
    return _selected_collect_path(collect_path, item_id)


def _selected_item_summaries(status_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for item in status_items:
        item_id = item.get("id")
        if item_id:
            summaries[str(item_id)] = _selected_item_report(str(item_id), status_items)
    return summaries


def _canonical_collect_path(root: Path) -> Path:
    return root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_collect.yml"


def _acceptance_summary(
    *,
    capability: dict[str, Any],
    objective: dict[str, Any],
    goal: dict[str, Any],
    hygiene: dict[str, Any],
) -> dict[str, Any]:
    return {
        "capability_overall_status": capability.get("overall_status"),
        "capability_status_counts": capability.get("status_counts"),
        "objective_status": objective.get("status"),
        "objective_status_counts": objective.get("status_counts"),
        "goal_status": goal.get("status"),
        "goal_status_counts": goal.get("status_counts"),
        "acceptance_report_hygiene_status": hygiene.get("status"),
        "acceptance_report_hygiene_canonical_text_artifact_count": hygiene.get(
            "canonical_text_artifact_count"
        ),
        "acceptance_report_hygiene_canonical_text_issue_count": len(
            hygiene.get("canonical_text_issues") or []
        ),
        "acceptance_report_hygiene_stale_private_selected_command_hit_count": len(
            hygiene.get("stale_private_selected_command_hits") or []
        ),
    }


def _refresh_acceptance_reports(root: Path) -> dict[str, dict[str, Any]]:
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    live_unblock_abs = base / "live_unblock_plan.yml"
    current_abs = base / "current.yml"
    objective_abs = base / "objective_requirement_audit.yml"
    goal_abs = base / "goal_completion_audit.yml"
    hygiene_abs = base / "acceptance_report_hygiene.yml"

    from capability_acceptance import build_capability_acceptance_report
    from acceptance_report_hygiene import sync_snapshot_aliases, write_acceptance_report_hygiene
    from goal_completion_audit import write_goal_completion_audit
    from live_unblock_plan import build_live_unblock_plan
    from objective_requirement_audit import write_objective_requirement_audit

    live_unblock = build_live_unblock_plan(root)
    write_report_yaml(live_unblock_abs, live_unblock, root)
    capability = build_capability_acceptance_report(root)
    write_report_yaml(current_abs, capability, root)
    goal = write_goal_completion_audit(root, goal_abs)
    objective = write_objective_requirement_audit(root, objective_abs)
    sync_snapshot_aliases(base)
    hygiene = write_acceptance_report_hygiene(root, hygiene_abs)
    return {
        "live_unblock": live_unblock,
        "capability": capability,
        "objective": objective,
        "goal": goal,
        "hygiene": hygiene,
    }


def build_trusted_live_runner_collect(
    root: Path,
    request_path: Path | None = None,
    item_id: str | None = None,
    *,
    refresh_acceptance_reports: bool = True,
) -> dict[str, Any]:
    """Refresh local trusted-runner acceptance reports and summarize state."""
    root = root.resolve()
    acceptance_scope = load_goal_acceptance_scope(root)
    media_live_acceptance_required = (
        acceptance_mode(acceptance_scope, "media_generation") == "full_live_acceptance"
    )
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    request_abs = _request_path(root, request_path)
    request = _read_yaml(request_abs)
    status_abs = _status_path(root, request, request_abs)
    operator_abs = base / "trusted_live_runner_operator_handoff.yml"
    live_unblock_abs = base / "live_unblock_plan.yml"
    current_abs = base / "current.yml"
    objective_abs = base / "objective_requirement_audit.yml"
    goal_abs = base / "goal_completion_audit.yml"
    hygiene_abs = base / "acceptance_report_hygiene.yml"

    from trusted_live_runner_operator_handoff import write_trusted_live_runner_operator_handoff
    from trusted_live_runner_status import write_trusted_live_runner_status

    status = write_trusted_live_runner_status(root, status_abs, request_path=request_abs)
    operator = write_trusted_live_runner_operator_handoff(root, operator_abs, request_path=request_abs)
    if refresh_acceptance_reports:
        refreshed = _refresh_acceptance_reports(root)
        capability = refreshed["capability"]
        objective = refreshed["objective"]
        goal = refreshed["goal"]
        hygiene = refreshed["hygiene"]
    else:
        capability = _read_yaml(current_abs)
        objective = _read_yaml(objective_abs)
        goal = _read_yaml(goal_abs)
        hygiene = _read_yaml(hygiene_abs)

    pending = _pending_items(status)
    stale_items = status.get("stale_items", []) if isinstance(status.get("stale_items"), list) else []
    qc_failures = (
        status.get("artifact_qc_failures", [])
        if isinstance(status.get("artifact_qc_failures"), list)
        else []
    )
    status_items = _status_items(status)
    writer_item_accepted = any(
        isinstance(item, dict)
        and item.get("id") == "run_crown_internal_writer_eval"
        and item.get("returned_candidate_artifacts_accepted") is True
        for item in status_items
    )
    unaccepted_pass_items = [
        item
        for item in status_items
        if isinstance(item, dict) and item.get("returned_candidate_artifacts_accepted") is not True
    ]
    status_pass_has_unaccepted_items = (
        status.get("status") == "pass"
        and (len(status_items) < 2 or bool(unaccepted_pass_items))
    )
    if status_pass_has_unaccepted_items:
        collect_status = "fail"
        next_action = "repair_trusted_live_runner_status_or_rerun_collect"
    elif status.get("status") == "pass" and not pending and not qc_failures:
        collect_status = "pass"
        next_action = "refresh_promotion_or_human_acceptance_gate"
    elif qc_failures:
        collect_status = "artifact_qc_failed"
        next_action = "review_returned_candidate_artifacts_or_rerun_trusted_live_command"
    else:
        collect_status = "pending_returned_artifacts"
        if not media_live_acceptance_required and writer_item_accepted:
            next_action = "scoped_acceptance_complete_deferred_media_pending"
        elif not media_live_acceptance_required:
            next_action = "run_writer_selected_item_only"
        else:
            next_action = "run_or_rerun_trusted_live_runner"

    acceptance_blockers = sorted(
        {
            str(item.get("acceptance_blocker"))
            for item in pending
            if isinstance(item, dict)
            and item.get("acceptance_blocker")
            and item.get("acceptance_blocker") != "none"
        }
    )
    if status_pass_has_unaccepted_items:
        acceptance_blockers = sorted({*acceptance_blockers, "returned_artifacts_not_accepted"})
    acceptance_blocker_reasons = sorted(
        {
            str(item.get("pending_reason"))
            for item in pending
            if isinstance(item, dict) and item.get("pending_reason")
        }
    )
    if status_pass_has_unaccepted_items:
        acceptance_blocker_reasons = sorted(
            {
                *acceptance_blocker_reasons,
                "status_pass_but_returned_artifacts_not_accepted",
            }
        )
    required_files_missing_count = sum(
        len(item.get("missing") or [])
        for item in pending
        if isinstance(item, dict) and isinstance(item.get("missing") or [], list)
    )
    returned_candidate_artifacts_accepted_count = len(
        [
            item
            for item in status_items
            if isinstance(item, dict) and item.get("returned_candidate_artifacts_accepted") is True
        ]
    )

    report = {
        "schema_version": 1,
        "report_type": "agentlab_trusted_live_runner_collect",
        "root": str(root),
        "status": collect_status,
        "source_request": _rel(root, request_abs),
        "request_id": request.get("request_id"),
        "refreshed_reports": {
            "trusted_live_runner_status": _rel(root, status_abs),
            "trusted_live_runner_operator_handoff": _rel(root, operator_abs),
            "live_unblock_plan": _rel(root, live_unblock_abs),
            "capability_acceptance": _rel(root, current_abs),
            "objective_requirement_audit": _rel(root, objective_abs),
            "goal_completion_audit": _rel(root, goal_abs),
            "acceptance_report_hygiene": _rel(root, hygiene_abs),
        },
        "trusted_live_runner_status": {
            "status": status.get("status"),
            "pending_item_count": len(pending),
            "stale_item_count": len(stale_items),
            "artifact_qc_failure_count": len(qc_failures),
        },
        "acceptance_blockers": acceptance_blockers,
        "acceptance_blocker_reasons": acceptance_blocker_reasons,
        "required_files_missing_count": required_files_missing_count,
        "returned_candidate_artifacts_accepted_count": returned_candidate_artifacts_accepted_count,
        "inconsistent_pass_items": [
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "returned_candidate_artifacts_accepted": item.get(
                    "returned_candidate_artifacts_accepted"
                ),
                "acceptance_blocker": "returned_artifacts_not_accepted",
            }
            for item in unaccepted_pass_items
        ]
        if status_pass_has_unaccepted_items
        else [],
        "pending_items": [
            {
                "id": item.get("id"),
                "expected_type": item.get("expected_type"),
                "pending_reason": item.get("pending_reason"),
                "next_action": item.get("next_action"),
                "missing": item.get("missing") or [],
                "required_files_exist": item.get("required_files_exist"),
                "returned_candidate_artifacts_accepted": item.get("returned_candidate_artifacts_accepted"),
                "acceptance_blocker": item.get("acceptance_blocker"),
            }
            for item in pending
        ],
        "acceptance_summary": _acceptance_summary(
            capability=capability,
            objective=objective,
            goal=goal,
            hygiene=hygiene,
        ),
        "operator_handoff_status": operator.get("status"),
        "next_action": next_action,
        "active_selected_item_ids": ["run_crown_internal_writer_eval"]
        if not media_live_acceptance_required
        else ["run_crown_internal_writer_eval", "run_crown_internal_media_smoke"],
        "deferred_selected_item_ids": ["run_crown_internal_media_smoke"]
        if not media_live_acceptance_required
        else [],
        "recommended_selected_command": (
            ((request.get("local_runner_package") or {}).get("selective_run_examples") or {}).get(
                "writer_only"
            )
            if not media_live_acceptance_required
            else None
        ),
        "secret_values_rendered": False,
        "notes": [
            "This collector does not run private role-session acceptance commands.",
            "It accepts returned role-session acceptance artifacts only through trusted-live-runner-status structural QC.",
            "Generated outputs remain run-local candidates until explicit promotion or human acceptance.",
            "The active acceptance scope runs Writer only; media live artifacts remain deferred."
            if not media_live_acceptance_required
            else "Writer and media live artifacts are both active acceptance items.",
        ],
    }
    selected_summaries = _selected_item_summaries(status_items)
    if item_id:
        report.update(_selected_item_report(item_id, status_items))
    else:
        report["selected_item_summaries"] = selected_summaries
    report["secret_values_rendered"] = _contains_secret_text(report)
    if report["secret_values_rendered"]:
        report["status"] = "fail"
        report["next_action"] = "remove_secret_values_from_reports"
    return report


def _materialize_selected_collect_reports(root: Path, collect_path: Path, report: dict[str, Any]) -> None:
    summaries = (
        report.get("selected_item_summaries")
        if isinstance(report.get("selected_item_summaries"), dict)
        else {}
    )
    for item_id, summary in summaries.items():
        if not isinstance(summary, dict):
            continue
        selected_report = dict(report)
        selected_report.pop("selected_item_summaries", None)
        selected_report["selected_item_report_source"] = _rel(root, collect_path)
        selected_report.update(summary)
        write_report_yaml(_selected_collect_path(collect_path, str(item_id)), selected_report, root)


def write_trusted_live_runner_collect(
    root: Path,
    out: Path,
    request_path: Path | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    out = out if out.is_absolute() else root / out
    requested_item_id = item_id
    is_canonical = out.resolve() == _canonical_collect_path(root).resolve()
    report = build_trusted_live_runner_collect(
        root,
        request_path=request_path,
        item_id=None if is_canonical else item_id,
        refresh_acceptance_reports=not is_canonical,
    )
    if is_canonical:
        summaries = (
            report.get("selected_item_summaries")
            if isinstance(report.get("selected_item_summaries"), dict)
            else {}
        )
        report["selected_item_report_paths"] = {
            str(selected_id): _rel(root, _selected_collect_path(out, str(selected_id)))
            for selected_id in summaries
        }
    write_report_yaml(out, report, root)
    if is_canonical:
        _materialize_selected_collect_reports(root, out, report)
        refreshed = _refresh_acceptance_reports(root)
        report["acceptance_summary"] = _acceptance_summary(
            capability=refreshed["capability"],
            objective=refreshed["objective"],
            goal=refreshed["goal"],
            hygiene=refreshed["hygiene"],
        )
        report["secret_values_rendered"] = _contains_secret_text(report)
        if report["secret_values_rendered"]:
            report["status"] = "fail"
            report["next_action"] = "remove_secret_values_from_reports"
        write_report_yaml(out, report, root)
        _materialize_selected_collect_reports(root, out, report)
        if requested_item_id:
            return _read_yaml(_selected_collect_path(out, requested_item_id))
    return report
