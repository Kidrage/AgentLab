"""Preflight a trusted live runner package without provider calls."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _resolve_path(root: Path, path_text: str | None, fallback: Path) -> Path:
    if not path_text:
        return fallback
    path = Path(path_text)
    return path if path.is_absolute() else root / path


def _file_check(id_: str, path: Path, *, executable: bool = False) -> dict[str, Any]:
    exists = path.exists()
    is_executable = path.is_file() and exists and path.stat().st_mode & 0o111 != 0
    status = "pass" if exists and (not executable or is_executable) else "fail"
    issue = None
    if not exists:
        issue = "missing"
    elif executable and not is_executable:
        issue = "not_executable"
    return {
        "id": id_,
        "kind": "file",
        "path": str(path),
        "status": status,
        **({"issue": issue} if issue else {}),
    }


def _command_check(command: str) -> dict[str, Any]:
    resolved = shutil.which(command)
    return {
        "id": f"command:{command}",
        "kind": "command",
        "command": command,
        "status": "pass" if resolved else "fail",
        **({"path": resolved} if resolved else {"issue": "not_found"}),
    }


def _policy_check(id_: str, observed: Any) -> dict[str, Any]:
    return {
        "id": id_,
        "kind": "policy",
        "status": "pass" if observed is True else "fail",
        "observed": observed is True,
        **({"issue": "not_declared"} if observed is not True else {}),
    }


def build_trusted_live_runner_preflight(root: Path, request_path: Path | None = None) -> dict[str, Any]:
    """Inspect local runner prerequisites without reading private project context."""
    root = root.resolve()
    request_path = request_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml"
    )
    if not request_path.is_absolute():
        request_path = root / request_path
    request = _read_yaml(request_path)
    package = request.get("local_runner_package") if isinstance(request.get("local_runner_package"), dict) else {}
    script_path = _resolve_path(
        root,
        str(package.get("entrypoint") or request.get("script_path") or ""),
        request_path.with_suffix(".sh"),
    )
    status_path = _resolve_path(
        root,
        str(package.get("status_path") or ""),
        request_path.with_name("trusted_live_runner_status.yml"),
    )
    checks = [
        _file_check("request_yaml", request_path),
        _file_check("runner_script", script_path, executable=True),
        _file_check("agentlab_entrypoint", root / "agentlab.sh", executable=True),
        _command_check("agy"),
        _command_check("hermes"),
        _policy_check(
            "exact_outbound_context_manifest_required",
            package.get("exact_outbound_context_manifest_required"),
        ),
        _policy_check("writer_sealed_context_required", package.get("writer_sealed_context_required")),
        _policy_check("media_prompt_digest_required", package.get("media_prompt_digest_required")),
        _policy_check(
            "secret_pattern_gate_before_provider_call",
            package.get("secret_pattern_gate_before_provider_call"),
        ),
    ]
    issues: list[str] = []
    if request.get("status") != "ready_for_trusted_runner":
        issues.append("trusted_live_runner_request_not_ready")
    if not package:
        issues.append("local_runner_package_missing")
    issues.extend(f"{check['id']}:{check.get('issue')}" for check in checks if check["status"] != "pass")

    return {
        "schema_version": 1,
        "report_type": "agentlab_trusted_live_runner_preflight",
        "root": str(root),
        "request_path": str(request_path),
        "script_path": str(script_path),
        "status_path": str(status_path),
        "request_id": request.get("request_id"),
        "status": "pass" if not issues else "fail",
        "executes_provider_calls": False,
        "loads_private_project_context": False,
        "safe_scope": "local binary/path preflight only",
        "private_context_runtime_guard": {
            "exact_manifest_required": package.get("exact_outbound_context_manifest_required") is True,
            "writer_sealed_context_required": package.get("writer_sealed_context_required") is True,
            "media_prompt_digest_required": package.get("media_prompt_digest_required") is True,
            "secret_pattern_gate_before_provider_call": (
                package.get("secret_pattern_gate_before_provider_call") is True
            ),
            "provider_calls_remain_blocked_until_runtime_manifest_passes": True,
        },
        "checks": checks,
        "issues": issues,
    }


def write_trusted_live_runner_preflight(root: Path, out: Path, request_path: Path | None = None) -> dict[str, Any]:
    report = build_trusted_live_runner_preflight(root, request_path=request_path)
    write_report_yaml(out, report, root)
    return report
