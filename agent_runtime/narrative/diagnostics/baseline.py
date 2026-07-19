"""Historical and live efficiency baseline collection for narrative workflows."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import yaml

from agent_runtime.atomic_io import atomic_write_json


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError):
        return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _metric(
    value: Any,
    unit: str,
    measurement: str,
    source: Sequence[str],
    confidence: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "measurement": measurement,
        "source": list(source),
        "confidence": confidence,
    }


def _seconds(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        return (
            datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
        ).total_seconds()
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _integer(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _evidence_path(path: Path, root: Path | None) -> str:
    """Return a portable evidence locator without exposing a workstation path."""

    path = Path(path)
    if root is not None:
        try:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return path.as_posix() if not path.is_absolute() else path.name


def _provider_commands(run_dir: Path) -> list[dict[str, Any]]:
    log = _load_yaml(run_dir / "execution_log.yml")
    return [
        _mapping(command)
        for command in log.get("commands", [])
        if isinstance(command, Mapping)
        and not command.get("dry_run")
        and bool(command.get("cli_agent") or command.get("provider"))
    ]


def _execution_span(run_dir: Path) -> float | None:
    log = _load_yaml(run_dir / "execution_log.yml")
    commands = [
        _mapping(command)
        for command in log.get("commands", [])
        if isinstance(command, Mapping)
    ]
    starts = [str(item["started_at"]) for item in commands if item.get("started_at")]
    ends = [str(item["completed_at"]) for item in commands if item.get("completed_at")]
    if not starts or not ends:
        return None
    return _seconds(min(starts), max(ends))


def _stage_timings(lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    timings: dict[str, Any] = {}
    for stage, value in _mapping(lifecycle.get("nodes")).items():
        node = _mapping(value)
        duration = _seconds(node.get("started_at"), node.get("completed_at"))
        timings[str(stage)] = {
            "status": node.get("status"),
            "seconds": round(duration, 6) if duration is not None else None,
            "measurement": "exact" if duration is not None else "missing",
        }
    return timings


def _paid_ledger_entries(run_dir: Path) -> list[dict[str, Any]]:
    ledger = _load_yaml(run_dir / "cost_ledger.yml")
    return [
        _mapping(entry)
        for entry in ledger.get("entries", [])
        if isinstance(entry, Mapping)
        and not entry.get("dry_run")
        and entry.get("usage_source") != "no_llm_call"
    ]


def _unique_receipts(run_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    receipts: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for path in sorted(run_dir.glob("model_execution_receipt_*.yml")):
        receipt = _load_yaml(path)
        identity = str(
            receipt.get("provider_reported_session_id")
            or receipt.get("attempt_id")
            or path.name
        )
        if identity in seen:
            continue
        seen.add(identity)
        receipts.append((path, receipt))
    return receipts


def _context_snapshot(
    run_dir: Path, *, evidence_root: Path | None = None
) -> dict[str, Any]:
    manifests: list[tuple[Path, dict[str, Any]]] = [
        (path, _load_yaml(path))
        for path in sorted(run_dir.glob("outbound_context_manifest_*.yml"))
    ]
    payload_bytes = 0
    source_bytes = 0
    source_occurrences: list[dict[str, Any]] = []
    by_role: dict[str, Any] = {}
    for path, manifest in manifests:
        payload = _mapping(manifest.get("payload"))
        inventory = _mapping(manifest.get("source_inventory"))
        files = [
            _mapping(item)
            for item in inventory.get("files", [])
            if isinstance(item, Mapping)
        ]
        role = str(
            manifest.get("role")
            or path.stem.removeprefix("outbound_context_manifest_").title()
        )
        role_source_bytes = sum(_integer(item.get("bytes")) for item in files)
        role_payload_bytes = _integer(payload.get("bytes"))
        payload_bytes += role_payload_bytes
        source_bytes += role_source_bytes
        source_occurrences.extend(files)
        by_role[role] = {
            "payload_bytes": role_payload_bytes,
            "payload_sha256": payload.get("sha256"),
            "source_count": _integer(inventory.get("count")) or len(files),
            "source_bytes": role_source_bytes,
            "manifest": _evidence_path(path, evidence_root),
        }

    unique_sources: dict[str, int] = {}
    for index, item in enumerate(source_occurrences):
        identity = str(item.get("sha256") or item.get("path") or f"unknown-{index}")
        unique_sources.setdefault(identity, _integer(item.get("bytes")))
    unique_bytes = sum(unique_sources.values())
    duplicated_bytes = max(0, source_bytes - unique_bytes)
    duplicate_ratio = (
        round(duplicated_bytes / source_bytes, 6) if source_bytes else None
    )
    return {
        "manifest_count": len(manifests),
        "payload_bytes": payload_bytes,
        "source_bytes": source_bytes,
        "unique_source_bytes": unique_bytes,
        "duplicated_source_bytes": duplicated_bytes,
        "duplicate_ratio": duplicate_ratio,
        "by_role": by_role,
        "sources": [_evidence_path(path, evidence_root) for path, _ in manifests],
        "source_occurrences": source_occurrences,
    }


def _finding_snapshot(run_dir: Path) -> dict[str, Any]:
    fiction = _load_yaml(run_dir / "fiction_review.yml")
    continuity = _load_yaml(run_dir / "continuity_failure_report.yml")
    revision = _load_yaml(run_dir / "revision_or_rewrite_proposal.yml")
    findings = [
        _mapping(item)
        for item in fiction.get("findings", [])
        if isinstance(item, Mapping)
    ]
    failures = [
        _mapping(item)
        for item in continuity.get("failures", [])
        if isinstance(item, Mapping)
    ]
    proposals = [
        _mapping(item)
        for item in revision.get("proposals", [])
        if isinstance(item, Mapping)
    ]
    evidence_findings = [
        item
        for item in findings
        if (item.get("evidence") or item.get("evidence_anchor"))
        and (
            item.get("location")
            or item.get("locator")
            or item.get("chapter") is not None
        )
    ]
    finding_ids = {
        str(item.get("finding_id") or item.get("issue_id") or "").strip()
        for item in findings
        if str(item.get("finding_id") or item.get("issue_id") or "").strip()
    }
    finding_fingerprints = {
        hashlib.sha256(
            json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        for item in findings
    }
    proposal_refs = {
        str(reference).strip()
        for proposal in proposals
        for reference in (
            proposal.get("finding_refs") or proposal.get("issue_refs") or []
        )
        if str(reference).strip()
    }
    return {
        "fiction_status": fiction.get("status"),
        "continuity_status": continuity.get("status"),
        "findings_count": len(findings),
        "unique_findings_count": len(finding_fingerprints),
        "blocking_findings_count": sum(
            str(item.get("severity", "")).lower() == "blocking" for item in findings
        ),
        "findings_with_exact_evidence_count": len(evidence_findings),
        "continuity_failures_count": len(failures),
        "revision_proposals_count": len(proposals),
        "findings_with_revision_proposal_count": len(finding_ids & proposal_refs),
        "findings_resulting_in_actual_revision_count": None,
        "findings_resolved_after_rewrite_count": None,
        "new_regressions_after_rewrite_count": None,
        "uplift_measurement": "missing_cross_version_finding_lineage",
        "rewrite_required": revision.get("rewrite_required"),
    }


def collect_run_metrics(
    run_dir: Path, *, evidence_root: Path | None = None
) -> dict[str, Any]:
    """Collect evidence-labelled metrics from one immutable historical run."""

    run_dir = Path(run_dir)
    execution_source = _evidence_path(run_dir / "execution_log.yml", evidence_root)
    lifecycle_source = _evidence_path(run_dir / "lifecycle.yml", evidence_root)
    ledger_source = _evidence_path(run_dir / "cost_ledger.yml", evidence_root)
    provider_commands = _provider_commands(run_dir)
    ledger_entries = _paid_ledger_entries(run_dir)
    receipts = _unique_receipts(run_dir)
    context = _context_snapshot(run_dir, evidence_root=evidence_root)
    findings = _finding_snapshot(run_dir)

    provider_process_seconds_values = [
        value
        for value in (
            _seconds(command.get("started_at"), command.get("completed_at"))
            for command in provider_commands
        )
        if value is not None
    ]
    provider_process_seconds = round(sum(provider_process_seconds_values), 6)
    lifecycle = _load_yaml(run_dir / "lifecycle.yml")
    wall_seconds = _seconds(lifecycle.get("created_at"), lifecycle.get("updated_at"))
    wall_measurement = "exact"
    if wall_seconds is None:
        wall_seconds = _execution_span(run_dir)
        wall_measurement = "lower_bound" if wall_seconds is not None else "missing"
    if wall_seconds is not None:
        wall_seconds = round(wall_seconds, 6)
    non_provider_seconds = (
        round(max(0.0, wall_seconds - provider_process_seconds), 6)
        if wall_seconds is not None
        else None
    )

    usage_rows = [
        _mapping(receipt.get("provider_reported_usage")) for _, receipt in receipts
    ]
    usage_by_role: dict[str, dict[str, Any]] = {}
    for _, receipt in receipts:
        role = str(receipt.get("role") or "unknown")
        usage = _mapping(receipt.get("provider_reported_usage"))
        current = usage_by_role.setdefault(
            role,
            {
                "receipt_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "unpriced_receipt_count": 0,
                "selected_models": [],
            },
        )
        current["receipt_count"] += 1
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "total_tokens",
        ):
            current[key] += _integer(usage.get(key))
        if isinstance(usage.get("estimated_cost"), (int, float)):
            current["cost_usd"] = round(
                current["cost_usd"] + _number(usage.get("estimated_cost")), 6
            )
        else:
            current["unpriced_receipt_count"] += 1
        model = receipt.get("selected_model_id")
        if model and model not in current["selected_models"]:
            current["selected_models"].append(model)
    receipt_input = sum(_integer(row.get("input_tokens")) for row in usage_rows)
    receipt_output = sum(_integer(row.get("output_tokens")) for row in usage_rows)
    receipt_cache_read = sum(
        _integer(row.get("cache_read_input_tokens")) for row in usage_rows
    )
    receipt_total = sum(_integer(row.get("total_tokens")) for row in usage_rows)
    receipt_cost_values = [
        _number(row.get("estimated_cost"))
        for row in usage_rows
        if isinstance(row.get("estimated_cost"), (int, float))
    ]
    receipt_cost = round(sum(receipt_cost_values), 6)
    unpriced_receipts = sum(
        not isinstance(row.get("estimated_cost"), (int, float)) for row in usage_rows
    )
    all_model_tokens = 0
    all_model_breakdown_available = 0
    for row in usage_rows:
        breakdown = _mapping(row.get("provider_reported_model_usage"))
        if breakdown:
            all_model_breakdown_available += 1
            all_model_tokens += sum(
                _integer(_mapping(model_usage).get("total_tokens"))
                for model_usage in breakdown.values()
            )
        else:
            all_model_tokens += _integer(row.get("total_tokens"))

    call_count = len(provider_commands)
    ledger_call_count = len(ledger_entries)
    unledgered_calls = max(0, call_count - ledger_call_count)
    ledger_input = sum(_integer(row.get("input_tokens")) for row in ledger_entries)
    ledger_output = sum(_integer(row.get("output_tokens")) for row in ledger_entries)
    ledger_total = sum(_integer(row.get("total_tokens")) for row in ledger_entries)
    ledger_cost_values = [
        _number(row.get("estimated_cost"))
        for row in ledger_entries
        if isinstance(row.get("estimated_cost"), (int, float))
    ]
    ledger_unpriced = sum(
        not isinstance(row.get("estimated_cost"), (int, float))
        for row in ledger_entries
    )
    ledger_usage_exact = all(
        row.get("exact_usage_available") is not False for row in ledger_entries
    )
    provider_process_by_role: dict[str, float] = {}
    for command in provider_commands:
        duration = _seconds(command.get("started_at"), command.get("completed_at"))
        if duration is None:
            continue
        role = str(command.get("agent") or command.get("node") or "unknown")
        provider_process_by_role[role] = round(
            provider_process_by_role.get(role, 0.0) + duration,
            6,
        )
    receipt_sources = [_evidence_path(path, evidence_root) for path, _ in receipts]
    context_sources = context["sources"]
    return {
        "run_dir": _evidence_path(run_dir, evidence_root),
        "wall_clock_seconds": _metric(
            wall_seconds,
            "seconds",
            wall_measurement,
            [lifecycle_source if wall_measurement == "exact" else execution_source],
            (
                "high"
                if wall_measurement == "exact"
                else "medium" if wall_seconds is not None else "low"
            ),
        ),
        "model_active_seconds": _metric(
            None,
            "seconds",
            "missing_provider_compute_field",
            [],
            "low",
        ),
        "provider_process_wall_seconds": _metric(
            provider_process_seconds,
            "seconds",
            (
                "exact_cli_process_wall"
                if len(provider_process_seconds_values) == call_count
                else "lower_bound"
            ),
            [execution_source],
            "high" if len(provider_process_seconds_values) == call_count else "medium",
        ),
        "non_provider_wall_seconds": _metric(
            non_provider_seconds,
            "seconds",
            "derived" if non_provider_seconds is not None else "missing",
            [lifecycle_source, execution_source],
            "medium" if non_provider_seconds is not None else "low",
        ),
        "model_call_count": _metric(
            call_count, "calls", "exact", [execution_source], "high"
        ),
        "cost_ledger_call_count": _metric(
            ledger_call_count, "calls", "exact", [ledger_source], "high"
        ),
        "unledgered_model_call_count": _metric(
            unledgered_calls,
            "calls",
            "derived",
            [execution_source, ledger_source],
            "high",
        ),
        "ledger_input_tokens": _metric(
            ledger_input,
            "tokens",
            "exact" if ledger_usage_exact else "derived",
            [ledger_source],
            "high" if ledger_usage_exact else "medium",
        ),
        "ledger_output_tokens": _metric(
            ledger_output,
            "tokens",
            "exact" if ledger_usage_exact else "derived",
            [ledger_source],
            "high" if ledger_usage_exact else "medium",
        ),
        "ledger_total_tokens": _metric(
            ledger_total,
            "tokens",
            "exact" if ledger_usage_exact else "derived",
            [ledger_source],
            "high" if ledger_usage_exact else "medium",
        ),
        "ledger_cost_usd": _metric(
            round(sum(ledger_cost_values), 6),
            "USD",
            "lower_bound" if ledger_unpriced else "exact",
            [ledger_source],
            "medium" if ledger_unpriced else "high",
        ),
        "ledger_unpriced_call_count": _metric(
            ledger_unpriced, "calls", "exact", [ledger_source], "high"
        ),
        "model_receipt_count": _metric(
            len(receipts), "receipts", "exact", receipt_sources, "high"
        ),
        "receipt_input_tokens": _metric(
            receipt_input, "tokens", "exact", receipt_sources, "high"
        ),
        "receipt_output_tokens": _metric(
            receipt_output, "tokens", "exact", receipt_sources, "high"
        ),
        "receipt_cache_read_tokens": _metric(
            receipt_cache_read, "tokens", "exact", receipt_sources, "high"
        ),
        "receipt_total_tokens": _metric(
            receipt_total, "tokens", "exact", receipt_sources, "high"
        ),
        "all_model_total_tokens": _metric(
            all_model_tokens,
            "tokens",
            "exact" if all_model_breakdown_available == len(receipts) else "derived",
            receipt_sources,
            "high" if all_model_breakdown_available == len(receipts) else "medium",
        ),
        "receipt_cost_usd": _metric(
            receipt_cost,
            "USD",
            "exact" if not unpriced_receipts else "lower_bound",
            receipt_sources,
            "high" if not unpriced_receipts else "medium",
        ),
        "unpriced_receipt_count": _metric(
            unpriced_receipts, "receipts", "exact", receipt_sources, "high"
        ),
        "context_manifest_count": _metric(
            context["manifest_count"], "manifests", "exact", context_sources, "high"
        ),
        "context_payload_bytes": _metric(
            context["payload_bytes"], "bytes", "exact", context_sources, "high"
        ),
        "context_source_bytes": _metric(
            context["source_bytes"], "bytes", "exact", context_sources, "high"
        ),
        "duplicated_context_bytes": _metric(
            context["duplicated_source_bytes"],
            "bytes",
            "lower_bound",
            context_sources,
            "medium",
        ),
        "duplicated_context_ratio": _metric(
            context["duplicate_ratio"],
            "ratio",
            "lower_bound" if context["duplicate_ratio"] is not None else "missing",
            context_sources,
            "medium" if context["duplicate_ratio"] is not None else "low",
        ),
        "context_by_role": context["by_role"],
        "usage_by_role": usage_by_role,
        "provider_process_by_role_seconds": provider_process_by_role,
        "stage_timings": _stage_timings(lifecycle),
        "findings": findings,
    }


def aggregate_case_metrics(
    run_dirs: Sequence[Path], *, evidence_root: Path | None = None
) -> dict[str, Any]:
    """Aggregate a frozen case while retaining evidence and measurement quality."""

    paths = [Path(path) for path in run_dirs]
    runs = [
        collect_run_metrics(path, evidence_root=evidence_root) for path in paths
    ]
    run_sources = [_evidence_path(path, evidence_root) for path in paths]

    def summed(key: str) -> float:
        return sum(_number(run[key]["value"]) for run in runs)

    context_snapshots = [
        _context_snapshot(path, evidence_root=evidence_root) for path in paths
    ]
    occurrences = [
        item
        for snapshot in context_snapshots
        for item in snapshot["source_occurrences"]
    ]
    context_source_bytes = sum(_integer(item.get("bytes")) for item in occurrences)
    unique_sources: dict[str, int] = {}
    for index, item in enumerate(occurrences):
        identity = str(item.get("sha256") or item.get("path") or f"unknown-{index}")
        unique_sources.setdefault(identity, _integer(item.get("bytes")))
    duplicated_context_bytes = max(
        0, context_source_bytes - sum(unique_sources.values())
    )
    duplicate_ratio = (
        round(duplicated_context_bytes / context_source_bytes, 6)
        if context_source_bytes
        else None
    )

    context_by_role: dict[str, dict[str, Any]] = {}
    for snapshot in context_snapshots:
        for role, role_data in snapshot["by_role"].items():
            current = context_by_role.setdefault(
                role,
                {
                    "invocation_count": 0,
                    "payload_bytes": 0,
                    "source_count": 0,
                    "source_bytes": 0,
                },
            )
            current["invocation_count"] += 1
            current["payload_bytes"] += _integer(role_data.get("payload_bytes"))
            current["source_count"] += _integer(role_data.get("source_count"))
            current["source_bytes"] += _integer(role_data.get("source_bytes"))

    usage_by_role: dict[str, dict[str, Any]] = {}
    for run in runs:
        for role, role_data in run["usage_by_role"].items():
            current = usage_by_role.setdefault(
                role,
                {
                    "receipt_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "unpriced_receipt_count": 0,
                    "selected_models": [],
                },
            )
            for key in (
                "receipt_count",
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
                "total_tokens",
                "unpriced_receipt_count",
            ):
                current[key] += _integer(role_data.get(key))
            current["cost_usd"] = round(
                current["cost_usd"] + _number(role_data.get("cost_usd")), 6
            )
            for model in role_data.get("selected_models", []):
                if model not in current["selected_models"]:
                    current["selected_models"].append(model)

    retry_count = 0
    provider_failure_count = 0
    provider_rotation_count = 0
    for path in paths:
        commands = _provider_commands(path)
        calls_by_role: dict[str, int] = {}
        for command in commands:
            role = str(command.get("agent") or command.get("node") or "unknown")
            calls_by_role[role] = calls_by_role.get(role, 0) + 1
            if command.get("exit_code") not in (None, 0) or command.get("status") in {
                "failed",
                "error",
            }:
                provider_failure_count += 1
        retry_count += sum(max(0, count - 1) for count in calls_by_role.values())

        routes_by_role: dict[str, set[tuple[str, str]]] = {}
        for _, receipt in _unique_receipts(path):
            role = str(receipt.get("role") or "unknown")
            routes_by_role.setdefault(role, set()).add(
                (
                    str(receipt.get("selected_provider") or "unknown"),
                    str(receipt.get("selected_model_id") or "unknown"),
                )
            )
        provider_rotation_count += sum(
            max(0, len(routes) - 1) for routes in routes_by_role.values()
        )

    candidate_produced_count = sum(
        (path / "fiction_draft.md").is_file() for path in paths
    )
    audit_eligible_count = sum(
        all(
            (path / name).is_file()
            for name in (
                "fiction_draft.md",
                "continuity_ledger.yml",
                "state_transition_proposal.yml",
            )
        )
        for path in paths
    )
    wall = round(summed("wall_clock_seconds"), 6)
    provider_process = round(summed("provider_process_wall_seconds"), 6)
    non_provider = round(summed("non_provider_wall_seconds"), 6)
    unpriced = int(summed("unpriced_receipt_count"))
    wall_measurements = {run["wall_clock_seconds"]["measurement"] for run in runs}
    aggregate_wall_measurement = (
        "exact"
        if wall_measurements == {"exact"}
        else (
            "missing" if wall_measurements == {"missing"} or not runs else "lower_bound"
        )
    )
    return {
        "run_count": _metric(len(paths), "runs", "exact", run_sources, "high"),
        "wall_clock_seconds": _metric(
            wall if aggregate_wall_measurement != "missing" else None,
            "seconds",
            aggregate_wall_measurement,
            run_sources,
            (
                "high"
                if aggregate_wall_measurement == "exact"
                else "medium" if aggregate_wall_measurement == "lower_bound" else "low"
            ),
        ),
        "model_active_seconds": _metric(
            None, "seconds", "missing_provider_compute_field", [], "low"
        ),
        "provider_process_wall_seconds": _metric(
            provider_process,
            "seconds",
            "exact_cli_process_wall",
            run_sources,
            "high",
        ),
        "non_provider_wall_seconds": _metric(
            non_provider, "seconds", "derived", run_sources, "medium"
        ),
        "model_call_count": _metric(
            int(summed("model_call_count")), "calls", "exact", run_sources, "high"
        ),
        "cost_ledger_call_count": _metric(
            int(summed("cost_ledger_call_count")),
            "calls",
            "exact",
            run_sources,
            "high",
        ),
        "unledgered_model_call_count": _metric(
            int(summed("unledgered_model_call_count")),
            "calls",
            "derived",
            run_sources,
            "high",
        ),
        "ledger_input_tokens": _metric(
            int(summed("ledger_input_tokens")),
            "tokens",
            "derived",
            run_sources,
            "medium",
        ),
        "ledger_output_tokens": _metric(
            int(summed("ledger_output_tokens")),
            "tokens",
            "derived",
            run_sources,
            "medium",
        ),
        "ledger_total_tokens": _metric(
            int(summed("ledger_total_tokens")),
            "tokens",
            "derived",
            run_sources,
            "medium",
        ),
        "ledger_cost_usd": _metric(
            round(summed("ledger_cost_usd"), 6),
            "USD",
            "lower_bound" if summed("ledger_unpriced_call_count") else "exact",
            run_sources,
            "medium" if summed("ledger_unpriced_call_count") else "high",
        ),
        "ledger_unpriced_call_count": _metric(
            int(summed("ledger_unpriced_call_count")),
            "calls",
            "exact",
            run_sources,
            "high",
        ),
        "retry_count": _metric(
            retry_count, "retries", "derived", run_sources, "medium"
        ),
        "provider_failure_count": _metric(
            provider_failure_count, "calls", "exact", run_sources, "high"
        ),
        "provider_rotation_count": _metric(
            provider_rotation_count, "rotations", "derived", run_sources, "medium"
        ),
        "receipt_input_tokens": _metric(
            int(summed("receipt_input_tokens")), "tokens", "exact", run_sources, "high"
        ),
        "receipt_output_tokens": _metric(
            int(summed("receipt_output_tokens")), "tokens", "exact", run_sources, "high"
        ),
        "receipt_cache_read_tokens": _metric(
            int(summed("receipt_cache_read_tokens")),
            "tokens",
            "exact",
            run_sources,
            "high",
        ),
        "receipt_total_tokens": _metric(
            int(summed("receipt_total_tokens")), "tokens", "exact", run_sources, "high"
        ),
        "all_model_total_tokens": _metric(
            int(summed("all_model_total_tokens")),
            "tokens",
            "derived",
            run_sources,
            "medium",
        ),
        "receipt_cost_usd": _metric(
            round(summed("receipt_cost_usd"), 6),
            "USD",
            "lower_bound" if unpriced else "exact",
            run_sources,
            "medium" if unpriced else "high",
        ),
        "unpriced_receipt_count": _metric(
            unpriced, "receipts", "exact", run_sources, "high"
        ),
        "context_payload_bytes": _metric(
            sum(snapshot["payload_bytes"] for snapshot in context_snapshots),
            "bytes",
            "exact",
            run_sources,
            "high",
        ),
        "context_source_bytes": _metric(
            context_source_bytes, "bytes", "exact", run_sources, "high"
        ),
        "duplicated_context_bytes": _metric(
            duplicated_context_bytes,
            "bytes",
            "lower_bound",
            run_sources,
            "medium",
        ),
        "duplicated_context_ratio": _metric(
            duplicate_ratio,
            "ratio",
            "lower_bound" if duplicate_ratio is not None else "missing",
            run_sources,
            "medium" if duplicate_ratio is not None else "low",
        ),
        "context_by_role": context_by_role,
        "usage_by_role": usage_by_role,
        "candidate_produced_count": _metric(
            candidate_produced_count, "candidates", "exact", run_sources, "high"
        ),
        "audit_eligible_candidate_count": _metric(
            audit_eligible_count, "candidates", "exact", run_sources, "high"
        ),
        "final_usable_candidate_count": _metric(
            None, "candidates", "missing", [], "low"
        ),
        "queue_wait_seconds": _metric(None, "seconds", "missing", [], "low"),
    }


def collect_background_job_metrics(
    directory: Path, *, evidence_root: Path | None = None
) -> dict[str, Any]:
    """Measure persisted scheduling/capacity waits without guessing from process time."""

    event_path = Path(directory) / "job_events.jsonl"
    events: list[dict[str, Any]] = []
    if event_path.is_file():
        for line in event_path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                events.append(dict(value))

    ready_since: str | None = None
    wait_kind: str | None = None
    scheduling_wait_seconds = 0.0
    capacity_wait_seconds = 0.0
    retry_wait_seconds = 0.0
    measured_intervals = 0
    for event in events:
        event_type = str(event.get("event_type") or "")
        status = str(event.get("status") or "")
        recorded_at = str(event.get("recorded_at") or "")
        if event_type == "ATTEMPT_SCHEDULED" and ready_since:
            duration = _seconds(ready_since, recorded_at)
            if duration is not None:
                measured_intervals += 1
                if wait_kind == "capacity_wait":
                    capacity_wait_seconds += duration
                elif wait_kind == "retry_wait":
                    retry_wait_seconds += duration
                else:
                    scheduling_wait_seconds += duration
            ready_since = None
            wait_kind = None
            continue
        if event_type == "JOB_CREATED" or (
            event_type
            in {
                "RECEIPT_CONSUMED",
                "BLOCKED_JOB_REOPENED_AFTER_REPAIR",
                "CAPACITY_WAIT_RESUMED",
                "RETRY_WAIT_RESUMED",
            }
            and status in {"queued", "failed_recoverable", "capacity_wait", "retry_wait"}
        ):
            ready_since = recorded_at
            wait_kind = status if status in {"capacity_wait", "retry_wait"} else "queue"

    source = [_evidence_path(event_path, evidence_root)] if event_path.is_file() else []
    return {
        "job_dir": _evidence_path(Path(directory), evidence_root),
        "event_count": _metric(len(events), "events", "exact", source, "high"),
        "attempt_scheduled_count": _metric(
            sum(event.get("event_type") == "ATTEMPT_SCHEDULED" for event in events),
            "attempts",
            "exact",
            source,
            "high",
        ),
        "queue_wait_seconds": _metric(
            round(scheduling_wait_seconds, 6),
            "seconds",
            "derived_from_persisted_state_events",
            source,
            "medium",
        ),
        "capacity_wait_seconds": _metric(
            round(capacity_wait_seconds, 6),
            "seconds",
            "derived_from_persisted_state_events",
            source,
            "medium",
        ),
        "retry_wait_seconds": _metric(
            round(retry_wait_seconds, 6),
            "seconds",
            "derived_from_persisted_state_events",
            source,
            "medium",
        ),
        "measured_wait_intervals": measured_intervals,
        "open_wait_interval": ready_since is not None,
    }


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def collect_known_issue_checks() -> list[dict[str, Any]]:
    """Replay the two Phase 0 red signals without repairing their behavior."""

    checks: list[dict[str, Any]] = []
    request = (
        "审计 Crown_of_Ash 第 1-10 章候选稿。全面检查连续性、人物状态、关系与势力变化、"
        "伏笔、时间线、POV 和风格漂移。只审查已有正文；不得重写正文、写 production 或自动 "
        "promotion。发现 blocking issue 时只生成 revision_or_rewrite_proposal.yml。"
    )
    try:
        from agent_runtime.narrative_intent import classify_narrative_intent

        classified = classify_narrative_intent(
            request,
            active_longform_project=True,
        )
        checks.append(
            {
                "id": "heavy_audit_request_identity",
                "expected": {"kind": "audit"},
                "observed": {
                    "kind": classified.kind,
                    "reason": classified.reason,
                },
                "status": "pass" if classified.kind == "audit" else "confirmed_defect",
            }
        )
    except Exception as exc:  # pragma: no cover - evidence path must report gaps
        checks.append(
            {
                "id": "heavy_audit_request_identity",
                "expected": {"kind": "audit"},
                "observed": {"error": str(exc)},
                "status": "measurement_error",
            }
        )

    try:
        from agent_runtime.background_job_controller import _successful_transition

        state = {
            "status": "awaiting_heavy_audit",
            "current_batch": {"number": 1, "start": 1, "end": 10},
            "sealed_batches": [],
        }
        result = {
            "status": "pass",
            "requires_rewrite": False,
            "fiction_review": {"status": "blocked"},
            "continuity_failure_report": {"status": "pass"},
        }
        _successful_transition(state, "heavy_audit", result, "2026-07-19T00:00:00Z")
        sealed = state.get("status") == "batch_sealed" or bool(
            state.get("sealed_batches")
        )
        checks.append(
            {
                "id": "fiction_blocked_prevents_seal",
                "expected": {"sealed": False},
                "observed": {
                    "sealed": sealed,
                    "status": state.get("status"),
                    "sealed_batch_count": len(state.get("sealed_batches", [])),
                },
                "status": "confirmed_defect" if sealed else "pass",
            }
        )
    except Exception as exc:  # pragma: no cover - evidence path must report gaps
        checks.append(
            {
                "id": "fiction_blocked_prevents_seal",
                "expected": {"sealed": False},
                "observed": {"error": str(exc)},
                "status": "measurement_error",
            }
        )
    return checks


def build_efficiency_baseline(root: Path, manifest_path: Path) -> dict[str, Any]:
    """Build the Phase 0 baseline from a frozen manifest of tracked evidence."""

    root = Path(root).resolve()
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_yaml(manifest_path)
    cases: dict[str, Any] = {}
    for case in manifest.get("metric_cases", []):
        case_data = _mapping(case)
        case_id = str(case_data.get("id", ""))
        run_paths = [root / str(run_path) for run_path in case_data.get("run_dirs", [])]
        cases[case_id] = {
            "kind": case_data.get("kind"),
            "chapter_range": case_data.get("chapter_range"),
            "aggregate": aggregate_case_metrics(run_paths, evidence_root=root),
            "runs": [
                collect_run_metrics(run_path, evidence_root=root)
                for run_path in run_paths
            ],
        }

    frozen_files = []
    for item in manifest.get("frozen_files", []):
        item_data = _mapping(item)
        relative_path = str(item_data.get("path", ""))
        path = root / relative_path
        frozen_files.append(
            {
                **item_data,
                "path": relative_path,
                "exists": path.is_file(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size if path.is_file() else None,
            }
        )

    live_trial_path = root / str(manifest.get("live_trial_receipt", ""))
    live_trial = _load_json(live_trial_path)
    execution_isolation = _mapping(live_trial.get("execution_isolation"))
    production_guard = _mapping(live_trial.get("production_guard"))
    production_hash_match = production_guard.get("match")
    background_jobs = [
        collect_background_job_metrics(
            root / str(item),
            evidence_root=root,
        )
        for item in manifest.get("background_job_dirs", [])
    ]

    return {
        "schema_version": 1,
        "baseline_kind": "narrative_phase_0_diagnostic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_agent": "codex",
        "invoked_agent": "codex",
        "reporting_agent": "codex",
        "git": {
            "source_head": manifest.get("source_git_head"),
            "branch": _git_value(root, "branch", "--show-current"),
        },
        "root": ".",
        "manifest": _evidence_path(manifest_path, root),
        "positive_calibration_status": manifest.get(
            "positive_calibration_status", "missing_user_samples"
        ),
        "safety": {
            "candidate_only": execution_isolation.get("candidate_only"),
            "production_modified": (
                False if production_hash_match is True else None
            ),
            "measurement": (
                "live_trial_production_tree_hash_match"
                if production_hash_match is True
                else "missing_live_production_tree_hash"
            ),
        },
        "frozen_files": frozen_files,
        "live_trial": live_trial,
        "background_jobs": background_jobs,
        "cases": cases,
        "known_issue_checks": collect_known_issue_checks(),
        "measurement_notes": {
            "queue_wait_time": (
                "derived_from_persisted_background_job_events"
                if background_jobs
                else "missing_historical_field"
            ),
            "provider_rotation_count": "partially_available_in_capacity_receipts",
            "schema_valid_candidate_count": "missing_historical_field",
            "audit_eligible_candidate_count": "missing_historical_field",
            "human_blind_review_preference": "missing_user_samples",
            "quality_uplift": "not_measured_by_current_artifacts",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    baseline = build_efficiency_baseline(args.root, args.manifest)
    atomic_write_json(args.output, baseline)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by acceptance command
    raise SystemExit(main())
