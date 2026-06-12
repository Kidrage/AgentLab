from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from agent_runtime.external_agents.registry import (
    DEFAULT_CONFIG_PATH,
    get_external_agent,
)


ALLOWED_STATUS_VALUES = {"completed", "failed", "partial", "rejected"}


@dataclass
class _ExternalResultData:
    """Internal dataclass for external result data."""
    handoff_id: str
    task_id: str
    executor: dict[str, Any]
    status: str
    summary: str
    changed_files: list[dict[str, Any]] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    cost_notes: dict[str, Any] = field(default_factory=dict)
    submitted_at: Optional[str] = None


def normalize_external_result(data: dict[str, Any]) -> _ExternalResultData:
    """Convert raw result dict into an _ExternalResultData dataclass with defaults."""
    executor = dict(data.get("executor") or {})
    status = data.get("status", "completed")
    if status not in ALLOWED_STATUS_VALUES:
        raise ValueError(
            f"status must be one of {ALLOWED_STATUS_VALUES}, got '{status}'"
        )

    changed_files_raw = data.get("changed_files") or []
    changed_files = _normalize_changed_files(changed_files_raw)

    commands_run_raw = data.get("commands_run") or []
    commands_run = _normalize_commands_run(commands_run_raw)

    artifacts = _coerce_to_string_list(data.get("artifacts") or [])

    risks = _coerce_to_string_list(data.get("risks") or [])

    cost_notes = dict(data.get("cost_notes") or {})
    cost_notes.setdefault("api_cost_usd", None)
    cost_notes.setdefault("subscription_quota_used", "unknown")
    cost_notes.setdefault("pricing_status", "external_unknown")

    submitted_at = data.get("submitted_at") or datetime.now(timezone.utc).isoformat()

    return _ExternalResultData(
        handoff_id=data.get("handoff_id", ""),
        task_id=data.get("task_id", ""),
        executor=executor,
        status=status,
        summary=data.get("summary", ""),
        changed_files=changed_files,
        commands_run=commands_run,
        artifacts=artifacts,
        risks=risks,
        cost_notes=cost_notes,
        submitted_at=submitted_at,
    )


def _coerce_to_string_list(raw: list[Any]) -> list[dict[str, Any]]:
    """Coerce mixed input (strings + dicts) into list of dicts."""
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            result.append({"value": item})
        elif isinstance(item, dict):
            result.append(dict(item))
    return result


def _normalize_changed_files(raw: list[Any]) -> list[dict[str, Any]]:
    """Normalize changed_files: each must be a dict with at least path and change_type."""
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            result.append({"path": item, "change_type": "unknown"})
        elif isinstance(item, dict):
            entry = dict(item)
            entry.setdefault("path", "")
            entry.setdefault("change_type", "unknown")
            result.append(entry)
    return result


def _normalize_commands_run(raw: list[Any]) -> list[dict[str, Any]]:
    """Normalize commands_run: each must be a dict with 'command' and optional evidence."""
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            entry: dict[str, Any] = {"command": item}
            if "evidence" not in entry and "external_unverified" not in entry:
                entry["external_unverified"] = True
            result.append(entry)
        elif isinstance(item, dict):
            entry = dict(item)
            entry.setdefault("command", "")
            if "evidence" not in entry and "external_unverified" not in entry:
                entry["external_unverified"] = True
            result.append(entry)
    return result


def load_external_result(path: Path) -> _ExternalResultData:
    """Load an external result from a YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"Result file not found: {path}")
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    if not data or not isinstance(data, dict):
        raise ValueError(f"Invalid result data in {path}")
    return normalize_external_result(data)


def write_external_result(result: _ExternalResultData, run_dir: Path) -> Path:
    """Write external result to run_dir/external_result.yml."""
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / "external_result.yml"
    data = asdict(result)
    with open(output_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
    return output_path


def validate_external_result_evidence(result: _ExternalResultData) -> list[str]:
    """Validate evidence in an external result. Returns list of issues (empty = clean)."""
    issues: list[str] = []

    if result.status in ("failed", "rejected"):
        issues.append(
            f"Result status is '{result.status}'; evidence may be incomplete."
        )

    if result.changed_files:
        has_command_evidence = any(
            c.get("command") and c.get("evidence") for c in result.commands_run
        )
        has_unverified = any(
            c.get("external_unverified") for c in result.commands_run
        )
        has_artifacts = bool(result.artifacts)
        if not (has_command_evidence or has_unverified or has_artifacts):
            issues.append(
                "changed_files present but no command evidence, "
                "external_unverified marker, or artifacts"
            )

    for i, cmd in enumerate(result.commands_run):
        if not cmd.get("command"):
            issues.append(f"commands_run[{i}] missing 'command' field")
        if "evidence" not in cmd and not cmd.get("external_unverified"):
            issues.append(
                f"commands_run[{i}] ('{cmd.get('command', '')}') has no evidence "
                f"and no external_unverified flag — evidence is missing"
            )

    summary_lower = (result.summary or "").lower()
    claims_keywords = ["ran tests", "ran build", "executed commands", "tests passed"]
    if any(kw in summary_lower for kw in claims_keywords):
        has_cmd_evidence = any(
            c.get("command")
            and (c.get("evidence") or c.get("external_unverified"))
            for c in result.commands_run
        )
        has_artifacts = bool(result.artifacts)
        if not (has_cmd_evidence or has_artifacts):
            issues.append(
                "summary claims build/test/command execution but no command evidence "
                "or artifacts found"
            )

    api_cost = result.cost_notes.get("api_cost_usd")
    if api_cost == 0 and result.cost_notes.get("free") is not True:
        issues.append(
            "api_cost_usd is 0 but free is not explicitly set to true; "
            "external cost unknown must be null, not 0"
        )

    return issues


# ============================================================
# ExternalResult — the public class used by CLI and tests
# ============================================================
class ExternalResult:
    """Handles submission and validation of external agent results.

    Key P1-B design rules:
    - submit_result writes external_result.yml only; it does NOT auto-pass
      artifact gates.
    - evidence_status (complete/partial/missing) is separate from
      artifact_gate_status (pending/failed).
    - cost fields default to null/unknown.
    """

    def __init__(
        self,
        task_id: str,
        handoff_id: str,
        output_dir: Optional[str] = None,
    ):
        self.task_id = task_id
        self.handoff_id = handoff_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"
        self.result_id = (
            f"result_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )

    def submit_result(self, result_data: dict[str, Any]) -> dict[str, Any]:
        """Submit and validate an external agent result. Returns dict."""
        # ---- Validate required fields ----
        required = ["handoff_id", "task_id", "executor", "summary"]
        for field_name in required:
            if field_name not in result_data:
                raise ValueError(
                    f"Missing required field '{field_name}' in result data"
                )

        executor = result_data["executor"]
        if not isinstance(executor, dict):
            raise ValueError("'executor' must be a dict")
        for ex_field in (
            "agent_id",
            "reported_by",
            "billing_mode",
            "token_visibility",
        ):
            if ex_field not in executor:
                raise ValueError(
                    f"Missing required executor field '{ex_field}'"
                )

        if executor.get("token_visibility") != "unknown":
            raise ValueError("token_visibility must be 'unknown'")

        agent_id = executor.get("agent_id", "")
        if agent_id:
            try:
                agent = get_external_agent(DEFAULT_CONFIG_PATH, agent_id)
                expected_mode = agent.billing.get("mode", "")
                actual_mode = executor.get("billing_mode", "")
                if expected_mode and actual_mode and expected_mode != actual_mode:
                    raise ValueError(
                        f"Billing mode mismatch: agent config has "
                        f"'{expected_mode}', result has '{actual_mode}'"
                    )
            except ValueError:
                pass

        # ---- Normalize, validate evidence, write ----
        normalized = normalize_external_result(result_data)

        evidence_issues = validate_external_result_evidence(normalized)
        if evidence_issues:
            for issue in evidence_issues:
                print(f"WARNING: {issue}")
            # hard check for missing evidence with changed_files or claims
            has_hard_issue = any(
                "requires evidence of commands" in issue
                or "require evidence of commands run" in issue
                or "require evidence of commands run or artifacts" in issue
                or "no command evidence" in issue.lower()
                for issue in evidence_issues
            )
            if has_hard_issue:
                raise ValueError("; ".join(evidence_issues))

        evidence_status = "missing"
        if normalized.status in ("failed", "rejected"):
            evidence_status = "missing"
        elif normalized.commands_run or normalized.artifacts:
            evidence_status = "complete"
        elif normalized.changed_files:
            evidence_status = "partial"

        write_external_result(normalized, Path(self.output_dir))

        try:
            from agent_runtime.external_agents.ledger import (
                record_result_submitted,
            )

            record_result_submitted(
                ledger_path=Path(self.output_dir)
                / "external_agent_ledger.yml",
                task_id=self.task_id,
                handoff_id=normalized.handoff_id,
                evidence_status=evidence_status,
            )
        except ImportError:
            pass

        result = asdict(normalized)
        result["result_id"] = self.result_id
        result["evidence_status"] = evidence_status
        result.setdefault("api_cost_usd", None)
        result.setdefault("subscription_quota_used", "unknown")
        result.setdefault("pricing_status", "external_unknown")

        return result