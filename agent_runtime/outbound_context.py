"""Deterministic safety receipts for provider-bound AgentLab context."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable

try:
    from agent_runtime.report_sanitizer import write_report_yaml
    from agent_runtime.runtime_hygiene.secret_scan import SECRET_PATTERNS
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml
    from runtime_hygiene.secret_scan import SECRET_PATTERNS


TRUSTED_RUNNER_ENV_NAME = "AGENTLAB_TRUSTED_LIVE_RUNNER"
PRIVATE_CONTEXT_APPROVAL_ENV_NAME = "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED"
PRIVATE_CONTEXT_APPROVAL_PAYLOAD_SHA256_ENV_NAME = (
    "AGENTLAB_ROLE_SESSION_ACCEPTANCE_PAYLOAD_SHA256"
)
PRIVATE_CONTEXT_APPROVAL_SCOPE_SHA256_ENV_NAME = (
    "AGENTLAB_ROLE_SESSION_ACCEPTANCE_SCOPE_SHA256"
)
PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME = (
    "AGENTLAB_PRODUCTION_PACK_CONTEXT_APPROVED"
)
_FORBIDDEN_SOURCE_NAMES = {
    ".agents",
    ".codex",
    ".env",
    ".git",
    ".gnupg",
    ".hermes",
    ".ssh",
    "credentials",
    "secrets",
}
_FORBIDDEN_SOURCE_SUFFIXES = {".key", ".pem"}
_PLACEHOLDER_MARKERS = (
    "placeholder",
    "dummy",
    "example",
    "your_",
    "test-key",
    "xxx",
    "tbd",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _secret_pattern_names(text: str) -> list[str]:
    matches: list[str] = []
    for name, pattern in SECRET_PATTERNS.items():
        found = False
        for match in pattern.finditer(text):
            matched_text = match.group(0).lower()
            if any(marker in matched_text for marker in _PLACEHOLDER_MARKERS):
                continue
            if name == "Generic Assignment Secret":
                key = (
                    matched_text.split(":", 1)[0]
                    .split("=", 1)[0]
                    .strip()
                    .replace("-", "_")
                )
                value = str(match.group(1) if match.groups() else "")
                if key == "secret":
                    character_classes = sum(
                        any(test(char) for char in value)
                        for test in (str.islower, str.isupper, str.isdigit)
                    )
                    if len(value) < 16 or character_classes < 2:
                        continue
            found = True
            break
        if found:
            matches.append(str(name))
    return sorted(matches)


def _relative_source(root: Path, path: Path) -> tuple[str, bool]:
    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        return resolved_path.relative_to(resolved_root).as_posix(), True
    except ValueError:
        return "<outside-agentlab-root>", False


def is_forbidden_source_path(path: Path) -> bool:
    """Return whether *path* names a sensitive source that must not be read."""

    candidate = Path(path)
    return any(
        part.lower() in _FORBIDDEN_SOURCE_NAMES
        or part.lower().startswith(".env")
        for part in candidate.parts
    ) or candidate.suffix.lower() in _FORBIDDEN_SOURCE_SUFFIXES


def _source_records(
    root: Path, source_paths: Iterable[Path]
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[Path] = set()
    for raw_path in source_paths:
        path = Path(raw_path)
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        relative, inside_root = _relative_source(root, path)
        forbidden_name = is_forbidden_source_path(path)
        exists = path.is_file()
        is_symlink = path.is_symlink()
        record: dict[str, Any] = {
            "path": relative,
            "inside_agentlab_root": inside_root,
            "exists": exists,
            "is_symlink": is_symlink,
            "forbidden_name": forbidden_name,
        }
        if exists and inside_root and not forbidden_name and not is_symlink:
            payload = path.read_bytes()
            record.update({"bytes": len(payload), "sha256": _sha256_bytes(payload)})
        records.append(record)
        if not inside_root:
            issues.append(f"source_outside_agentlab_root:{relative}")
        if forbidden_name:
            issues.append(f"forbidden_source_path:{relative}")
        if is_symlink:
            issues.append(f"symlink_source_forbidden:{relative}")
        if not exists:
            issues.append(f"source_missing:{relative}")
    return records, issues


def build_outbound_context_manifest(
    root: Path,
    *,
    item_id: str,
    role: str,
    provider_surface: str,
    payload_kind: str,
    payload_text: str,
    source_paths: Iterable[Path] = (),
    private_context: bool,
    exact_payload: bool,
    sealed_context: bool,
    execution_workspace_isolated: bool,
    approval_required: bool,
    approval_granted: bool | None = None,
    approval_env_name: str = PRIVATE_CONTEXT_APPROVAL_ENV_NAME,
    approval_payload_sha256_required: bool = False,
    approved_payload_sha256: str | None = None,
    approval_payload_sha256_env_name: str = (
        PRIVATE_CONTEXT_APPROVAL_PAYLOAD_SHA256_ENV_NAME
    ),
    approval_scope_sha256_required: bool = False,
    approval_scope_contract_valid: bool = True,
    expected_scope_sha256: str | None = None,
    approved_scope_sha256: str | None = None,
    approval_scope_sha256_env_name: str = (
        PRIVATE_CONTEXT_APPROVAL_SCOPE_SHA256_ENV_NAME
    ),
    provider_project_scan_requested: bool = False,
    provider_shell_or_browser_requested: bool = False,
    source_inventory_required: bool = False,
    approval_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a content-free receipt for the exact provider-bound payload."""
    root = root.resolve(strict=False)
    if approval_granted is None:
        approval_granted = os.getenv(approval_env_name) == "1"

    payload_bytes = payload_text.encode("utf-8")
    payload_sha256 = _sha256_bytes(payload_bytes)
    if approved_payload_sha256 is None:
        approved_payload_sha256 = str(
            os.getenv(approval_payload_sha256_env_name) or ""
        ).strip()
    if approved_scope_sha256 is None:
        approved_scope_sha256 = str(
            os.getenv(approval_scope_sha256_env_name) or ""
        ).strip()
    secret_patterns = _secret_pattern_names(payload_text)
    sources, source_issues = _source_records(root, source_paths)
    issues = list(source_issues)
    if not payload_text.strip():
        issues.append("outbound_payload_empty")
    if not exact_payload:
        issues.append("outbound_payload_not_exact")
    if source_inventory_required and not sources:
        issues.append("source_inventory_empty")
    if private_context and not sealed_context:
        issues.append("private_context_not_sealed")
    if secret_patterns:
        issues.append("secret_pattern_detected")
    if approval_required and not approval_granted:
        issues.append("explicit_private_context_approval_missing")
    if approval_required and approval_granted and approval_payload_sha256_required:
        if not approved_payload_sha256:
            issues.append(
                "explicit_private_context_payload_sha256_approval_missing"
            )
        elif approved_payload_sha256 != payload_sha256:
            issues.append("approved_private_context_payload_sha256_mismatch")
    if approval_scope_sha256_required:
        if not approval_scope_contract_valid or not expected_scope_sha256:
            issues.append("narrative_approval_scope_contract_invalid")
        elif approval_required and approval_granted:
            if not approved_scope_sha256:
                issues.append(
                    "explicit_private_context_scope_sha256_approval_missing"
                )
            elif approved_scope_sha256 != expected_scope_sha256:
                issues.append("approved_private_context_scope_sha256_mismatch")

    only_approval_pending = bool(issues) and all(
        issue
        in {
            "explicit_private_context_approval_missing",
            "explicit_private_context_payload_sha256_approval_missing",
            "explicit_private_context_scope_sha256_approval_missing",
        }
        for issue in issues
    )
    status = (
        "pass"
        if not issues
        else "pending_approval"
        if only_approval_pending
        else "blocked"
    )
    return {
        "schema_version": 1,
        "report_type": "agentlab_outbound_context_manifest",
        "item_id": item_id,
        "role": role,
        "provider_surface": provider_surface,
        "status": status,
        "execution_allowed": status == "pass",
        "context_boundary": {
            "private_context": private_context,
            "sealed_context": sealed_context,
            "exact_payload_hashed": exact_payload,
            "execution_workspace_isolated": execution_workspace_isolated,
            "provider_project_scan_requested": provider_project_scan_requested,
            "provider_shell_or_browser_requested": (
                provider_shell_or_browser_requested
            ),
            "payload_contents_rendered_in_manifest": False,
        },
        "payload": {
            "kind": payload_kind,
            "bytes": len(payload_bytes),
            "sha256": payload_sha256,
            "secret_pattern_hit_count": len(secret_patterns),
            "secret_pattern_names": secret_patterns,
        },
        "source_inventory": {
            "count": len(sources),
            "required": source_inventory_required,
            "content_rendered": False,
            "files": sources,
        },
        "authorization": {
            "approval_required": approval_required,
            "approval_env_name": approval_env_name,
            "approval_observed": bool(approval_granted),
            "payload_sha256_required": approval_payload_sha256_required,
            "payload_sha256_env_name": approval_payload_sha256_env_name,
            "payload_sha256_observed": bool(approved_payload_sha256),
            "payload_sha256_matched": (
                approved_payload_sha256 == payload_sha256
                if approved_payload_sha256
                else False
            ),
            "scope_sha256_required": approval_scope_sha256_required,
            "scope_contract_valid": approval_scope_contract_valid,
            "scope_sha256_env_name": approval_scope_sha256_env_name,
            "scope_sha256_expected": expected_scope_sha256,
            "scope_sha256_observed": bool(approved_scope_sha256),
            "scope_sha256_matched": (
                approved_scope_sha256 == expected_scope_sha256
                if approved_scope_sha256 and expected_scope_sha256
                else False
            ),
            "trusted_runner_env_name": TRUSTED_RUNNER_ENV_NAME,
            "trusted_runner_observed": os.getenv(TRUSTED_RUNNER_ENV_NAME) == "1",
            "env_values_rendered": False,
            "authority": dict(approval_authority or {}),
        },
        "issues": issues,
    }


def write_outbound_context_manifest(
    root: Path,
    out: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    report = build_outbound_context_manifest(root, **kwargs)
    write_report_yaml(out, report, root)
    return report
