"""Append-only, hash-chained user acceptance authority for Candidate Sets."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
import fcntl
import getpass
import hashlib
import json
import os
import re
import subprocess

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
from agent_runtime.narrative.candidates.manifest import validate_candidate_set

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _event_hash(event: Mapping[str, Any]) -> str:
    return _hash({key: value for key, value in event.items() if key != "event_hash"})


def _paths(project_root: Path) -> tuple[Path, Path, Path]:
    authority = project_root / "project_brain" / "user_acceptance"
    return (
        authority / "events.jsonl",
        authority / "receipts",
        authority / ".lock",
    )


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"user acceptance ledger line {line_number} is invalid"
            ) from exc
        if (
            not isinstance(event, dict)
            or event.get("schema_version")
            != "narrative-user-acceptance-event/v1"
            or event.get("sequence") != line_number
            or event.get("previous_event_hash") != previous_hash
            or event.get("event_hash") != _event_hash(event)
        ):
            raise ValueError("user acceptance ledger integrity failure")
        previous_hash = str(event["event_hash"])
        events.append(event)
    return events


def _append_event(path: Path, event: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        dict(event),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _parse_approved_at(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("approved_at must be timezone-aware")
    return value


def candidate_acceptance_payload(
    *,
    actor_id: str,
    idempotency_key: str,
    approved_at: str,
    candidate_set_id: str,
    candidate_set_sha256: str,
    evidence_bundle_sha256: str,
) -> dict[str, Any]:
    """Return the exact payload that an external user authority must sign."""

    return {
        "schema_version": "narrative-user-acceptance-signature-payload/v1",
        "action": "accept_candidate_set",
        "actor_type": "user",
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "approved_at": approved_at,
        "candidate_set_id": candidate_set_id,
        "candidate_set_sha256": candidate_set_sha256,
        "evidence_bundle_sha256": evidence_bundle_sha256,
    }


def _signature_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _verify_external_signature(
    project_root: Path,
    *,
    payload: Mapping[str, Any],
    signature_path: Path,
    public_key_path: Path,
) -> dict[str, str]:
    agentlab_root = project_root.parent.parent.resolve(strict=True)
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
            authority_path.relative_to(agentlab_root)
        except ValueError:
            pass
        else:
            raise ValueError(
                "approval signature authority must be outside AgentLab"
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
        input=_signature_bytes(payload),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("user acceptance signature verification failed")
    return {
        "signature_path": str(signature),
        "signature_sha256": hashlib.sha256(signature.read_bytes()).hexdigest(),
        "public_key_path": str(public_key),
        "public_key_sha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
        "signed_payload_sha256": hashlib.sha256(
            _signature_bytes(payload)
        ).hexdigest(),
    }


def _pinned_public_key(project_root: Path) -> Path:
    agentlab_root = project_root.parent.parent.resolve(strict=True)
    config_path = agentlab_root / "config" / "local_private_topology.yml"
    config = safe_read_yaml(config_path, default=None)
    authority = (
        config.get("user_approval_authority")
        if isinstance(config, Mapping)
        else None
    )
    if not isinstance(authority, Mapping):
        raise ValueError("private user approval authority is not configured")
    public_key = Path(str(authority.get("public_key_path") or ""))
    expected_sha256 = str(authority.get("public_key_sha256") or "")
    if (
        not str(public_key).strip()
        or not _SHA256.fullmatch(expected_sha256)
        or public_key.is_symlink()
    ):
        raise ValueError("private user approval authority is invalid")
    public_key = public_key.resolve(strict=True)
    try:
        public_key.relative_to(agentlab_root)
    except ValueError:
        pass
    else:
        raise ValueError("user approval public key must be outside AgentLab")
    if (
        not public_key.is_file()
        or hashlib.sha256(public_key.read_bytes()).hexdigest()
        != expected_sha256
    ):
        raise ValueError("user approval public key pin mismatch")
    return public_key


def record_candidate_acceptance(
    project_root: Path,
    *,
    manifest_path: Path,
    actor_id: str,
    idempotency_key: str,
    approved_at: str,
    signature_path: Path,
) -> dict[str, Any]:
    """Record one explicit local-user acceptance and return its immutable receipt."""

    root = Path(project_root).resolve(strict=True)
    manifest_candidate = Path(manifest_path)
    if manifest_candidate.is_symlink():
        raise ValueError("candidate manifest may not be a symlink")
    manifest_path = manifest_candidate.resolve(strict=True)
    manifest_path.relative_to(root)
    actor_id = str(actor_id or "").strip()
    idempotency_key = str(idempotency_key or "").strip()
    if not _SAFE_ID.fullmatch(actor_id):
        raise ValueError("actor_id is invalid")
    if not _SAFE_ID.fullmatch(idempotency_key):
        raise ValueError("idempotency_key is invalid")
    _parse_approved_at(approved_at)
    manifest = safe_read_yaml(manifest_path, default=None)
    if not isinstance(manifest, dict) or manifest.get("status") != "frozen":
        raise ValueError("candidate set must be frozen before user acceptance")
    if validate_candidate_set(root, manifest_path).get("status") != "pass":
        raise ValueError("candidate set is stale")
    candidate_set_id = str(manifest.get("candidate_set_id") or "")
    candidate_set_sha256 = str(manifest.get("candidate_set_sha256") or "")
    if not _SAFE_ID.fullmatch(candidate_set_id) or not _SHA256.fullmatch(
        candidate_set_sha256
    ):
        raise ValueError("candidate set identity is invalid")
    from agent_runtime.narrative.candidates.promotion import (
        evidence_bundle_sha256,
    )

    evidence_sha256 = evidence_bundle_sha256(root, manifest)
    signed_payload = candidate_acceptance_payload(
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        approved_at=approved_at,
        candidate_set_id=candidate_set_id,
        candidate_set_sha256=candidate_set_sha256,
        evidence_bundle_sha256=evidence_sha256,
    )
    signature_authority = _verify_external_signature(
        root,
        payload=signed_payload,
        signature_path=signature_path,
        public_key_path=_pinned_public_key(root),
    )
    ledger_path, receipts_root, lock_path = _paths(root)
    with _lock(lock_path):
        events = _load_events(ledger_path)
        for event in events:
            if event.get("idempotency_key") != idempotency_key:
                continue
            if (
                event.get("candidate_set_id") != candidate_set_id
                or event.get("candidate_set_sha256") != candidate_set_sha256
                or event.get("evidence_bundle_sha256") != evidence_sha256
                or event.get("actor_id") != actor_id
            ):
                raise ValueError("user acceptance idempotency conflict")
            receipt_path = receipts_root / f"{event['event_hash']}.yml"
            receipt = safe_read_yaml(receipt_path, default=None)
            if not isinstance(receipt, dict):
                raise ValueError("user acceptance receipt is missing")
            return {
                **receipt,
                "receipt_path": receipt_path.relative_to(root).as_posix(),
            }
        event = {
            "schema_version": "narrative-user-acceptance-event/v1",
            "sequence": len(events) + 1,
            "previous_event_hash": (
                events[-1]["event_hash"] if events else None
            ),
            "action": "accept_candidate_set",
            "actor_type": "user",
            "actor_id": actor_id,
            "authenticated_local_principal": {
                "login": getpass.getuser(),
                "uid": os.getuid(),
            },
            "idempotency_key": idempotency_key,
            "approved_at": approved_at,
            "candidate_set_id": candidate_set_id,
            "candidate_set_sha256": candidate_set_sha256,
            "evidence_bundle_sha256": evidence_sha256,
            "signature_authority": signature_authority,
        }
        event["event_hash"] = _event_hash(event)
        _append_event(ledger_path, event)
        receipt = {
            "schema_version": "narrative-user-acceptance-ledger-receipt/v1",
            "status": "accepted",
            **{
                key: event[key]
                for key in (
                    "action",
                    "actor_type",
                    "actor_id",
                    "authenticated_local_principal",
                    "idempotency_key",
                    "approved_at",
                    "candidate_set_id",
                    "candidate_set_sha256",
                    "evidence_bundle_sha256",
                    "sequence",
                    "previous_event_hash",
                    "event_hash",
                    "signature_authority",
                )
            },
            "ledger_path": ledger_path.relative_to(root).as_posix(),
        }
        receipts_root.mkdir(parents=True, exist_ok=True)
        receipt_path = receipts_root / f"{event['event_hash']}.yml"
        atomic_write_yaml(receipt_path, receipt)
        return {
            **receipt,
            "receipt_path": receipt_path.relative_to(root).as_posix(),
        }


def validate_candidate_acceptance(
    project_root: Path,
    receipt_path: Path,
    *,
    candidate_set_id: str,
    candidate_set_sha256: str,
    evidence_bundle_sha256: str,
) -> dict[str, Any]:
    """Verify that a receipt is backed by the exact hash-chained user event."""

    root = Path(project_root).resolve(strict=True)
    raw_receipt_path = Path(receipt_path)
    if raw_receipt_path.is_symlink():
        raise ValueError("user acceptance receipt may not be a symlink")
    resolved_receipt = raw_receipt_path.resolve(strict=True)
    resolved_receipt.relative_to(root)
    receipt = safe_read_yaml(resolved_receipt, default=None)
    if not isinstance(receipt, dict):
        raise ValueError("user acceptance receipt is invalid")
    if (
        receipt.get("schema_version")
        != "narrative-user-acceptance-ledger-receipt/v1"
        or receipt.get("status") != "accepted"
        or receipt.get("action") != "accept_candidate_set"
        or receipt.get("actor_type") != "user"
        or receipt.get("candidate_set_id") != candidate_set_id
        or receipt.get("candidate_set_sha256") != candidate_set_sha256
        or receipt.get("evidence_bundle_sha256") != evidence_bundle_sha256
        or not _SAFE_ID.fullmatch(str(receipt.get("actor_id") or ""))
        or not _SAFE_ID.fullmatch(str(receipt.get("idempotency_key") or ""))
        or not isinstance(receipt.get("authenticated_local_principal"), Mapping)
        or not isinstance(receipt.get("signature_authority"), Mapping)
    ):
        raise ValueError("user acceptance receipt contract is invalid")
    _parse_approved_at(str(receipt.get("approved_at") or ""))
    signed_payload = candidate_acceptance_payload(
        actor_id=str(receipt.get("actor_id") or ""),
        idempotency_key=str(receipt.get("idempotency_key") or ""),
        approved_at=str(receipt.get("approved_at") or ""),
        candidate_set_id=candidate_set_id,
        candidate_set_sha256=candidate_set_sha256,
        evidence_bundle_sha256=evidence_bundle_sha256,
    )
    signature_authority = receipt.get("signature_authority") or {}
    observed_authority = _verify_external_signature(
        root,
        payload=signed_payload,
        signature_path=Path(
            str(signature_authority.get("signature_path") or "")
        ),
        public_key_path=_pinned_public_key(root),
    )
    if observed_authority != signature_authority:
        raise ValueError("user acceptance signature authority changed")
    ledger_value = str(receipt.get("ledger_path") or "")
    raw_ledger_path = root / ledger_value
    if raw_ledger_path.is_symlink():
        raise ValueError("user acceptance ledger may not be a symlink")
    ledger_path = raw_ledger_path.resolve(strict=True)
    ledger_path.relative_to(root)
    events = _load_events(ledger_path)
    sequence = receipt.get("sequence")
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 1
        or sequence > len(events)
    ):
        raise ValueError("user acceptance ledger sequence is invalid")
    event = events[sequence - 1]
    for key in (
        "action",
        "actor_type",
        "actor_id",
        "authenticated_local_principal",
        "idempotency_key",
        "approved_at",
        "candidate_set_id",
        "candidate_set_sha256",
        "evidence_bundle_sha256",
        "sequence",
        "previous_event_hash",
        "event_hash",
        "signature_authority",
    ):
        if receipt.get(key) != event.get(key):
            raise ValueError("user acceptance receipt is not ledger-bound")
    return receipt
