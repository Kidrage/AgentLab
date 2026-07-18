from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


CANONICAL_REPORT_TYPES = {
    "current.yml": "agentlab_capability_acceptance",
    "objective_requirement_audit.yml": "agentlab_objective_requirement_audit",
    "goal_completion_audit.yml": "agentlab_goal_completion_audit",
    "internal_live_readiness.yml": "agentlab_internal_live_readiness",
    "trusted_live_runner_request.yml": "agentlab_trusted_live_runner_request",
    "trusted_live_runner_preflight.yml": "agentlab_trusted_live_runner_preflight",
    "trusted_live_runner_operator_handoff.yml": "agentlab_trusted_live_runner_operator_handoff",
    "trusted_live_runner_status.yml": "agentlab_trusted_live_runner_status",
    "trusted_live_runner_collect.yml": "agentlab_trusted_live_runner_collect",
}

CANONICAL_TEXT_ARTIFACTS = {
    "role_session_acceptance_handoff.md": [
        "Canonical term: `private_role_session_acceptance_smoke`",
        "Legacy shorthand: `private live smoke`",
        "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1",
        "missing_candidate_artifacts",
        "ready_for_internal_live_smoke",
    ],
    "private_live_smoke_approval_handoff.md": [
        "Legacy path:",
        "role_session_acceptance_handoff.md",
        "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1",
    ],
}

CANONICAL_TEXT_FORBIDDEN_MARKERS = {
    "role_session_acceptance_handoff.md": [
        "Paste this approval before asking Codex to run the private role-session acceptance smoke",
        "我批准 Codex 在本机 trusted runner 流程中",
        "task_narrative_eval_ch01_current_writer",
        "media_backend_live_internal_current_media",
    ],
    "private_live_smoke_approval_handoff.md": [
        "Paste this approval before asking Codex to run the private role-session acceptance smoke",
        "我批准 Codex 在本机 trusted runner 流程中",
        "task_narrative_eval_ch01_current_writer",
        "media_backend_live_internal_current_media",
    ],
}

SNAPSHOT_ALIASES = {
    "current_now.yml": "current.yml",
    "current_check.yml": "current.yml",
    "capability_acceptance_now.yml": "current.yml",
    "objective_requirement_audit_now.yml": "objective_requirement_audit.yml",
    "objective_requirement_audit_check.yml": "objective_requirement_audit.yml",
    "goal_completion_audit_now.yml": "goal_completion_audit.yml",
    "internal_live_readiness_now.yml": "internal_live_readiness.yml",
    "trusted_live_runner_status_now.yml": "trusted_live_runner_status.yml",
    "agent_role_chain_audit_now.yml": "agent_role_chain_audit.yml",
    "production_chain_audit_now.yml": "production_chain_audit.yml",
    "crown_scale_governance_audit_now.yml": "crown_scale_governance_audit.yml",
    "crown_live_candidate_audit_now.yml": "crown_live_candidate_audit.yml",
}

HISTORICAL_SNAPSHOT_NAMES = {
    "agy_cli_session_smoke_now.yml",
    "grok_cli_session_smoke_now.yml",
    "grok_cli_session_smoke_for_user_check.yml",
}

STALE_MARKERS = [
    "remains blocked by missing xAI/Grok live auth",
    "hermes_grok_oauth` still has no verified live-generation adapter",
]

ROLE_SESSION_ACCEPTANCE_APPROVAL_ENV = "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1"
TRUSTED_LIVE_RUNNER_SCRIPT_MARKER = "trusted_live_runner_request.sh"
PRIVATE_SELECTED_ROLE_SESSION_ITEMS = [
    "run_crown_internal_writer_eval",
    "run_crown_internal_media_smoke",
]


def _private_selected_command_scan_artifacts() -> list[str]:
    return sorted(
        {
            *CANONICAL_REPORT_TYPES.keys(),
            *CANONICAL_TEXT_ARTIFACTS.keys(),
            "live_unblock_plan.yml",
        }
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dig(data: dict[str, Any], path: list[str]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _signature(data: dict[str, Any]) -> dict[str, Any]:
    report_type = data.get("report_type")
    base: dict[str, Any] = {
        "report_type": report_type,
        "status": data.get("status") or data.get("overall_status"),
        "status_counts": data.get("status_counts"),
    }
    if report_type == "agentlab_capability_acceptance":
        base["grok_session_auth_evidence"] = _dig(
            data,
            ["capabilities_by_id", "grok_xai_media_backend", "details", "session_auth_evidence"],
        )
        for item in data.get("capabilities", []):
            if isinstance(item, dict) and item.get("id") == "grok_xai_media_backend":
                details = item.get("details") if isinstance(item.get("details"), dict) else {}
                base["grok_session_auth_evidence"] = details.get("session_auth_evidence")
                base["grok_session_auth_healthy"] = details.get("session_auth_healthy")
                break
    if report_type == "agentlab_internal_live_readiness":
        base["session_health_issue_count"] = len(data.get("session_health_issues") or [])
    if report_type == "agentlab_trusted_live_runner_status":
        base["pending_item_ids"] = [
            item.get("id")
            for item in data.get("items", [])
            if isinstance(item, dict) and item.get("status") != "pass"
        ]
    return base


def _snapshot_staleness(base: Path) -> list[dict[str, Any]]:
    stale: list[dict[str, Any]] = []
    for snapshot_name, canonical_name in SNAPSHOT_ALIASES.items():
        snapshot_path = base / snapshot_name
        canonical_path = base / canonical_name
        if not snapshot_path.exists():
            continue
        if not canonical_path.exists():
            stale.append(
                {
                    "snapshot": str(snapshot_path.name),
                    "canonical": str(canonical_path.name),
                    "reason": "canonical_missing",
                }
            )
            continue
        snapshot = _read_yaml(snapshot_path)
        canonical = _read_yaml(canonical_path)
        snapshot_sig = _signature(snapshot)
        canonical_sig = _signature(canonical)
        mismatched_keys = [
            key
            for key, canonical_value in canonical_sig.items()
            if snapshot_sig.get(key) != canonical_value
        ]
        if mismatched_keys:
            stale.append(
                {
                    "snapshot": str(snapshot_path.name),
                    "canonical": str(canonical_path.name),
                    "reason": "signature_mismatch",
                    "mismatched_keys": mismatched_keys,
                    "snapshot_signature": snapshot_sig,
                    "canonical_signature": canonical_sig,
                }
            )
    return stale


def sync_snapshot_aliases(base: Path) -> list[dict[str, Any]]:
    """Refresh existing non-authoritative snapshot aliases from their canonical reports."""
    synced: list[dict[str, Any]] = []
    for snapshot_name, canonical_name in SNAPSHOT_ALIASES.items():
        snapshot_path = base / snapshot_name
        canonical_path = base / canonical_name
        if not snapshot_path.exists() or not canonical_path.exists():
            continue
        snapshot_path.write_text(canonical_path.read_text(encoding="utf-8"), encoding="utf-8")
        synced.append(
            {
                "snapshot": snapshot_path.name,
                "canonical": canonical_path.name,
            }
        )
    return synced


def _marker_hits(base: Path) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        markers = [marker for marker in STALE_MARKERS if marker in text]
        if markers:
            hits.append({"path": path.name, "markers": markers})
    return hits


def _private_selected_command_hits(base: Path) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for name in _private_selected_command_scan_artifacts():
        path = base / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        start = 0
        while True:
            index = text.find(TRUSTED_LIVE_RUNNER_SCRIPT_MARKER, start)
            if index == -1:
                break
            command_window = text[index : index + 260]
            matched_item = next(
                (
                    item
                    for item in PRIVATE_SELECTED_ROLE_SESSION_ITEMS
                    if f"--only {item}" in command_window
                ),
                None,
            )
            if matched_item:
                approval_window = text[max(0, index - 220) : index + len(command_window)]
                if ROLE_SESSION_ACCEPTANCE_APPROVAL_ENV not in approval_window:
                    hits.append(
                        {
                            "path": name,
                            "line": text.count("\n", 0, index) + 1,
                            "item": matched_item,
                            "reason": "selected_private_role_session_command_missing_approval_env",
                            "required_env": ROLE_SESSION_ACCEPTANCE_APPROVAL_ENV,
                        }
                    )
            start = index + len(TRUSTED_LIVE_RUNNER_SCRIPT_MARKER)
    return hits


def _canonical_text_forbidden_hits(text: str, forbidden_markers: list[str]) -> list[str]:
    return [marker for marker in forbidden_markers if marker in text]


def build_acceptance_report_hygiene(root: Path) -> dict[str, Any]:
    root = root.resolve()
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    canonical_reports: list[dict[str, Any]] = []
    canonical_issues: list[dict[str, Any]] = []
    for name, expected_type in CANONICAL_REPORT_TYPES.items():
        path = base / name
        data = _read_yaml(path)
        exists = path.exists()
        actual_type = data.get("report_type")
        item = {
            "path": _rel(root, path),
            "exists": exists,
            "expected_report_type": expected_type,
            "actual_report_type": actual_type,
        }
        canonical_reports.append(item)
        if not exists:
            canonical_issues.append({**item, "reason": "missing"})
        elif actual_type != expected_type:
            canonical_issues.append({**item, "reason": "report_type_mismatch"})

    canonical_text_artifacts: list[dict[str, Any]] = []
    canonical_text_issues: list[dict[str, Any]] = []
    for name, required_markers in CANONICAL_TEXT_ARTIFACTS.items():
        path = base / name
        exists = path.exists()
        text = path.read_text(encoding="utf-8") if exists else ""
        missing_markers = [marker for marker in required_markers if marker not in text]
        forbidden_markers = CANONICAL_TEXT_FORBIDDEN_MARKERS.get(name, [])
        forbidden_marker_hits = _canonical_text_forbidden_hits(text, forbidden_markers)
        item = {
            "path": _rel(root, path),
            "exists": exists,
            "required_markers": required_markers,
            "missing_markers": missing_markers,
            "forbidden_markers": forbidden_markers,
            "forbidden_marker_hits": forbidden_marker_hits,
        }
        canonical_text_artifacts.append(item)
        if not exists:
            canonical_text_issues.append({**item, "reason": "missing"})
        elif missing_markers:
            canonical_text_issues.append({**item, "reason": "missing_required_markers"})
        elif forbidden_marker_hits:
            canonical_text_issues.append({**item, "reason": "forbidden_markers_present"})

    snapshot_files = sorted(
        path.name
        for path in base.glob("*.yml")
        if path.name.endswith("_now.yml")
        or path.name.endswith("_check.yml")
        or path.name.endswith("_current.yml")
    )
    historical_snapshots = [name for name in snapshot_files if name in HISTORICAL_SNAPSHOT_NAMES]
    stale_snapshots = _snapshot_staleness(base)
    stale_marker_hits = _marker_hits(base)
    stale_private_selected_command_hits = _private_selected_command_hits(base)
    consistency_issues: list[dict[str, Any]] = []
    status = (
        "pass"
        if not canonical_issues
        and not canonical_text_issues
        and not stale_snapshots
        and not stale_marker_hits
        and not stale_private_selected_command_hits
        and not consistency_issues
        else "fail"
    )
    return {
        "schema_version": 1,
        "report_type": "agentlab_acceptance_report_hygiene",
        "root": str(root),
        "status": status,
        "canonical_report_count": len(canonical_reports),
        "canonical_reports": canonical_reports,
        "canonical_issues": canonical_issues,
        "canonical_text_artifact_count": len(canonical_text_artifacts),
        "canonical_text_artifacts": canonical_text_artifacts,
        "canonical_text_issues": canonical_text_issues,
        "snapshot_policy": "non_authoritative_snapshots_may_exist_but_must_not_carry_stale_current_state",
        "non_authoritative_snapshot_count": len(snapshot_files),
        "non_authoritative_snapshots": snapshot_files,
        "historical_snapshot_count": len(historical_snapshots),
        "historical_snapshots": historical_snapshots,
        "stale_snapshot_count": len(stale_snapshots),
        "stale_snapshots": stale_snapshots,
        "stale_marker_hits": stale_marker_hits,
        "private_selected_command_policy": (
            "selected private role-session commands must include "
            f"{ROLE_SESSION_ACCEPTANCE_APPROVAL_ENV}"
        ),
        "private_selected_command_scan_artifacts": _private_selected_command_scan_artifacts(),
        "stale_private_selected_command_hits": stale_private_selected_command_hits,
        "consistency_issues": consistency_issues,
        "notes": [
            "This audit does not delete historical evidence or execute live commands.",
            "Historical policy rejection files remain valid evidence; current-state snapshots must not contradict canonical reports.",
        ],
    }


def write_acceptance_report_hygiene(root: Path, out: Path) -> dict[str, Any]:
    root = root.resolve()
    out = out if out.is_absolute() else root / out
    report = build_acceptance_report_hygiene(root)
    write_report_yaml(out, report, root)
    return report
