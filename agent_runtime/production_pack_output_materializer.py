"""Materialize provider-returned production-pack candidate artifacts."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

try:
    from atomic_io import atomic_write_text, atomic_write_yaml
    from patch_applicator import parse_edit_blocks, strip_edit_blocks_from_report
    from production_pack_registry import validate_pack_candidate
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
    from agent_runtime.patch_applicator import (
        parse_edit_blocks,
        strip_edit_blocks_from_report,
    )
    from agent_runtime.production_pack_registry import validate_pack_candidate


REQUIRED_SYNTHESIS_OUTPUTS = (
    "production_pack_proposal.yml",
    "domain_memory_contract.yml",
    "lifecycle_profile.yml",
)


def _strip_optional_code_fence(content: str) -> str:
    lines = content.strip().splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().startswith("```")
        and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1]).strip()
    return content.strip()


def _target_issue(
    raw_path: str, task_id: str, required: set[str]
) -> tuple[str | None, str | None]:
    normalized = raw_path.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return None, f"unsafe_production_pack_output_path:{normalized or '<blank>'}"
    if path.name not in required:
        return None, f"unexpected_production_pack_output:{normalized}"
    allowed_shapes = {
        (path.name,),
        ("runs", task_id, path.name),
    }
    if path.parts not in allowed_shapes:
        if len(path.parts) >= 2 and path.parts[-2] != task_id:
            return None, f"production_pack_output_wrong_run:{normalized}"
        return None, f"production_pack_output_invalid_scope:{normalized}"
    return path.name, None


def _safe_result_metadata(result: Any, execution_mode: str) -> dict[str, Any]:
    raw_usage = getattr(result, "raw_usage", None) or {}
    return {
        "provider": str(getattr(result, "provider", "") or "unknown"),
        "model": str(getattr(result, "model", "") or "unknown"),
        "result_status": str(getattr(result, "status", "") or "unknown"),
        "execution_mode": execution_mode,
        "executor_type": raw_usage.get("executor_type"),
        "configured_cli_agent": raw_usage.get("configured_cli_agent")
        or raw_usage.get("cli_agent"),
        "command_id": raw_usage.get("command_id"),
    }


def _candidate_boundary_issues(proposal: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    pack = proposal.get("pack") if isinstance(proposal.get("pack"), dict) else proposal
    promotion = pack.get("promotion_policy") if isinstance(pack, dict) else {}
    if proposal.get("candidate_only") is not True:
        issues.append("production_pack_proposal_missing_candidate_only")
    if proposal.get("production_modified") is not False:
        issues.append("production_pack_proposal_must_not_modify_production")
    if not isinstance(promotion, dict) or promotion.get("auto_promote") is not False:
        issues.append("production_pack_proposal_must_disable_auto_promotion")
    if (
        isinstance(promotion, dict)
        and promotion.get("production_modified") is not False
    ):
        issues.append("production_pack_promotion_policy_must_not_modify_production")
    return issues


def materialize_production_pack_candidate_result(
    result: Any,
    run_dir: Path,
    task_id: str,
    catalog_path: Path,
    *,
    execution_mode: str,
    required_outputs: tuple[str, ...] = REQUIRED_SYNTHESIS_OUTPUTS,
    capture_name: str = "production_pack_role_session_capture.md",
    contract_name: str = "production_pack_output_contract.yml",
) -> bool:
    """Write exactly one same-run full-file block for every required pack artifact."""
    run_dir.mkdir(parents=True, exist_ok=True)
    content = str(getattr(result, "content", "") or "")
    atomic_write_text(run_dir / capture_name, content)

    required = set(required_outputs)
    materialized: dict[str, str] = {}
    parsed_yaml: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    raw_usage = getattr(result, "raw_usage", None) or {}
    native_materialized = (
        raw_usage.get("artifact_materialization_status") == "pass"
        and bool(raw_usage.get("artifact_materialization_receipt"))
    )
    if getattr(result, "status", None) != "completed":
        issues.append("production_pack_role_result_not_completed")
    if not content.strip():
        issues.append("production_pack_role_result_empty")

    if native_materialized:
        receipt_path = Path(str(raw_usage["artifact_materialization_receipt"]))
        try:
            receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            receipt = {}
        receipt_records = {
            Path(str(item.get("path") or "")).name: item
            for item in receipt.get("materialized", [])
            if isinstance(item, dict)
        } if isinstance(receipt, dict) else {}
        for name in required_outputs:
            path = run_dir / name
            record = receipt_records.get(name)
            if not path.is_file() or not isinstance(record, dict):
                issues.append(f"missing_production_pack_output:{name}")
                continue
            raw_bytes = path.read_bytes()
            digest = sha256(raw_bytes).hexdigest()
            if (
                record.get("sha256") != digest
                or int(record.get("byte_count") or -1) != len(raw_bytes)
            ):
                issues.append(f"production_pack_output_receipt_mismatch:{name}")
                continue
            try:
                value = raw_bytes.decode("utf-8")
                parsed = yaml.safe_load(value)
            except (UnicodeDecodeError, yaml.YAMLError) as exc:
                issues.append(
                    f"invalid_production_pack_yaml:{name}:{type(exc).__name__}"
                )
                continue
            if not isinstance(parsed, dict):
                issues.append(f"production_pack_output_must_be_yaml_mapping:{name}")
                continue
            if execution_mode == "execute" and parsed.get("generated_by") == "fake_provider":
                issues.append(f"fake_provider_production_pack_output:{name}")
                continue
            materialized[name] = value
            parsed_yaml[name] = parsed
    else:
        for block in parse_edit_blocks(content):
            raw_path = str(block.get("path") or "")
            name, target_issue = _target_issue(raw_path, task_id, required)
            if target_issue:
                issues.append(target_issue)
                continue
            assert name is not None
            if name in materialized:
                issues.append(f"duplicate_production_pack_output:{name}")
                continue
            if "html_block_content" not in block:
                issues.append(f"production_pack_output_requires_full_file_block:{name}")
                continue
            value = _strip_optional_code_fence(str(block.get("html_block_content") or ""))
            if not value:
                issues.append(f"empty_production_pack_output:{name}")
                continue
            try:
                parsed = yaml.safe_load(value)
            except yaml.YAMLError as exc:
                issues.append(f"invalid_production_pack_yaml:{name}:{type(exc).__name__}")
                continue
            if not isinstance(parsed, dict):
                issues.append(f"production_pack_output_must_be_yaml_mapping:{name}")
                continue
            if (
                execution_mode == "execute"
                and parsed.get("generated_by") == "fake_provider"
            ):
                issues.append(f"fake_provider_production_pack_output:{name}")
                continue
            materialized[name] = value
            parsed_yaml[name] = parsed

    for name in required_outputs:
        if name not in materialized:
            issues.append(f"missing_production_pack_output:{name}")

    research_contract_path = run_dir / "production_pack_research_contract.yml"
    research_contract = (
        yaml.safe_load(research_contract_path.read_text(encoding="utf-8")) or {}
        if research_contract_path.exists()
        else {}
    )
    if execution_mode == "execute" and research_contract.get("status") != "pass":
        issues.append("production_pack_research_contract_not_passed")

    if "production_pack_proposal.yml" in parsed_yaml:
        issues.extend(
            _candidate_boundary_issues(parsed_yaml["production_pack_proposal.yml"])
        )

    output_hashes = {
        name: {
            "sha256": sha256(value.encode("utf-8")).hexdigest(),
            "bytes": len(value.encode("utf-8")),
        }
        for name, value in materialized.items()
    }
    contract: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "agentlab_production_pack_output_contract",
        "status": "blocked" if issues else "materialized_pending_validation",
        "task_id": task_id,
        "capture_path": capture_name,
        "required_outputs": list(required_outputs),
        "materialized_outputs": [] if issues else sorted(materialized),
        "returned_artifact_source": (
            "isolated_cli_declared_files"
            if native_materialized
            else "provider_role_session_edit_blocks"
        ),
        "provider_returned_outputs": not issues,
        "harness_generated_pack_content": False,
        # Candidate files are never promoted here, but native CLI files already
        # exist in the current run and edit-block files are written before the
        # semantic pack validator runs. Do not overstate that ordering as a
        # transactional commit.
        "transactional_before_validation": False,
        "candidate_only": True,
        "production_modified": False,
        "promotion_attempted": False,
        "source": _safe_result_metadata(result, execution_mode),
        "research_contract_path": research_contract_path.name,
        "research_contract_status": research_contract.get("status"),
        "output_hashes": output_hashes if not issues else {},
        "proposal_validation": {},
        "issues": issues,
    }
    if issues:
        atomic_write_yaml(
            run_dir / contract_name, contract, sort_keys=False, allow_unicode=True
        )
        return False

    if not native_materialized:
        for name, value in materialized.items():
            atomic_write_text(run_dir / name, value.rstrip() + "\n")

    validation = validate_pack_candidate(
        run_dir / "production_pack_proposal.yml",
        catalog_path,
    )
    contract["proposal_validation"] = validation.as_dict()
    if validation.valid:
        contract["status"] = "pass"
    else:
        contract["status"] = "blocked"
        contract["issues"] = [
            f"production_pack_validation:{issue}" for issue in validation.issues
        ]
    atomic_write_yaml(
        run_dir / contract_name, contract, sort_keys=False, allow_unicode=True
    )
    return bool(validation.valid)


def artifact_producer_report_content(result: Any) -> str:
    """Return the readable report while preserving raw role output in its capture file."""
    content = str(getattr(result, "content", "") or "")
    readable = strip_edit_blocks_from_report(content).strip()
    return (
        readable
        or "Production-pack candidate files returned through structured edit blocks."
    )


def write_production_pack_verification_receipt(
    result: Any,
    run_dir: Path,
    catalog_path: Path,
    *,
    execution_mode: str,
) -> dict[str, Any]:
    """Bind Verifier completion to the materialized candidate and registry validation."""
    contract_path = run_dir / "production_pack_output_contract.yml"
    contract = (
        yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        if contract_path.exists()
        else {}
    )
    validation = validate_pack_candidate(
        run_dir / "production_pack_proposal.yml",
        catalog_path,
    )
    result_metadata = _safe_result_metadata(result, execution_mode)
    verifier_returned = (
        getattr(result, "status", None) == "completed"
        and bool(str(getattr(result, "content", "") or "").strip())
        and result_metadata["provider"] != "fake_provider"
        and execution_mode == "execute"
    )
    issues: list[str] = []
    if contract.get("status") != "pass":
        issues.append("production_pack_output_contract_not_passed")
    if not validation.valid:
        issues.extend(
            f"production_pack_validation:{item}" for item in validation.issues
        )
    if not verifier_returned:
        issues.append("verifier_role_session_not_returned")
    receipt = {
        "schema_version": 1,
        "report_type": "agentlab_production_pack_verification_receipt",
        "status": "pass" if not issues else "blocked",
        "candidate_only": True,
        "production_modified": False,
        "promotion_attempted": False,
        "output_contract_path": contract_path.name,
        "output_contract_status": contract.get("status"),
        "proposal_validation": validation.as_dict(),
        "verifier": result_metadata,
        "verifier_role_session_returned": verifier_returned,
        "issues": issues,
    }
    atomic_write_yaml(
        run_dir / "production_pack_verification_receipt.yml",
        receipt,
        sort_keys=False,
        allow_unicode=True,
    )
    return receipt
