"""Lifecycle orchestration for governed AgentLab component evolution."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import re
import subprocess
import tempfile
from typing import Any, Iterable, Mapping

import yaml

from agent_runtime.runtime_registry import RuntimeRegistry

from .compiler import RoleComponentCompiler
from .evidence import (
    GapObservation,
    build_observation,
    evaluate_gap_eligibility,
    load_observation,
    write_observation,
)
from .models import ComponentManifest
from .role_catalog import RoleCatalog
from .workspace import (
    assert_candidate_bundle_unchanged,
    assert_candidate_worktree_scope,
    create_candidate_worktree,
    prepare_draft_review,
    validate_candidate_worktree,
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _task_run_root(root: Path, path: Path, *, field_name: str) -> Path:
    """Return the owning task run or reject out-of-run evolution artifacts."""

    root = Path(root).resolve()
    candidate = Path(path).resolve()
    projects_root = (root / "projects").resolve()
    try:
        relative = candidate.relative_to(projects_root)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be under projects/<Project>/runs/<task_id>/"
        ) from exc
    if len(relative.parts) < 3 or relative.parts[1] != "runs":
        raise ValueError(f"{field_name} must be under projects/<Project>/runs/<task_id>/")
    return projects_root / relative.parts[0] / "runs" / relative.parts[2]


def _require_same_task_run(root: Path, evolution_dir: Path, paths: Iterable[Path]) -> Path:
    run_root = _task_run_root(root, evolution_dir, field_name="evolution_dir")
    for path in paths:
        owner = _task_run_root(root, Path(path), field_name=str(path))
        if owner != run_root:
            raise ValueError(f"self-evolution artifact crosses task-run boundary: {path}")
    return run_root


def _evolution_workspace_id(root: Path, evolution_dir: Path) -> str:
    """Derive a collision-resistant identity from the full task-relative path."""

    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    _task_run_root(root, evolution_dir, field_name="evolution_dir")
    relative = evolution_dir.relative_to((root / "projects").resolve()).as_posix()
    digest = sha256(relative.encode("utf-8")).hexdigest()[:16]
    return f"evolution-{digest}"


def _append_ledger(evolution_dir: Path, stage: str, status: str, **details: Any) -> Path:
    path = evolution_dir / "evolution_ledger.yml"
    data = _read_yaml(path) or {
        "schema_version": 1,
        "ledger_type": "agentlab_self_evolution",
        "events": [],
    }
    data.setdefault("events", []).append(
        {
            "at": utc_timestamp(),
            "stage": stage,
            "status": status,
            **details,
        }
    )
    data["current_stage"] = stage
    data["status"] = status
    return _write_yaml(path, data)


def record_gap_observation(
    root: Path,
    out_dir: Path,
    *,
    task_id: str,
    capability_id: str,
    reason: str,
    explicit_user_request: bool = False,
    input_contract: Iterable[str] = (),
    output_contract: Iterable[str] = (),
    permission_class: str = "read_only",
    required_capabilities: Iterable[str] = (),
) -> Path:
    run_root = _task_run_root(root, out_dir, field_name="observation output")
    if run_root.name != task_id:
        raise ValueError("gap observation task_id must match its owning task-run directory")
    if not task_id.strip() or not capability_id.strip() or not reason.strip():
        raise ValueError("task_id, capability_id, and reason are required")
    observation = build_observation(
        task_id=task_id,
        capability_id=capability_id,
        reason=reason,
        explicit_user_request=explicit_user_request,
        input_contract=input_contract,
        output_contract=output_contract,
        permission_class=permission_class,
        required_capabilities=required_capabilities,
    )
    return write_observation(observation, Path(out_dir) / "capability_gap_observation.yml")


def propose_component(
    root: Path,
    *,
    manifest_path: Path,
    evidence_paths: Iterable[Path],
    evolution_dir: Path,
) -> dict[str, Any]:
    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    manifest_path = Path(manifest_path).resolve()
    evidence_paths = [Path(path).resolve() for path in evidence_paths]
    _require_same_task_run(root, evolution_dir, [manifest_path])
    evidence_records: list[tuple[dict[str, str], GapObservation]] = []
    for evidence_path in evidence_paths:
        evidence_run = _task_run_root(
            root,
            evidence_path,
            field_name=str(evidence_path),
        )
        observation = load_observation(evidence_path)
        if observation.task_id != evidence_run.name:
            raise ValueError(
                f"gap observation task_id does not match its task-run directory: {evidence_path}"
            )
        evidence_records.append(
            (
                {
                    "path": str(evidence_path.relative_to(root)),
                    "sha256": sha256(evidence_path.read_bytes()).hexdigest(),
                },
                observation,
            )
        )
    evidence_records.sort(key=lambda item: item[0]["path"])
    evidence_sources = [item[0] for item in evidence_records]
    observations = [item[1] for item in evidence_records]
    evidence_bundle_sha256 = _canonical_sha256(evidence_sources)
    evolution_dir.mkdir(parents=True, exist_ok=True)
    manifest = ComponentManifest.load(manifest_path)
    if not observations:
        raise ValueError("at least one capability-gap observation is required")
    policy = _read_yaml(root / "config" / "self_evolution_policy.yml")
    trigger = policy.get("trigger") or {}
    eligibility = evaluate_gap_eligibility(
        observations,
        manifest=manifest,
        catalog=RoleCatalog.load(root),
        window_days=int(trigger.get("window_days") or 30),
        minimum_unique_tasks=int(trigger.get("minimum_unique_tasks") or 2),
    )
    if eligibility.get("status") == "eligible" and eligibility.get("fingerprint"):
        duplicate = _find_open_duplicate(
            root / "projects",
            fingerprint=str(eligibility["fingerprint"]),
            exclude=evolution_dir,
        )
        if duplicate is not None:
            eligibility = {
                **eligibility,
                "status": "blocked",
                "reason": "duplicate_open_proposal",
                "existing_proposal": str(duplicate),
            }
    proposal_status = "proposed" if eligibility.get("status") == "eligible" else "blocked"
    _write_yaml(evolution_dir / "component_manifest.yml", manifest.to_dict())
    _write_yaml(
        evolution_dir / "capability_gap_aggregate.yml",
        {
            "schema_version": 1,
            "manifest_fingerprint": manifest.fingerprint,
            "evidence_sources": evidence_sources,
            "evidence_bundle_sha256": evidence_bundle_sha256,
            "eligibility": eligibility,
            "observations": [item.to_dict() for item in observations],
        },
    )
    proposal = {
        "schema_version": 1,
        "proposal_type": "agentlab_component_evolution",
        "component_id": manifest.component_id,
        "component_kind": manifest.kind,
        "manifest_fingerprint": manifest.fingerprint,
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "status": proposal_status,
        "materializer": "agent_role_v1" if manifest.materializer_available else None,
        "materializer_status": "available" if manifest.materializer_available else "proposal_only",
        "eligibility": eligibility,
        "human_merge_required": True,
        "automatic_activation": "after_human_merge_and_config_reload",
        "direct_production_write": False,
    }
    _write_yaml(evolution_dir / "component_proposal.yml", proposal)
    _append_ledger(
        evolution_dir,
        "proposed" if proposal_status == "proposed" else "observed",
        proposal_status,
        component_id=manifest.component_id,
        eligibility_reason=eligibility.get("reason"),
    )
    return proposal


def _find_open_duplicate(
    parent: Path,
    *,
    fingerprint: str,
    exclude: Path,
) -> Path | None:
    if not parent.exists():
        return None
    for proposal_path in sorted(parent.rglob("component_proposal.yml")):
        candidate_dir = proposal_path.parent
        if candidate_dir.resolve() == exclude.resolve():
            continue
        proposal = _read_yaml(proposal_path)
        ledger = _read_yaml(candidate_dir / "evolution_ledger.yml")
        if proposal.get("status") == "blocked" or ledger.get("status") in {
            "blocked",
            "rejected",
            "rolled_back",
        }:
            continue
        aggregate = _read_yaml(candidate_dir / "capability_gap_aggregate.yml")
        existing = (aggregate.get("eligibility") or {}).get("fingerprint")
        if str(existing or "") == fingerprint:
            return candidate_dir
    return None


def materialize_component(
    root: Path,
    *,
    evolution_dir: Path,
    create_worktree: bool = True,
) -> dict[str, Any]:
    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    _task_run_root(root, evolution_dir, field_name="evolution_dir")
    proposal = _read_yaml(evolution_dir / "component_proposal.yml")
    if proposal.get("status") != "proposed":
        raise ValueError("component proposal is not eligible for materialization")
    manifest = ComponentManifest.load(evolution_dir / "component_manifest.yml")
    if manifest.kind == "agent_role" and manifest.status != "active":
        raise ValueError(
            "agent_role manifest must be active before materialization so the "
            "reviewed candidate is runnable after merge"
        )
    aggregate = _read_yaml(evolution_dir / "capability_gap_aggregate.yml")
    recorded_fingerprints = {
        str(proposal.get("manifest_fingerprint") or ""),
        str(aggregate.get("manifest_fingerprint") or ""),
    }
    if recorded_fingerprints != {manifest.fingerprint}:
        raise ValueError("component manifest changed after the proposal was recorded")
    if (
        proposal.get("component_id") != manifest.component_id
        or proposal.get("component_kind") != manifest.kind
    ):
        raise ValueError("component proposal identity does not match its manifest")
    evidence_sources = aggregate.get("evidence_sources") or []
    if not isinstance(evidence_sources, list) or not evidence_sources:
        raise ValueError("component proposal is missing its source evidence inventory")
    normalized_sources: list[dict[str, str]] = []
    observations: list[GapObservation] = []
    for item in evidence_sources:
        if not isinstance(item, Mapping):
            raise ValueError("component evidence inventory is invalid")
        raw_path = str(item.get("path") or "")
        evidence_path = (root / raw_path).resolve()
        _task_run_root(root, evidence_path, field_name="component evidence")
        if (
            not raw_path
            or evidence_path.is_symlink()
            or not evidence_path.is_file()
            or item.get("sha256") != sha256(evidence_path.read_bytes()).hexdigest()
        ):
            raise ValueError("component proposal source evidence changed")
        observation = load_observation(evidence_path)
        if observation.task_id != _task_run_root(
            root,
            evidence_path,
            field_name="component evidence",
        ).name:
            raise ValueError("component evidence task identity changed")
        observations.append(observation)
        normalized_sources.append(
            {"path": raw_path, "sha256": str(item.get("sha256") or "")}
        )
    normalized_sources.sort(key=lambda item: item["path"])
    evidence_bundle_sha256 = _canonical_sha256(normalized_sources)
    if not (
        aggregate.get("evidence_bundle_sha256") == evidence_bundle_sha256
        and proposal.get("evidence_bundle_sha256") == evidence_bundle_sha256
        and aggregate.get("observations")
        == [observation.to_dict() for observation in observations]
    ):
        raise ValueError("component proposal evidence bundle changed")
    policy = _read_yaml(root / "config" / "self_evolution_policy.yml")
    trigger = policy.get("trigger") or {}
    eligibility = evaluate_gap_eligibility(
        observations,
        manifest=manifest,
        catalog=RoleCatalog.load(root),
        window_days=int(trigger.get("window_days") or 30),
        minimum_unique_tasks=int(trigger.get("minimum_unique_tasks") or 2),
    )
    if eligibility.get("status") == "eligible" and eligibility.get("fingerprint"):
        duplicate = _find_open_duplicate(
            root / "projects",
            fingerprint=str(eligibility["fingerprint"]),
            exclude=evolution_dir,
        )
        if duplicate is not None:
            eligibility = {
                **eligibility,
                "status": "blocked",
                "reason": "duplicate_open_proposal",
            }
    if eligibility.get("status") != "eligible":
        raise ValueError(
            "component proposal is no longer eligible for materialization: "
            + str(eligibility.get("reason") or "unknown")
        )
    if not manifest.materializer_available:
        result = {
            "status": "design_ready",
            "reason": "component materializer is not registered in v1",
            "component_kind": manifest.kind,
        }
        _write_yaml(evolution_dir / "bridge_plan.yml", result)
        _append_ledger(evolution_dir, "design_ready", "proposal_only")
        return result

    bridge_dir = evolution_dir / "bridge_bundle"
    compile_result = RoleComponentCompiler(root).compile(manifest, bridge_dir)
    status = "materialized" if compile_result.get("status") == "pass" else "blocked"
    bridge_plan = {
        "schema_version": 1,
        "status": status,
        "component_id": manifest.component_id,
        "source_manifest": "component_manifest.yml",
        "bridge_bundle": "bridge_bundle",
        "generated_surfaces": [
            "agent_profile",
            "artifact_contract",
            "role_requirement",
            "worker_binding",
            "runtime_binding",
            "protocol_binding",
            "init_templates",
            "workflow_binding",
            "worker_prompt",
        ],
        "issues": compile_result.get("issues") or [],
    }
    _write_yaml(evolution_dir / "bridge_plan.yml", bridge_plan)
    _write_yaml(
        evolution_dir / "change_manifest.yml",
        {
            "component_id": manifest.component_id,
            "allowed_target_paths": [
                f"config/components/agents/{manifest.component_id}.yml",
                f"config/generated/roles/{manifest.component_id}/",
            ],
            "source_code_changes_required": False,
            "production_paths_allowed": False,
            "credential_paths_allowed": False,
        },
    )
    _write_yaml(
        evolution_dir / "validation_plan.yml",
        {
            "structural_checks": [
                "manifest_schema",
                "role_collision",
                "artifact_collision",
                "worker_whitelist",
                "runtime_route_selection",
                "invocation_contract",
                "generated_hashes",
                "secret_scan",
            ],
            "commands": (_read_yaml(root / "config" / "self_evolution_policy.yml").get("validation") or {}).get("commands") or [],
            "independent_verifier_required": True,
        },
    )
    _write_yaml(
        evolution_dir / "promotion_plan.yml",
        {
            "status": "blocked_until_validation_and_human_merge",
            "draft_pr": True,
            "auto_merge": False,
            "activation": "next_config_reload_after_merge",
            "additional_approval_required_for": [
                "credentials",
                "dependencies",
                "network_permissions",
                "external_write",
            ],
        },
    )
    _write_yaml(
        evolution_dir / "rollback_plan.yml",
        {
            "strategy": "revert_component_manifest_commit",
            "restore_previous_manifest": True,
            "remove_generated_bridge_bundle": True,
            "direct_main_branch_revert": False,
            "human_merge_required": True,
        },
    )
    workspace_receipt = None
    if status == "materialized" and create_worktree:
        workspace_receipt = create_candidate_worktree(
            root,
            evolution_id=_evolution_workspace_id(root, evolution_dir),
            manifest=manifest,
            bridge_bundle=bridge_dir,
        )
        _write_yaml(evolution_dir / "workspace_receipt.yml", workspace_receipt)
    _append_ledger(
        evolution_dir,
        "materialized",
        status,
        workspace_created=bool(workspace_receipt),
    )
    return {**bridge_plan, "workspace": workspace_receipt}


def _hash_matches(path: Path, expected: str) -> bool:
    return path.exists() and sha256(path.read_bytes()).hexdigest() == expected


VALIDATION_AUTHORITY_PATHS = (
    "config/self_evolution_policy.yml",
    "config/runtime_registry.yml",
    "config/routing_policy.yml",
    "config/routing_rules.yml",
    "config/agent_registry.yml",
    "config/agent_role_bindings.yml",
    "config/agent_role_requirements.yml",
    "config/worker_invocation_contracts.yml",
    "config/model_catalog.yml",
    "config/agent_model_profiles.yml",
)


def _validation_authority_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in VALIDATION_AUTHORITY_PATHS:
        path = Path(root) / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"validation authority must be a regular file: {relative}")
        hashes[relative] = sha256(path.read_bytes()).hexdigest()
    return hashes


def _runtime_doctor_semantic_issues(
    command: list[str],
    *,
    component_id: str,
) -> tuple[list[str], dict[str, Any]]:
    if "runtime-doctor" not in command:
        return [], {}
    try:
        out_index = command.index("--out") + 1
        report_path = Path(command[out_index]) / "M2_RUNTIME_HYGIENE_REPORT.yml"
    except (ValueError, IndexError):
        return ["runtime_doctor_output_not_declared"], {}
    report = _read_yaml(report_path)
    required_sections = {
        "runtime_layout",
        "symlink_audit",
        "gitignore_audit",
        "secret_scan",
    }
    if not required_sections.issubset(report):
        return ["runtime_doctor_report_missing_or_invalid"], {}

    allowed_prefixes = (
        f"config/components/agents/{component_id}.yml",
        f"config/generated/roles/{component_id}/",
    )

    def candidate_path(value: Any) -> bool:
        text = str(value or "").replace("\\", "/")
        return text == allowed_prefixes[0] or text.startswith(allowed_prefixes[1])

    issues: list[str] = []
    candidate_secret_findings = [
        item
        for item in (report.get("secret_scan") or {}).get("findings") or []
        if isinstance(item, Mapping) and candidate_path(item.get("file"))
    ]
    if candidate_secret_findings:
        issues.append("runtime_doctor_candidate_secret_finding")

    candidate_symlink_risks = [
        item
        for item in (report.get("symlink_audit") or {}).get("symlinks") or []
        if isinstance(item, Mapping)
        and candidate_path(item.get("path"))
        and (
            item.get("is_valid") is not True
            or item.get("outside_workspace") is True
            or bool(item.get("risk_flags"))
        )
    ]
    if candidate_symlink_risks:
        issues.append("runtime_doctor_candidate_symlink_risk")
    missing_rules = (report.get("gitignore_audit") or {}).get("missing_rules") or []
    if missing_rules:
        issues.append("runtime_doctor_missing_gitignore_rules")

    warning_count = sum(
        len((report.get(section) or {}).get("warnings") or [])
        for section in required_sections
    )
    return issues, {
        "report_path": str(report_path),
        "warning_count": warning_count,
        "candidate_secret_finding_count": len(candidate_secret_findings),
        "candidate_symlink_risk_count": len(candidate_symlink_risks),
        "missing_gitignore_rule_count": len(missing_rules),
    }


def _run_validation_command(
    command: list[str],
    cwd: Path,
    *,
    component_id: str,
    command_index: int,
    policy_command: list[str],
    output_path: Path,
) -> dict[str, Any]:
    started_at = utc_timestamp()
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    semantic_issues, semantic_evidence = _runtime_doctor_semantic_issues(
        command,
        component_id=component_id,
    )
    if output_path.is_symlink():
        raise ValueError("validation command output path is a symlink")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.stdout, encoding="utf-8")
    status = "pass" if result.returncode == 0 and not semantic_issues else "fail"
    return {
        "command_index": command_index,
        "policy_command": policy_command,
        "command": command,
        "exit_code": result.returncode,
        "status": status,
        "started_at": started_at,
        "completed_at": utc_timestamp(),
        "semantic_status": "pass" if not semantic_issues else "fail",
        "semantic_issues": semantic_issues,
        "semantic_evidence": semantic_evidence,
        "output_path": str(output_path),
        "output_sha256": sha256(output_path.read_bytes()).hexdigest(),
        "output_tail": result.stdout[-4000:],
    }


def _rendered_command_matches_policy(
    rendered: Any,
    policy_command: list[str],
) -> bool:
    if not isinstance(rendered, list) or len(rendered) != len(policy_command):
        return False
    replacements: set[str] = set()
    for actual, policy_item in zip(rendered, policy_command):
        if not isinstance(actual, str):
            return False
        marker = "{validation_artifact_dir}"
        if marker not in policy_item:
            if actual != policy_item:
                return False
            continue
        prefix, suffix = policy_item.split(marker, 1)
        if not actual.startswith(prefix) or (suffix and not actual.endswith(suffix)):
            return False
        end = len(actual) - len(suffix) if suffix else len(actual)
        replacement = actual[len(prefix):end]
        if not replacement:
            return False
        replacements.add(replacement)
    return len(replacements) <= 1


def _validation_report_integrity_issues(
    root: Path,
    evolution_dir: Path,
    *,
    manifest: ComponentManifest,
    policy_root: Path,
) -> list[str]:
    report_path = evolution_dir / "validation_report.yml"
    if report_path.is_symlink() or not report_path.is_file():
        return ["validation_report_missing_or_not_regular"]
    report = _read_yaml(report_path)
    policy = _read_yaml(Path(policy_root) / "config" / "self_evolution_policy.yml")
    commands = (policy.get("validation") or {}).get("commands") or []
    issues: list[str] = []
    required_values = {
        "schema_version": 1,
        "report_type": "agentlab_self_evolution_validation",
        "component_id": manifest.component_id,
        "manifest_fingerprint": manifest.fingerprint,
        "status": "pass",
        "structural_status": "pass",
        "commands_executed": True,
        "required_command_count": len(commands),
        "required_commands": commands,
    }
    issues.extend(
        f"invalid_validation_report:{key}"
        for key, expected in required_values.items()
        if report.get(key) != expected
    )
    checks = report.get("checks") or []
    expected_checks = {
        "compiler_preflight",
        "generated_hashes",
        "candidate_role_catalog",
        "runtime_whitelist",
    }
    passed_checks = {
        str(item.get("check"))
        for item in checks
        if isinstance(item, Mapping) and item.get("status") == "pass"
    }
    if len(checks) != len(expected_checks) or passed_checks != expected_checks:
        issues.append("invalid_validation_report:structural_checks")

    receipts = report.get("command_receipts") or []
    if not isinstance(receipts, list) or len(receipts) != len(commands):
        issues.append("invalid_validation_report:command_receipts")
        return issues
    run_root = _task_run_root(root, evolution_dir, field_name="evolution_dir")
    for index, (receipt, policy_command) in enumerate(
        zip(receipts, commands),
        start=1,
    ):
        prefix = f"invalid_validation_receipt:{index}"
        if not isinstance(receipt, Mapping) or not isinstance(policy_command, list):
            issues.append(prefix)
            continue
        if not (
            receipt.get("command_index") == index
            and receipt.get("policy_command") == policy_command
            and _rendered_command_matches_policy(
                receipt.get("command"),
                policy_command,
            )
            and receipt.get("status") == "pass"
            and receipt.get("exit_code") == 0
            and receipt.get("semantic_status") == "pass"
            and not (receipt.get("semantic_issues") or [])
            and receipt.get("started_at")
            and receipt.get("completed_at")
        ):
            issues.append(prefix)
        raw_output = str(receipt.get("output_path") or "")
        unresolved_output = Path(raw_output)
        if not unresolved_output.is_absolute():
            unresolved_output = root / unresolved_output
        output_path = unresolved_output.resolve()
        try:
            output_path.relative_to(run_root)
        except ValueError:
            issues.append(f"{prefix}:output_path")
            continue
        if (
            not raw_output
            or unresolved_output.is_symlink()
            or not output_path.is_file()
            or receipt.get("output_sha256")
            != sha256(output_path.read_bytes()).hexdigest()
            or receipt.get("output_tail")
            != output_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        ):
            issues.append(f"{prefix}:output_evidence")
    return issues


def _verification_report_issues(
    report_path: Path,
    *,
    manifest: ComponentManifest,
    role_session_id: str,
) -> list[str]:
    text = report_path.read_text(encoding="utf-8", errors="replace")
    marker_pattern = re.compile(
        r"^\s*(AGENTLAB_[A-Z0-9_]+)\s*:\s*(.*?)\s*$"
    )
    values: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = marker_pattern.match(line)
        if match:
            values.setdefault(match.group(1), []).append(match.group(2))
    required = {
        "AGENTLAB_SELF_EVOLUTION_VERDICT": "PASS",
        "AGENTLAB_COMPONENT_ID": manifest.component_id,
        "AGENTLAB_MANIFEST_FINGERPRINT": manifest.fingerprint,
        "AGENTLAB_ROLE_SESSION_ID": role_session_id,
    }
    issues: list[str] = []
    for marker, expected in required.items():
        actual = values.get(marker) or []
        if len(actual) != 1 or actual[0] != expected:
            issues.append(f"invalid_verification_report_marker:{marker}")
    raw_blocking = values.get("AGENTLAB_BLOCKING_FINDINGS_JSON") or []
    if len(raw_blocking) != 1:
        issues.append(
            "invalid_verification_report_marker:AGENTLAB_BLOCKING_FINDINGS_JSON"
        )
    else:
        try:
            blocking = json.loads(raw_blocking[0])
        except (TypeError, json.JSONDecodeError):
            issues.append("invalid_verification_report_blocking_findings")
        else:
            if not isinstance(blocking, list) or blocking:
                issues.append("verification_report_contains_blocking_findings")
    return issues


_VERIFIER_ACCEPTANCE = [
    "verify manifest, generated bridge hashes, route binding, and validation evidence",
    "report blocking findings without editing the candidate",
    "emit each required report marker exactly once on its own line",
    "set PASS and [] only when no blocking finding remains",
]
_VERIFIER_FORBIDDEN = ["self_promotion", "candidate_edit", "production_write"]


def _verifier_input_paths(
    root: Path,
    evolution_dir: Path,
    *,
    manifest: ComponentManifest,
    role_session_path: Path,
) -> list[Path]:
    bridge_root = evolution_dir / "bridge_bundle"
    compatibility_path = bridge_root / "compatibility_manifest.yml"
    compatibility = _read_yaml(compatibility_path)
    if not (
        compatibility.get("status") == "pass"
        and compatibility.get("component_id") == manifest.component_id
        and compatibility.get("manifest_fingerprint") == manifest.fingerprint
    ):
        raise ValueError("bridge compatibility manifest identity is invalid")
    verifier_inputs = [
        evolution_dir / "component_manifest.yml",
        evolution_dir / "validation_report.yml",
        compatibility_path,
        role_session_path,
    ]
    if any(path.is_symlink() or not path.is_file() for path in verifier_inputs):
        raise ValueError("Verifier inputs must be regular run-local files")
    validation = _read_yaml(evolution_dir / "validation_report.yml")
    for receipt in validation.get("command_receipts") or []:
        if not isinstance(receipt, Mapping):
            raise ValueError("validation command receipt is invalid")
        output_path = Path(str(receipt.get("output_path") or ""))
        if not output_path.is_absolute():
            output_path = root / output_path
        unresolved_output = output_path
        output_path = unresolved_output.resolve()
        _task_run_root(root, output_path, field_name="validation command output")
        if unresolved_output.is_symlink() or not output_path.is_file():
            raise ValueError("validation command output is missing or not regular")
        verifier_inputs.append(output_path)
    generated_files = compatibility.get("generated_files")
    if not isinstance(generated_files, list) or not generated_files:
        raise ValueError("compatibility manifest generated file inventory is empty")
    seen: set[Path] = set()
    for item in generated_files:
        if not isinstance(item, Mapping):
            raise ValueError("compatibility manifest generated file item is invalid")
        raw_path = str(item.get("path") or "")
        unresolved = bridge_root / raw_path
        path = unresolved.resolve()
        try:
            path.relative_to(bridge_root.resolve())
        except ValueError as exc:
            raise ValueError(
                "compatibility manifest contains an unsafe bridge path"
            ) from exc
        current = unresolved
        while current != bridge_root and current != current.parent:
            if current.is_symlink():
                raise ValueError("generated bridge path contains a symlink")
            current = current.parent
        if not raw_path or path in seen:
            raise ValueError("compatibility manifest bridge path is blank or duplicated")
        if (
            not path.is_file()
            or sha256(path.read_bytes()).hexdigest()
            != str(item.get("sha256") or "")
        ):
            raise ValueError("generated bridge files changed after validation")
        seen.add(path)
        verifier_inputs.append(path)
    return verifier_inputs


def _verifier_task_contract(
    root: Path,
    run_root: Path,
    evolution_dir: Path,
    *,
    manifest: ComponentManifest,
    role_session_path: Path,
    role_session_id: str,
    worker: str,
) -> dict[str, Any]:
    verifier_inputs = _verifier_input_paths(
        root,
        evolution_dir,
        manifest=manifest,
        role_session_path=role_session_path,
    )
    return {
        "schema_version": 1,
        "packet_type": "agentlab_self_evolution_verifier_task",
        "role_session_id": role_session_id,
        "role": "Verifier",
        "worker": worker,
        "component_id": manifest.component_id,
        "manifest_fingerprint": manifest.fingerprint,
        "candidate_only": True,
        "must_read_artifacts": [
            str(path.relative_to(root)) for path in verifier_inputs
        ],
        "required_output": str(
            (run_root / "verification_report.md").relative_to(root)
        ),
        "required_report_markers": {
            "AGENTLAB_SELF_EVOLUTION_VERDICT": "PASS",
            "AGENTLAB_COMPONENT_ID": manifest.component_id,
            "AGENTLAB_MANIFEST_FINGERPRINT": manifest.fingerprint,
            "AGENTLAB_ROLE_SESSION_ID": role_session_id,
            "AGENTLAB_BLOCKING_FINDINGS_JSON": "[]",
        },
        "acceptance": list(_VERIFIER_ACCEPTANCE),
        "forbidden": list(_VERIFIER_FORBIDDEN),
    }


def _verification_receipt_issues(
    supplied: Mapping[str, Any],
    *,
    root: Path,
    run_root: Path,
    manifest: ComponentManifest,
    validation_report_path: Path,
    compatibility_path: Path,
) -> list[str]:
    evidence = supplied.get("evidence") if isinstance(supplied.get("evidence"), Mapping) else {}
    validation_report = _read_yaml(validation_report_path)
    expected = {
        "validation_report_sha256": sha256(validation_report_path.read_bytes()).hexdigest(),
        "compatibility_manifest_sha256": sha256(compatibility_path.read_bytes()).hexdigest(),
    }
    required_values = {
        "schema_version": 1,
        "report_type": "agentlab_self_evolution_verification_receipt",
        "status": "pass",
        "role": "Verifier",
        "independent": True,
        "role_session_returned": True,
        "candidate_only": True,
        "production_modified": False,
        "promotion_attempted": False,
        "component_id": manifest.component_id,
        "manifest_fingerprint": manifest.fingerprint,
    }
    issues = [
        f"invalid_{key}"
        for key, value in required_values.items()
        if supplied.get(key) != value
    ]
    issues.extend(
        _validation_report_integrity_issues(
            root,
            validation_report_path.parent,
            manifest=manifest,
            policy_root=root,
        )
    )
    issues.extend(
        f"invalid_evidence_{key}"
        for key, value in expected.items()
        if evidence.get(key) != value
    )
    if (
        validation_report.get("manifest_fingerprint") != manifest.fingerprint
        or validation_report.get("compatibility_manifest_sha256")
        != expected["compatibility_manifest_sha256"]
    ):
        issues.append("validation_snapshot_candidate_binding_mismatch")
    try:
        runtime_authority = _validation_authority_hashes(root)
    except ValueError:
        runtime_authority = {}
    if validation_report.get("validation_authority_sha256") != runtime_authority:
        issues.append("validation_authority_bundle_changed")
    expected_worker = str(
        validation_report.get("independent_verifier_worker") or ""
    )
    if supplied.get("worker") != expected_worker:
        issues.append("invalid_worker")
    if not supplied.get("role_session_id"):
        issues.append("invalid_role_session_id")
    if not supplied.get("execution_attempt_id"):
        issues.append("invalid_execution_attempt_id")

    source_paths: dict[str, Path] = {}
    for key in (
        "role_session_path",
        "verifier_task_packet_path",
        "execution_task_packet_path",
        "outbound_context_manifest_path",
        "model_execution_receipt_path",
        "model_execution_chain_path",
        "execution_log_path",
        "provider_stdout_path",
        "verification_report_path",
        "execution_binding_path",
    ):
        raw = str(evidence.get(key) or "")
        candidate = (run_root / raw).resolve()
        try:
            candidate.relative_to(run_root)
        except (TypeError, ValueError):
            issues.append(f"invalid_evidence_{key}")
            continue
        if not raw or candidate.is_symlink() or not candidate.is_file():
            issues.append(f"invalid_evidence_{key}")
            continue
        source_paths[key] = candidate
        hash_key = key.removesuffix("_path") + "_sha256"
        if evidence.get(hash_key) != sha256(candidate.read_bytes()).hexdigest():
            issues.append(f"invalid_evidence_{hash_key}")

    role_session_path = source_paths.get("role_session_path")
    verifier_task_packet_path = source_paths.get("verifier_task_packet_path")
    execution_task_packet_path = source_paths.get("execution_task_packet_path")
    outbound_context_manifest_path = source_paths.get(
        "outbound_context_manifest_path"
    )
    execution_path = source_paths.get("model_execution_receipt_path")
    execution_chain_path = source_paths.get("model_execution_chain_path")
    execution_log_path = source_paths.get("execution_log_path")
    provider_stdout_path = source_paths.get("provider_stdout_path")
    report_path = source_paths.get("verification_report_path")
    execution_binding_path = source_paths.get("execution_binding_path")
    if role_session_path:
        role_session = _read_yaml(role_session_path)
        project = run_root.parent.parent.name
        role_session_ok = (
            role_session.get("packet_type") == "agentlab_role_session"
            and role_session.get("role") == "Verifier"
            and role_session.get("worker") == expected_worker
            and role_session.get("project") == project
            and role_session.get("task_id") == run_root.name
            and (role_session.get("binding") or {}).get("allowed") is True
            and role_session.get("role_session_id") == supplied.get("role_session_id")
        )
        try:
            from agent_runtime.protocols import check_role_binding

            binding_allowed, _ = check_role_binding(root, expected_worker, "Verifier")
        except (ImportError, OSError, ValueError, yaml.YAMLError):
            binding_allowed = False
        if not role_session_ok or not binding_allowed:
            issues.append("invalid_bound_role_session")
    verifier_task_packet: dict[str, Any] = {}
    if verifier_task_packet_path:
        verifier_task_packet = _read_yaml(verifier_task_packet_path)
        try:
            expected_packet = _verifier_task_contract(
                root,
                run_root,
                validation_report_path.parent,
                manifest=manifest,
                role_session_path=role_session_path or Path(),
                role_session_id=str(supplied.get("role_session_id") or ""),
                worker=expected_worker,
            )
        except (OSError, ValueError):
            expected_packet = {}
        packet_without_timestamp = dict(verifier_task_packet)
        generated_at = packet_without_timestamp.pop("generated_at", None)
        if not (
            isinstance(generated_at, str)
            and generated_at
            and expected_packet
            and packet_without_timestamp == expected_packet
        ):
            issues.append("invalid_verifier_task_packet")
    if execution_task_packet_path:
        try:
            execution_packet = json.loads(
                execution_task_packet_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            execution_packet = {}
        messages = execution_packet.get("messages") or []
        message_text = "\n".join(
            str(item.get("content") or "")
            for item in messages
            if isinstance(item, Mapping)
        )
        if not (
            execution_packet.get("packet_type") == "agentlab_sealed_role_session"
            and execution_packet.get("agent") == "Verifier"
            and isinstance(messages, list)
            and "agentlab_self_evolution_verifier_task" in message_text
            and manifest.component_id in message_text
            and manifest.fingerprint in message_text
            and str(supplied.get("role_session_id") or "") in message_text
        ):
            issues.append("invalid_execution_task_packet")
    if outbound_context_manifest_path:
        outbound = _read_yaml(outbound_context_manifest_path)
        context_boundary = outbound.get("context_boundary") or {}
        if not (
            outbound.get("role") == "Verifier"
            and context_boundary.get("sealed_context") is True
            and context_boundary.get("exact_payload_hashed") is True
            and outbound.get("execution_allowed") is True
            and execution_task_packet_path is not None
            and (outbound.get("payload") or {}).get("sha256")
            == sha256(execution_task_packet_path.read_bytes()).hexdigest()
        ):
            issues.append("invalid_outbound_context_manifest")
        source_records = (outbound.get("source_inventory") or {}).get("files") or []
        expected_source_paths: list[Path] = []
        if verifier_task_packet_path is not None:
            expected_source_paths.append(verifier_task_packet_path)
        for raw_path in verifier_task_packet.get("must_read_artifacts") or []:
            path = (root / str(raw_path)).resolve()
            try:
                path.relative_to(run_root)
            except ValueError:
                continue
            expected_source_paths.append(path)
        source_inventory_matches = True
        for expected_source in expected_source_paths:
            expected_relative = str(expected_source.relative_to(root))
            matches = [
                item
                for item in source_records
                if isinstance(item, Mapping)
                and item.get("path") == expected_relative
            ]
            if not (
                len(matches) == 1
                and expected_source.is_file()
                and matches[0].get("inside_agentlab_root") is True
                and matches[0].get("exists") is True
                and matches[0].get("is_symlink") is False
                and matches[0].get("sha256")
                == sha256(expected_source.read_bytes()).hexdigest()
            ):
                source_inventory_matches = False
                break
        if not expected_source_paths or not source_inventory_matches:
            issues.append("verifier_execution_used_different_prepared_packet")
    execution: dict[str, Any] = {}
    if execution_path:
        execution = _read_yaml(execution_path)
        execution_ok = (
            execution.get("status") == "pass"
            and execution.get("role") == "Verifier"
            and execution.get("worker") == expected_worker
            and execution.get("provider_process_started") is True
            and execution.get("profile_binding_verified") is True
            and execution.get("command_binding_verified") is True
            and execution.get("fallback_detected") is False
            and execution.get("stdout_nonempty") is True
            and execution.get("exit_code") == 0
            and not (execution.get("issues") or [])
            and execution.get("attempt_id") == supplied.get("execution_attempt_id")
            and execution_task_packet_path is not None
            and execution.get("task_packet_sha256")
            == sha256(execution_task_packet_path.read_bytes()).hexdigest()
            and outbound_context_manifest_path is not None
            and execution.get("outbound_context_manifest_sha256")
            == sha256(outbound_context_manifest_path.read_bytes()).hexdigest()
            and report_path is not None
            and execution.get("returned_content_sha256")
            == sha256(report_path.read_bytes()).hexdigest()
            and bool(execution.get("execution_command_id"))
            and re.fullmatch(
                r"[0-9a-f]{64}",
                str(execution.get("provider_stdout_sha256") or ""),
            )
            is not None
        )
        receipt_path = Path(str(execution.get("receipt_path") or ""))
        if not receipt_path.is_absolute():
            receipt_path = run_root / receipt_path
        chain_path = Path(str(execution.get("chain_path") or ""))
        if not chain_path.is_absolute():
            chain_path = run_root / chain_path
        execution_ok = (
            execution_ok
            and receipt_path.resolve() == execution_path
            and execution_chain_path is not None
            and chain_path.resolve() == execution_chain_path
        )
        if not execution_ok:
            issues.append("invalid_model_execution_receipt")
        try:
            requested_at = datetime.fromisoformat(
                str(verifier_task_packet.get("generated_at") or "").replace("Z", "+00:00")
            )
            executed_at = datetime.fromisoformat(
                str(execution.get("created_at") or "").replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            issues.append("invalid_verifier_execution_timestamp")
        else:
            if requested_at.tzinfo is None or executed_at.tzinfo is None:
                issues.append("invalid_verifier_execution_timestamp")
            elif executed_at < requested_at:
                issues.append("stale_model_execution_receipt")
    if execution_chain_path and execution_path:
        execution_chain = _read_yaml(execution_chain_path)
        final = (
            execution_chain.get("final")
            if isinstance(execution_chain.get("final"), Mapping)
            else {}
        )
        final_receipt_path = Path(str(final.get("receipt_path") or ""))
        if not final_receipt_path.is_absolute():
            final_receipt_path = run_root / final_receipt_path
        attempts = [
            item
            for item in (execution_chain.get("attempts") or [])
            if isinstance(item, Mapping)
        ]
        matching_attempts = [
            item
            for item in attempts
            if item.get("attempt_id") == supplied.get("execution_attempt_id")
            and item.get("receipt_path") == final.get("receipt_path")
            and item.get("receipt_sha256")
            == sha256(execution_path.read_bytes()).hexdigest()
        ]
        chain_ok = (
            execution_chain.get("role") == "Verifier"
            and execution_chain.get("status") == "pass"
            and execution_chain.get("fallback_used") is False
            and final.get("attempt_id") == supplied.get("execution_attempt_id")
            and final.get("status") == "pass"
            and final_receipt_path.resolve() == execution_path
            and final.get("receipt_sha256")
            == sha256(execution_path.read_bytes()).hexdigest()
            and not (final.get("failure_issues") or [])
            and len(matching_attempts) == 1
            and matching_attempts[0].get("status") == "pass"
            and matching_attempts[0].get("fallback_detected") is False
            and not (matching_attempts[0].get("failure_issues") or [])
        )
        if not chain_ok:
            issues.append("invalid_model_execution_chain")
    if execution_log_path and provider_stdout_path:
        execution_log = _read_yaml(execution_log_path)
        matching_commands = [
            item
            for item in execution_log.get("commands") or []
            if isinstance(item, Mapping)
            and item.get("command_id") == execution.get("execution_command_id")
        ]
        command = matching_commands[0] if len(matching_commands) == 1 else {}
        stdout_path = Path(str(command.get("stdout_path") or ""))
        if not stdout_path.is_absolute():
            stdout_path = run_root / stdout_path
        command_ok = (
            command.get("agent") == "Verifier"
            and command.get("exit_code") == 0
            and command.get("status") == "success"
            and stdout_path.resolve() == provider_stdout_path
            and command.get("stdout_sha256")
            == execution.get("provider_stdout_sha256")
            and sha256(provider_stdout_path.read_bytes()).hexdigest()
            == execution.get("provider_stdout_sha256")
        )
        if not command_ok:
            issues.append("invalid_provider_execution_log_binding")
    if execution_binding_path:
        binding = _read_yaml(execution_binding_path)
        binding_evidence = (
            binding.get("evidence")
            if isinstance(binding.get("evidence"), Mapping)
            else {}
        )
        binding_required = {
            "schema_version": 1,
            "binding_type": "agentlab_self_evolution_verifier_execution",
            "status": "pass",
            "role": "Verifier",
            "worker": expected_worker,
            "role_session_id": supplied.get("role_session_id"),
            "component_id": manifest.component_id,
            "manifest_fingerprint": manifest.fingerprint,
            "execution_attempt_id": supplied.get("execution_attempt_id"),
            "execution_command_id": execution.get("execution_command_id"),
            "task_packet_sha256": execution.get("task_packet_sha256"),
            "outbound_context_manifest_sha256": execution.get(
                "outbound_context_manifest_sha256"
            ),
            "provider_stdout_sha256": execution.get("provider_stdout_sha256"),
            "returned_content_sha256": execution.get("returned_content_sha256"),
        }
        binding_ok = all(
            binding.get(key) == value for key, value in binding_required.items()
        )
        for key in (
            "role_session",
            "verifier_task_packet",
            "execution_task_packet",
            "outbound_context_manifest",
            "model_execution_receipt",
            "model_execution_chain",
            "execution_log",
            "provider_stdout",
            "verification_report",
        ):
            source = source_paths.get(f"{key}_path")
            if source is None:
                binding_ok = False
                continue
            expected_relative = str(source.relative_to(run_root))
            binding_ok = binding_ok and (
                binding_evidence.get(f"{key}_path") == expected_relative
                and binding_evidence.get(f"{key}_sha256")
                == sha256(source.read_bytes()).hexdigest()
            )
        if not binding_ok:
            issues.append("invalid_verifier_execution_binding")
    if report_path:
        issues.extend(
            _verification_report_issues(
                report_path,
                manifest=manifest,
                role_session_id=str(supplied.get("role_session_id") or ""),
            )
        )
    return issues


def prepare_verifier_request(
    root: Path,
    *,
    evolution_dir: Path,
    worker: str | None = None,
) -> dict[str, Any]:
    """Write the strongly bound Verifier role-session and task packet."""

    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    run_root = _task_run_root(root, evolution_dir, field_name="evolution_dir")
    validation = _read_yaml(evolution_dir / "validation_report.yml")
    if validation.get("status") != "pass" or validation.get("commands_executed") is not True:
        raise ValueError("full validation must pass before requesting independent verification")
    manifest = ComponentManifest.load(evolution_dir / "component_manifest.yml")
    workspace = _read_yaml(evolution_dir / "workspace_receipt.yml")
    if not workspace:
        raise ValueError("managed candidate worktree is required for verification")
    validation_root, _ = validate_candidate_worktree(
        root,
        workspace,
        evolution_id=_evolution_workspace_id(root, evolution_dir),
        component_id=manifest.component_id,
    )
    assert_candidate_worktree_scope(
        validation_root,
        component_id=manifest.component_id,
    )
    assert_candidate_bundle_unchanged(
        validation_root,
        component_id=manifest.component_id,
        manifest_fingerprint=manifest.fingerprint,
        bridge_bundle=evolution_dir / "bridge_bundle",
    )
    recorded_authority = validation.get("validation_authority_sha256") or {}
    if not (
        recorded_authority
        and recorded_authority == _validation_authority_hashes(validation_root)
        and recorded_authority == _validation_authority_hashes(root)
    ):
        raise ValueError("validation authority changed after full validation")
    validation_issues = _validation_report_integrity_issues(
        root,
        evolution_dir,
        manifest=manifest,
        policy_root=validation_root,
    )
    if validation_issues:
        raise ValueError(
            "full validation evidence is incomplete or changed: "
            + ", ".join(validation_issues)
        )
    configured_worker = str(validation.get("independent_verifier_worker") or "")
    selected_worker = str(worker or configured_worker)
    if not configured_worker or selected_worker != configured_worker:
        raise ValueError("Verifier worker must match self_evolution_policy.yml")
    try:
        from agent_runtime.protocols import build_role_session
    except ImportError:  # pragma: no cover - direct runtime import path
        from protocols import build_role_session

    project = run_root.parent.parent.name
    role_session = build_role_session(
        root,
        "Verifier",
        selected_worker,
        project=project,
        task_id=run_root.name,
    )
    if (role_session.get("binding") or {}).get("allowed") is not True:
        raise ValueError("configured Verifier worker is not allowed by the role binding")
    role_session_path = _write_yaml(
        run_root / "self_evolution_verifier_role_session.yml",
        role_session,
    )
    if validation.get("manifest_fingerprint") != manifest.fingerprint:
        raise ValueError("component manifest changed after validation")
    compatibility_path = (
        evolution_dir / "bridge_bundle" / "compatibility_manifest.yml"
    )
    if validation.get("compatibility_manifest_sha256") != sha256(
        compatibility_path.read_bytes()
    ).hexdigest():
        raise ValueError("bridge compatibility manifest changed after validation")
    task_packet = {
        **_verifier_task_contract(
            root,
            run_root,
            evolution_dir,
            manifest=manifest,
            role_session_path=role_session_path,
            role_session_id=str(role_session.get("role_session_id") or ""),
            worker=selected_worker,
        ),
        "generated_at": utc_timestamp(),
    }
    packet_path = _write_yaml(
        run_root / "self_evolution_verifier_task_packet.yml",
        task_packet,
    )
    result = {
        "status": "ready",
        "role_session": str(role_session_path),
        "task_packet": str(packet_path),
        "task_packet_sha256": sha256(packet_path.read_bytes()).hexdigest(),
        "execution_command": (
            f"./agentlab.sh run-agent Verifier --project {project} "
            f"--task-id {run_root.name} --execute --force "
            "--output verification_report.md --overwrite-report"
        ),
    }
    _write_yaml(evolution_dir / "verifier_request_receipt.yml", result)
    _append_ledger(evolution_dir, "verifier_requested", "pending_verifier")
    return result


def collect_verifier_receipt(
    root: Path,
    *,
    evolution_dir: Path,
    execution_receipt_path: Path | None = None,
) -> Path:
    """Collect actual Verifier role-session outputs into a hash-bound receipt."""

    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    run_root = _task_run_root(root, evolution_dir, field_name="evolution_dir")
    if execution_receipt_path is None:
        chain = _read_yaml(run_root / "model_execution_chain_verifier.yml")
        execution_receipt_path = Path(str((chain.get("final") or {}).get("receipt_path") or ""))
    execution_receipt_path = Path(execution_receipt_path)
    if not execution_receipt_path.is_absolute():
        execution_receipt_path = run_root / execution_receipt_path
    execution_receipt_path = execution_receipt_path.resolve()
    if _task_run_root(
        root,
        execution_receipt_path,
        field_name="Verifier model execution receipt",
    ) != run_root:
        raise ValueError("Verifier model execution receipt crosses task-run boundary")
    role_session_path = run_root / "self_evolution_verifier_role_session.yml"
    verification_report_path = run_root / "verification_report.md"
    execution_binding_path = (
        run_root / "self_evolution_verifier_execution_binding.yml"
    )
    role_session = _read_yaml(role_session_path)
    execution = _read_yaml(execution_receipt_path)
    manifest = ComponentManifest.load(evolution_dir / "component_manifest.yml")
    execution_log_path = run_root / "execution_log.yml"
    execution_log = _read_yaml(execution_log_path)
    command_records = [
        item
        for item in execution_log.get("commands") or []
        if isinstance(item, Mapping)
        and item.get("command_id") == execution.get("execution_command_id")
    ]
    stdout_raw = str(
        command_records[0].get("stdout_path")
        if len(command_records) == 1
        else ""
    )
    provider_stdout_path = (run_root / stdout_raw).resolve()
    try:
        provider_stdout_path.relative_to(run_root)
    except ValueError:
        provider_stdout_path = run_root / "invalid_provider_stdout_evidence"
    evidence_paths = {
        "role_session": role_session_path,
        "verifier_task_packet": run_root / "self_evolution_verifier_task_packet.yml",
        "execution_task_packet": run_root / "task_packet_verifier.json",
        "outbound_context_manifest": run_root
        / "outbound_context_manifest_verifier.yml",
        "model_execution_receipt": execution_receipt_path,
        "model_execution_chain": run_root / "model_execution_chain_verifier.yml",
        "execution_log": execution_log_path,
        "provider_stdout": provider_stdout_path,
        "verification_report": verification_report_path,
        "execution_binding": execution_binding_path,
    }
    evidence = {
        "validation_report_sha256": sha256(
            (evolution_dir / "validation_report.yml").read_bytes()
        ).hexdigest(),
        "compatibility_manifest_sha256": sha256(
            (evolution_dir / "bridge_bundle" / "compatibility_manifest.yml").read_bytes()
        ).hexdigest(),
    }
    for name, path in evidence_paths.items():
        evidence[f"{name}_path"] = str(path.relative_to(run_root))
        evidence[f"{name}_sha256"] = sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    receipt = {
        "schema_version": 1,
        "report_type": "agentlab_self_evolution_verification_receipt",
        "status": "pass",
        "role": "Verifier",
        "worker": role_session.get("worker"),
        "role_session_id": role_session.get("role_session_id"),
        "execution_attempt_id": execution.get("attempt_id"),
        "independent": True,
        "role_session_returned": True,
        "candidate_only": True,
        "production_modified": False,
        "promotion_attempted": False,
        "component_id": manifest.component_id,
        "manifest_fingerprint": manifest.fingerprint,
        "evidence": evidence,
    }
    issues = _verification_receipt_issues(
        receipt,
        root=root,
        run_root=run_root,
        manifest=manifest,
        validation_report_path=evolution_dir / "validation_report.yml",
        compatibility_path=evolution_dir / "bridge_bundle" / "compatibility_manifest.yml",
    )
    if issues:
        receipt["status"] = "fail"
        receipt["issues"] = issues
    receipt_path = _write_yaml(run_root / "self_evolution_verifier_receipt.yml", receipt)
    _append_ledger(
        evolution_dir,
        "verifier_collected",
        "verified" if not issues else "verification_failed",
    )
    return receipt_path


def validate_evolution(
    root: Path,
    *,
    evolution_dir: Path,
    execute_commands: bool = False,
    independent_verification_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    run_root = _task_run_root(root, evolution_dir, field_name="evolution_dir")
    if independent_verification_path is not None:
        verifier_run = _task_run_root(
            root,
            independent_verification_path,
            field_name="independent verification receipt",
        )
        if verifier_run != run_root:
            raise ValueError("independent verification receipt crosses task-run boundary")
    manifest = ComponentManifest.load(evolution_dir / "component_manifest.yml")
    bridge = evolution_dir / "bridge_bundle"
    workspace = _read_yaml(evolution_dir / "workspace_receipt.yml")
    if independent_verification_path is not None:
        validation_report_path = evolution_dir / "validation_report.yml"
        report = _read_yaml(validation_report_path)
        if not workspace:
            raise ValueError("managed candidate worktree is required for verification")
        validation_root, _ = validate_candidate_worktree(
            root,
            workspace,
            evolution_id=_evolution_workspace_id(root, evolution_dir),
            component_id=manifest.component_id,
        )
        assert_candidate_worktree_scope(
            validation_root,
            component_id=manifest.component_id,
        )
        assert_candidate_bundle_unchanged(
            validation_root,
            component_id=manifest.component_id,
            manifest_fingerprint=manifest.fingerprint,
            bridge_bundle=bridge,
        )
        supplied = _read_yaml(Path(independent_verification_path))
        verification_issues = _verification_receipt_issues(
            supplied,
            root=root,
            run_root=run_root,
            manifest=manifest,
            validation_report_path=validation_report_path,
            compatibility_path=bridge / "compatibility_manifest.yml",
        )
        validation_authority_files = {
            "validation_policy_sha256": validation_root
            / "config"
            / "self_evolution_policy.yml",
            "runtime_registry_sha256": validation_root
            / "config"
            / "runtime_registry.yml",
        }
        for field, path in validation_authority_files.items():
            if (
                path.is_symlink()
                or not path.is_file()
                or report.get(field) != sha256(path.read_bytes()).hexdigest()
            ):
                verification_issues.append(f"validation_authority_changed:{field}")
        recorded_authority = report.get("validation_authority_sha256") or {}
        try:
            candidate_authority = _validation_authority_hashes(validation_root)
            runtime_authority = _validation_authority_hashes(root)
        except ValueError:
            candidate_authority = {}
            runtime_authority = {}
        if not (
            recorded_authority
            and recorded_authority == candidate_authority
            and recorded_authority == runtime_authority
        ):
            verification_issues.append("validation_authority_bundle_changed")
        if report.get("status") != "pass" or report.get("commands_executed") is not True:
            verification_issues.append("validation_report_not_passed")
        if not verification_issues:
            verification = {
                "schema_version": 1,
                "report_type": "agentlab_self_evolution_verification_receipt",
                "status": "pass",
                "role": "Verifier",
                "worker": supplied.get("worker"),
                "role_session_id": supplied.get("role_session_id"),
                "execution_attempt_id": supplied.get("execution_attempt_id"),
                "independent": True,
                "role_session_returned": True,
                "candidate_only": True,
                "production_modified": False,
                "promotion_attempted": False,
                "component_id": manifest.component_id,
                "manifest_fingerprint": manifest.fingerprint,
                "evidence": dict(supplied.get("evidence") or {}),
                "source_receipt": str(Path(independent_verification_path).resolve()),
            }
        else:
            verification = {
                "status": "fail",
                "reason": "verification receipt is not bound to the validated candidate",
                "issues": verification_issues,
            }
        _write_yaml(evolution_dir / "independent_verification.yml", verification)
        _append_ledger(
            evolution_dir,
            "verification_attached",
            verification.get("status") or "fail",
        )
        return {
            **report,
            "status": (
                report.get("status")
                if verification.get("status") == "pass"
                else "fail"
            ),
            "validation_snapshot_status": report.get("status"),
            "verification_status": verification.get("status"),
            "verification_issues": verification.get("issues") or [],
        }

    compatibility = _read_yaml(bridge / "compatibility_manifest.yml")
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "check": "compiler_preflight",
            "status": "pass" if compatibility.get("status") == "pass" else "fail",
            "issues": compatibility.get("issues") or [],
        }
    )
    hash_issues: list[str] = []
    for item in compatibility.get("generated_files") or []:
        path = bridge / str(item.get("path") or "")
        if not _hash_matches(path, str(item.get("sha256") or "")):
            hash_issues.append(str(item.get("path") or ""))
    checks.append(
        {
            "check": "generated_hashes",
            "status": "pass" if not hash_issues else "fail",
            "issues": hash_issues,
        }
    )
    validation_root = root
    if workspace:
        validation_root, _ = validate_candidate_worktree(
            root,
            workspace,
            evolution_id=_evolution_workspace_id(root, evolution_dir),
            component_id=manifest.component_id,
        )
        assert_candidate_worktree_scope(
            validation_root,
            component_id=manifest.component_id,
        )
        assert_candidate_bundle_unchanged(
            validation_root,
            component_id=manifest.component_id,
            manifest_fingerprint=manifest.fingerprint,
            bridge_bundle=bridge,
        )
        catalog_issues = RoleCatalog.load(validation_root).validate()
        checks.append(
            {
                "check": "candidate_role_catalog",
                "status": "pass" if not catalog_issues else "fail",
                "issues": catalog_issues,
            }
        )
    receipt = _read_yaml(bridge / "model_selection_receipt.yml")
    decision = receipt.get("decision") or {}
    registry = RuntimeRegistry.load(validation_root)
    selected_route = str(decision.get("route_id") or "")
    allowed_routes = set(
        registry.whitelisted_route_templates(
            allowed_workers=tuple(
                (manifest.spec.get("worker_binding") or {}).get("allowed_workers") or []
            )
        )
    )
    route_ok = selected_route in allowed_routes and decision.get("status") == "selected"
    checks.append(
        {
            "check": "runtime_whitelist",
            "status": "pass" if route_ok else "fail",
            "selected_route": selected_route or None,
        }
    )
    policy_path = validation_root / "config" / "self_evolution_policy.yml"
    runtime_registry_path = validation_root / "config" / "runtime_registry.yml"
    policy = _read_yaml(policy_path)
    commands = (policy.get("validation") or {}).get("commands") or []
    command_receipts: list[dict[str, Any]] = []
    if execute_commands:
        if not workspace:
            command_receipts.append(
                {
                    "command": None,
                    "status": "fail",
                    "reason": "managed_candidate_worktree_required",
                }
            )
        elif not commands:
            command_receipts.append(
                {
                    "command": None,
                    "status": "fail",
                    "reason": "validation_commands_missing",
                }
            )
        else:
            command_output_root = evolution_dir / "validation_command_outputs"
            if command_output_root.is_symlink():
                raise ValueError("validation command output directory is a symlink")
            command_output_root.mkdir(parents=True, exist_ok=True)
            for stale_output in command_output_root.iterdir():
                if stale_output.is_symlink() or stale_output.is_file():
                    stale_output.unlink()
                else:
                    raise ValueError(
                        "validation command output directory contains an unexpected directory"
                    )
            with tempfile.TemporaryDirectory(
                prefix="agentlab-self-evolution-validation-"
            ) as validation_artifact_dir:
                for command_index, command in enumerate(commands, start=1):
                    if not isinstance(command, list) or not all(
                        isinstance(item, str) for item in command
                    ):
                        command_receipts.append(
                            {
                                "command": command,
                                "command_index": command_index,
                                "policy_command": command,
                                "status": "fail",
                                "reason": "invalid_command_contract",
                            }
                        )
                        continue
                    rendered_command = [
                        item.replace(
                            "{validation_artifact_dir}",
                            validation_artifact_dir,
                        )
                        for item in command
                    ]
                    command_receipts.append(
                        _run_validation_command(
                            rendered_command,
                            validation_root,
                            component_id=manifest.component_id,
                            command_index=command_index,
                            policy_command=command,
                            output_path=(
                                command_output_root
                                / f"command_{command_index:02d}.log"
                            ),
                        )
                    )
            assert_candidate_worktree_scope(
                validation_root,
                component_id=manifest.component_id,
            )
            assert_candidate_bundle_unchanged(
                validation_root,
                component_id=manifest.component_id,
                manifest_fingerprint=manifest.fingerprint,
                bridge_bundle=bridge,
            )
    structural_failed = [item for item in checks if item.get("status") != "pass"]
    command_failed = [
        item for item in command_receipts if item.get("status") != "pass"
    ]
    if structural_failed or command_failed:
        validation_status = "fail"
    elif not execute_commands:
        validation_status = "partial"
    else:
        validation_status = "pass"
    report = {
        "schema_version": 1,
        "report_type": "agentlab_self_evolution_validation",
        "component_id": manifest.component_id,
        "manifest_fingerprint": manifest.fingerprint,
        "compatibility_manifest_sha256": sha256(
            (bridge / "compatibility_manifest.yml").read_bytes()
        ).hexdigest(),
        "validation_policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        "runtime_registry_sha256": sha256(
            runtime_registry_path.read_bytes()
        ).hexdigest(),
        "validation_authority_sha256": _validation_authority_hashes(
            validation_root
        ),
        "independent_verifier_worker": str(
            (policy.get("validation") or {}).get("independent_verifier_worker")
            or ""
        ),
        "status": validation_status,
        "structural_status": "pass" if not structural_failed else "fail",
        "checks": checks,
        "command_receipts": command_receipts,
        "commands_executed": execute_commands,
        "required_command_count": len(commands),
        "required_commands": commands,
    }
    validation_report_path = _write_yaml(evolution_dir / "validation_report.yml", report)
    verification = {
        "status": "pending",
        "required_role": "Verifier",
        "same_role_self_verification_allowed": False,
    }
    _write_yaml(evolution_dir / "independent_verification.yml", verification)
    _append_ledger(evolution_dir, "validated", report["status"])
    return report


def mark_review_ready(
    root: Path,
    *,
    evolution_dir: Path,
    publish: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    _task_run_root(root, evolution_dir, field_name="evolution_dir")
    validation = _read_yaml(evolution_dir / "validation_report.yml")
    verification = _read_yaml(evolution_dir / "independent_verification.yml")
    if validation.get("status") != "pass":
        raise ValueError("validation_report.yml must pass before review preparation")
    if validation.get("commands_executed") is not True or not validation.get(
        "command_receipts"
    ):
        raise ValueError("focused and full validation commands must run before review preparation")
    if verification.get("status") != "pass" or verification.get("role") != "Verifier":
        raise ValueError("independent Verifier receipt must pass before review preparation")
    workspace = _read_yaml(evolution_dir / "workspace_receipt.yml")
    manifest = ComponentManifest.load(evolution_dir / "component_manifest.yml")
    verification_issues = _verification_receipt_issues(
        verification,
        root=root,
        run_root=_task_run_root(root, evolution_dir, field_name="evolution_dir"),
        manifest=manifest,
        validation_report_path=evolution_dir / "validation_report.yml",
        compatibility_path=evolution_dir / "bridge_bundle" / "compatibility_manifest.yml",
    )
    if verification_issues:
        raise ValueError(
            "independent Verifier receipt no longer matches the candidate: "
            + ", ".join(verification_issues)
        )
    result = prepare_draft_review(
        root,
        workspace,
        evolution_id=_evolution_workspace_id(root, evolution_dir),
        component_id=manifest.component_id,
        manifest_fingerprint=manifest.fingerprint,
        bridge_bundle=evolution_dir / "bridge_bundle",
        publish=publish,
    )
    _write_yaml(evolution_dir / "review_ready_receipt.yml", result)
    _append_ledger(evolution_dir, "review_ready", result.get("status") or "review_ready")
    return result


def evolution_status(root: Path, evolution_dir: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    _task_run_root(root, evolution_dir, field_name="evolution_dir")
    ledger = _read_yaml(evolution_dir / "evolution_ledger.yml")
    return {
        "evolution_dir": str(evolution_dir),
        "status": ledger.get("status") or "unknown",
        "current_stage": ledger.get("current_stage") or "unknown",
        "component": _read_yaml(evolution_dir / "component_proposal.yml").get("component_id"),
        "validation": _read_yaml(evolution_dir / "validation_report.yml").get("status"),
        "verification": _read_yaml(evolution_dir / "independent_verification.yml").get("status"),
        "review": _read_yaml(evolution_dir / "review_ready_receipt.yml").get("status"),
    }


def write_rollback_candidate(root: Path, evolution_dir: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    evolution_dir = Path(evolution_dir).resolve()
    _task_run_root(root, evolution_dir, field_name="evolution_dir")
    review = _read_yaml(evolution_dir / "review_ready_receipt.yml")
    commit = str(review.get("commit") or "")
    if review.get("status") not in {
        "local_review_ready",
        "branch_published_review_bundle",
        "draft_pr_created",
    } or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("a review-ready component commit is required for rollback")
    manifest = ComponentManifest.load(evolution_dir / "component_manifest.yml")
    changed = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if changed.returncode != 0:
        raise ValueError("review-ready component commit is unavailable")
    changed_paths = sorted(path for path in changed.stdout.splitlines() if path)
    allowed_manifest = f"config/components/agents/{manifest.component_id}.yml"
    allowed_generated = f"config/generated/roles/{manifest.component_id}/"
    if not changed_paths or any(
        path != allowed_manifest and not path.startswith(allowed_generated)
        for path in changed_paths
    ):
        raise ValueError("rollback target commit contains paths outside the component")
    reverse_diff = subprocess.run(
        ["git", "diff", "--binary", "-R", f"{commit}^", commit],
        cwd=root,
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if reverse_diff.returncode != 0 or not reverse_diff.stdout:
        raise ValueError("unable to build the component rollback patch")
    patch_path = evolution_dir / "rollback.patch"
    if patch_path.is_symlink():
        raise ValueError("rollback patch path is a symlink")
    patch_path.write_bytes(reverse_diff.stdout)
    result = {
        "status": "rollback_review_ready",
        "target_commit": commit,
        "component_id": manifest.component_id,
        "changed_paths": changed_paths,
        "strategy": "apply_hash_bound_reverse_patch_then_create_reviewed_revert_commit",
        "rollback_patch": str(patch_path.relative_to(root)),
        "rollback_patch_sha256": sha256(patch_path.read_bytes()).hexdigest(),
        "preflight_command": ["git", "apply", "--check", str(patch_path)],
        "apply_command": ["git", "apply", str(patch_path)],
        "automatic_execution": False,
        "direct_main_mutation": False,
        "human_merge_required": True,
    }
    _write_yaml(evolution_dir / "rollback_candidate.yml", result)
    _append_ledger(evolution_dir, "rollback_ready", "pending_human_review")
    return result
