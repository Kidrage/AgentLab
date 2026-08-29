"""Detached external approval signatures with an out-of-workspace trust root."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import subprocess
import yaml


def approval_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def narrative_outbound_approval_payload(
    *,
    project: str,
    task_id: str,
    recipient: str,
    purpose: str,
    packet_payload_sha256: str,
    scope_sha256: str,
    expires_at: str,
) -> dict[str, str]:
    return {
        "schema_version": "narrative-outbound-approval-signature/v1",
        "project": project,
        "task_id": task_id,
        "recipient": recipient,
        "purpose": purpose,
        "packet_payload_sha256": packet_payload_sha256,
        "scope_sha256": scope_sha256,
        "expires_at": expires_at,
    }


def verify_detached_approval(
    payload: Mapping[str, Any],
    *,
    signature_path: Path,
    public_key_path: Path,
    forbidden_root: Path,
) -> dict[str, str]:
    """Verify an OpenSSL detached signature whose authority is outside a root."""

    forbidden = Path(forbidden_root).resolve(strict=True)
    if not str(signature_path).strip() or not str(public_key_path).strip():
        raise ValueError("approval signature authority paths are required")
    raw_signature = Path(signature_path)
    raw_public_key = Path(public_key_path)
    if raw_signature.is_symlink() or raw_public_key.is_symlink():
        raise ValueError("approval signature authority may not use symlinks")
    signature = raw_signature.resolve(strict=True)
    public_key = raw_public_key.resolve(strict=True)
    if not signature.is_file() or not public_key.is_file():
        raise ValueError("approval signature authority must use regular files")
    for authority_path in (signature, public_key):
        try:
            authority_path.relative_to(forbidden)
        except ValueError:
            pass
        else:
            raise ValueError(
                "approval signature authority must be outside the governed root"
            )
    completed = subprocess.run(
        [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-verify",
            str(public_key),
            "-signature",
            str(signature),
        ],
        input=approval_payload_bytes(payload),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("detached approval signature verification failed")
    return {
        "signature_path": str(signature),
        "signature_sha256": hashlib.sha256(signature.read_bytes()).hexdigest(),
        "public_key_path": str(public_key),
        "public_key_sha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
        "signed_payload_sha256": hashlib.sha256(
            approval_payload_bytes(payload)
        ).hexdigest(),
    }


def pinned_approval_public_key(
    agentlab_root: Path,
    *,
    section: str,
) -> Path:
    """Load one SHA-pinned approval key from untracked private topology."""

    root = Path(agentlab_root).resolve(strict=True)
    config_path = root / "config" / "local_private_topology.yml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("private approval authority is not configured") from exc
    authority = config.get(section) if isinstance(config, Mapping) else None
    if not isinstance(authority, Mapping):
        raise ValueError("private approval authority is not configured")
    public_key = Path(str(authority.get("public_key_path") or ""))
    expected_sha256 = str(authority.get("public_key_sha256") or "")
    if (
        not str(public_key).strip()
        or len(expected_sha256) != 64
        or any(value not in "0123456789abcdef" for value in expected_sha256)
        or public_key.is_symlink()
    ):
        raise ValueError("private approval authority is invalid")
    public_key = public_key.resolve(strict=True)
    try:
        public_key.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("approval public key must be outside AgentLab")
    if (
        not public_key.is_file()
        or hashlib.sha256(public_key.read_bytes()).hexdigest()
        != expected_sha256
    ):
        raise ValueError("approval public key pin mismatch")
    return public_key
