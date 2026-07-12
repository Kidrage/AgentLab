"""Collect coalesced CLI shell session receipts and refresh acceptance reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from agent_runtime.cli_shell_coalescing_request import build_cli_shell_coalescing_runner_request
    from agent_runtime.cli_shell_coalescing_status import build_cli_shell_coalescing_status
    from agent_runtime.report_sanitizer import write_report_yaml
    from agent_runtime.runtime_hygiene.secret_scan import SECRET_PATTERNS
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from cli_shell_coalescing_request import build_cli_shell_coalescing_runner_request
    from cli_shell_coalescing_status import build_cli_shell_coalescing_status
    from report_sanitizer import write_report_yaml
    from runtime_hygiene.secret_scan import SECRET_PATTERNS


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _contains_secret_text(data: dict[str, Any]) -> bool:
    import yaml

    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return "test-key" in rendered or any(pattern.search(rendered) for pattern in SECRET_PATTERNS.values())


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_paths(
    root: Path,
    plan_path: Path,
    status_path: Path,
    request_path: Path,
    out: Path,
) -> bool:
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    expected = (
        base / "cli_shell_coalescing_plan.yml",
        base / "cli_shell_coalescing_status.yml",
        base / "cli_shell_coalescing_runner_request.yml",
        base / "cli_shell_coalescing_collect.yml",
    )
    actual = (plan_path, status_path, request_path, out)
    return all(value.resolve(strict=False) == target.resolve(strict=False) for value, target in zip(actual, expected))


def _unsafe_rejection_report(root: Path, out: Path) -> dict[str, Any]:
    report = {
        "schema_version": 1,
        "report_type": "agentlab_cli_shell_coalescing_collect",
        "root": str(root),
        "status": "unsafe_report_rejected",
        "secret_values_detected": True,
        "secret_values_rendered": False,
        "provider_calls_executed": False,
        "acceptance_refresh": {
            "performed": False,
            "reason": "unsafe_source_report_rejected_before_acceptance_refresh",
        },
        "next_action": "remove_secret_values_from_coalescing_paths_or_receipts",
    }
    write_report_yaml(out, report, root)
    return report


def _refresh_acceptance_reports(root: Path) -> dict[str, Any]:
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    current_path = base / "current.yml"
    objective_path = base / "objective_requirement_audit.yml"
    goal_path = base / "goal_completion_audit.yml"
    hygiene_path = base / "acceptance_report_hygiene.yml"

    try:
        from agent_runtime.acceptance_report_hygiene import (
            sync_snapshot_aliases,
            write_acceptance_report_hygiene,
        )
        from agent_runtime.capability_acceptance import build_capability_acceptance_report
        from agent_runtime.goal_completion_audit import write_goal_completion_audit
        from agent_runtime.objective_requirement_audit import write_objective_requirement_audit
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from acceptance_report_hygiene import sync_snapshot_aliases, write_acceptance_report_hygiene
        from capability_acceptance import build_capability_acceptance_report
        from goal_completion_audit import write_goal_completion_audit
        from objective_requirement_audit import write_objective_requirement_audit

    capability = build_capability_acceptance_report(root)
    write_report_yaml(current_path, capability, root)
    objective = write_objective_requirement_audit(root, objective_path)
    goal = write_goal_completion_audit(root, goal_path)
    sync_snapshot_aliases(base)
    hygiene = write_acceptance_report_hygiene(root, hygiene_path)
    objective = write_objective_requirement_audit(root, objective_path)
    goal = write_goal_completion_audit(root, goal_path)
    capability = build_capability_acceptance_report(root)
    write_report_yaml(current_path, capability, root)
    sync_snapshot_aliases(base)
    hygiene = write_acceptance_report_hygiene(root, hygiene_path)
    return {
        "capability": capability,
        "objective": objective,
        "goal": goal,
        "hygiene": hygiene,
        "paths": {
            "capability_acceptance": _rel(root, current_path),
            "objective_requirement_audit": _rel(root, objective_path),
            "goal_completion_audit": _rel(root, goal_path),
            "acceptance_report_hygiene": _rel(root, hygiene_path),
        },
    }


def _acceptance_summary(refreshed: dict[str, Any]) -> dict[str, Any]:
    capability = refreshed.get("capability") if isinstance(refreshed.get("capability"), dict) else {}
    objective = refreshed.get("objective") if isinstance(refreshed.get("objective"), dict) else {}
    goal = refreshed.get("goal") if isinstance(refreshed.get("goal"), dict) else {}
    hygiene = refreshed.get("hygiene") if isinstance(refreshed.get("hygiene"), dict) else {}
    return {
        "capability_overall_status": capability.get("overall_status"),
        "capability_status_counts": capability.get("status_counts"),
        "objective_status": objective.get("status"),
        "objective_status_counts": objective.get("status_counts"),
        "goal_status": goal.get("status"),
        "goal_status_counts": goal.get("status_counts"),
        "acceptance_report_hygiene_status": hygiene.get("status"),
    }


def build_cli_shell_coalescing_collect(
    root: Path,
    plan_path: Path | None = None,
    status_path: Path | None = None,
    request_path: Path | None = None,
    out: Path | None = None,
) -> dict[str, Any]:
    """Refresh coalesced shell receipt status and acceptance reports."""
    root = root.resolve()
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    plan_path = plan_path or base / "cli_shell_coalescing_plan.yml"
    status_path = status_path or base / "cli_shell_coalescing_status.yml"
    request_path = request_path or base / "cli_shell_coalescing_runner_request.yml"
    out = out or base / "cli_shell_coalescing_collect.yml"
    if not plan_path.is_absolute():
        plan_path = root / plan_path
    if not status_path.is_absolute():
        status_path = root / status_path
    if not request_path.is_absolute():
        request_path = root / request_path
    if not out.is_absolute():
        out = root / out

    status = build_cli_shell_coalescing_status(root, plan_path=plan_path)
    if _contains_secret_text(status):
        return _unsafe_rejection_report(root, out)
    write_report_yaml(status_path, status, root)
    request = build_cli_shell_coalescing_runner_request(root, plan_path=plan_path, status_path=status_path)
    if _contains_secret_text(request):
        return _unsafe_rejection_report(root, out)
    write_report_yaml(request_path, request, root)
    missing_count = int(status.get("missing_returned_files_count") or 0)
    stale_count = int(status.get("stale_returned_files_count") or 0)
    failure_count = int(status.get("failure_count") or 0)
    if status.get("status") == "pass":
        collect_status = "pass"
        next_action = "refresh_promotion_or_human_acceptance_gate"
    elif status.get("status") == "fail" and failure_count:
        collect_status = "artifact_qc_failed"
        next_action = "repair_failed_shell_or_role_receipts"
    elif status.get("status") == "pending_returned_artifacts":
        collect_status = "pending_returned_artifacts"
        next_action = "run_trusted_shell_sessions_and_return_receipts"
    else:
        collect_status = "invalid_coalescing_state"
        next_action = "repair_coalescing_plan_or_status_before_collect"

    canonical = _canonical_paths(root, plan_path, status_path, request_path, out)
    acceptance_paths = {
        "capability_acceptance": _rel(root, base / "current.yml"),
        "objective_requirement_audit": _rel(root, base / "objective_requirement_audit.yml"),
        "goal_completion_audit": _rel(root, base / "goal_completion_audit.yml"),
        "acceptance_report_hygiene": _rel(root, base / "acceptance_report_hygiene.yml"),
    }

    report = {
        "schema_version": 1,
        "report_type": "agentlab_cli_shell_coalescing_collect",
        "root": str(root),
        "status": collect_status,
        "source_plan": _rel(root, plan_path),
        "source_status": _rel(root, status_path),
        "source_request": _rel(root, request_path),
        "refreshed_reports": {
            "cli_shell_coalescing_status": _rel(root, status_path),
            "cli_shell_coalescing_runner_request": _rel(root, request_path),
            **acceptance_paths,
        },
        "coalescing_status": {
            "status": status.get("status"),
            "expected_packet_count": status.get("expected_packet_count", 0),
            "accepted_packet_count": status.get("accepted_packet_count", 0),
            "delegated_role_count": status.get("delegated_role_count", 0),
            "accepted_role_count": status.get("accepted_role_count", 0),
            "missing_returned_files_count": missing_count,
            "stale_returned_files_count": stale_count,
            "failure_count": failure_count,
        },
        "runner_request_status": request.get("status"),
        "source_report_sha256": {
            "cli_shell_coalescing_status": _sha256(status_path),
            "cli_shell_coalescing_runner_request": _sha256(request_path),
        },
        "missing_returned_files": status.get("missing_returned_files", []),
        "stale_returned_files": status.get("stale_returned_files", []),
        "failure_items": status.get("failures", []),
        "secret_values_rendered": False,
        "provider_calls_executed": False,
        "acceptance_refresh": {
            "performed": canonical,
            "reason": (
                "canonical_collector_refresh"
                if canonical
                else "noncanonical_paths_do_not_refresh_canonical_acceptance"
            ),
        },
        "next_action": next_action,
    }
    if not canonical:
        for key in acceptance_paths:
            report["refreshed_reports"].pop(key, None)
    report["secret_values_rendered"] = _contains_secret_text(report)
    if report["secret_values_rendered"]:
        return _unsafe_rejection_report(root, out)
    write_report_yaml(out, report, root)

    if canonical:
        refreshed = _refresh_acceptance_reports(root)
        report["refreshed_reports"].update(refreshed["paths"])
        report["acceptance_summary"] = _acceptance_summary(refreshed)
        report["secret_values_rendered"] = _contains_secret_text(report)
        if report["secret_values_rendered"]:
            return _unsafe_rejection_report(root, out)
        write_report_yaml(out, report, root)
    return report


def write_cli_shell_coalescing_collect(
    root: Path,
    out: Path,
    plan_path: Path | None = None,
    status_path: Path | None = None,
    request_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    out = out if out.is_absolute() else root / out
    return build_cli_shell_coalescing_collect(
        root,
        plan_path=plan_path,
        status_path=status_path,
        request_path=request_path,
        out=out,
    )
