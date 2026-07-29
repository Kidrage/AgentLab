"""Evidence-bound P0-P5 narrative production acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import re

import yaml

_STAGES = ("P0", "P1", "P2", "P3", "P4", "P5")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    return value if isinstance(value, Mapping) else None


def _artifact_issues(
    receipt: Mapping[str, Any],
    *,
    project_root: Path,
) -> list[str]:
    bindings = receipt.get("artifact_bindings")
    if not isinstance(bindings, list) or not bindings:
        return ["artifact_bindings_required"]
    issues: list[str] = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, Mapping):
            issues.append(f"artifact_binding_invalid:{index}")
            continue
        path_value = binding.get("path")
        declared_sha256 = binding.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            issues.append(f"artifact_path_required:{index}")
            continue
        path = (project_root / path_value).resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            issues.append(f"artifact_outside_project:{index}")
            continue
        if not path.is_file():
            issues.append(f"artifact_not_found:{path_value}")
            continue
        if not isinstance(declared_sha256, str) or not _SHA256.fullmatch(
            declared_sha256
        ):
            issues.append(f"artifact_sha256_invalid:{path_value}")
            continue
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != declared_sha256:
            issues.append(f"artifact_sha256_mismatch:{path_value}")
    return issues


def _metric_pass(value: object, rule: Mapping[str, Any]) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    threshold = rule.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return False
    operator = rule.get("operator")
    if operator == "eq":
        return float(value) == float(threshold)
    if operator == "gte":
        return float(value) >= float(threshold)
    return False


def build_narrative_acceptance_status(
    agentlab_root: Path,
    *,
    project: str,
    project_root: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    """Verify staged receipts and refuse full-scale claims before P5."""

    root = Path(agentlab_root).resolve()
    selected_project = Path(project_root).resolve()
    receipts = Path(evidence_dir).resolve()
    config_path = root / "config" / "narrative_acceptance_ladder.yml"
    config = _read_mapping(config_path)
    if (
        config is None
        or config.get("schema_version")
        != "narrative-acceptance-ladder/v1"
    ):
        return {
            "schema_version": "narrative-acceptance-status/v1",
            "project": project,
            "status": "blocked",
            "issues": ["acceptance_ladder_config_invalid"],
        }
    try:
        receipts.relative_to(selected_project)
    except ValueError:
        return {
            "schema_version": "narrative-acceptance-status/v1",
            "project": project,
            "status": "blocked",
            "issues": ["evidence_dir_outside_project"],
        }

    stage_config = config.get("stages")
    if not isinstance(stage_config, Mapping) or tuple(stage_config) != _STAGES:
        return {
            "schema_version": "narrative-acceptance-status/v1",
            "project": project,
            "status": "blocked",
            "issues": ["acceptance_stage_config_invalid"],
        }

    stages: list[dict[str, Any]] = []
    chain_open = True
    for stage_id in _STAGES:
        receipt_path = receipts / f"{stage_id}.yml"
        if not receipt_path.is_file():
            stages.append(
                {
                    "stage": stage_id,
                    "status": "missing",
                    "receipt_path": str(receipt_path),
                    "issues": ["receipt_missing"],
                }
            )
            chain_open = False
            continue
        receipt = _read_mapping(receipt_path)
        issues: list[str] = []
        if receipt is None:
            issues.append("receipt_invalid")
            receipt = {}
        if receipt.get("schema_version") != "narrative-acceptance-receipt/v1":
            issues.append("receipt_schema_invalid")
        if receipt.get("project") != project:
            issues.append("receipt_project_mismatch")
        if receipt.get("stage") != stage_id:
            issues.append("receipt_stage_mismatch")
        if receipt.get("status") != "pass":
            issues.append("receipt_not_pass")
        required = stage_config[stage_id].get("required_checks")
        checks = receipt.get("checks")
        if not isinstance(required, list) or not isinstance(checks, Mapping):
            issues.append("required_checks_invalid")
        else:
            for check_id in required:
                check = checks.get(check_id)
                if not isinstance(check, Mapping) or check.get("status") != "pass":
                    issues.append(f"required_check_not_pass:{check_id}")
        issues.extend(_artifact_issues(receipt, project_root=selected_project))
        if not chain_open:
            issues.append("prior_stage_not_pass")
        status = "pass" if not issues else "blocked"
        if status != "pass":
            chain_open = False
        stages.append(
            {
                "stage": stage_id,
                "status": status,
                "receipt_path": str(receipt_path),
                "receipt_sha256": hashlib.sha256(
                    receipt_path.read_bytes()
                ).hexdigest(),
                "issues": issues,
            }
        )

    passed = [item["stage"] for item in stages if item["status"] == "pass"]
    highest_completed = passed[-1] if passed else None
    p5_receipt = _read_mapping(receipts / "P5.yml") or {}
    metrics = p5_receipt.get("release_metrics")
    metric_rules = config.get("release_metrics")
    metric_results: dict[str, bool] = {}
    if isinstance(metrics, Mapping) and isinstance(metric_rules, Mapping):
        metric_results = {
            metric_id: _metric_pass(metrics.get(metric_id), rule)
            for metric_id, rule in metric_rules.items()
            if isinstance(rule, Mapping)
        }
    metrics_pass = (
        isinstance(metric_rules, Mapping)
        and len(metric_results) == len(metric_rules)
        and all(metric_results.values())
    )
    full_scale_ready = (
        all(item["status"] == "pass" for item in stages) and metrics_pass
    )
    return {
        "schema_version": "narrative-acceptance-status/v1",
        "project": project,
        "status": "pass" if full_scale_ready else "incomplete",
        "stages": stages,
        "highest_completed_stage": highest_completed,
        "release_metrics": metric_results,
        "release_metrics_pass": metrics_pass,
        "full_scale_production_ready": full_scale_ready,
        "claim_1980_chapter_capability_allowed": full_scale_ready,
        "issues": [] if full_scale_ready else ["P5_not_fully_accepted"],
    }
