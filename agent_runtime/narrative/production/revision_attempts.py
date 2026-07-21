"""Append-only attempt reservations and fencing for narrative revisions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
from typing import Any

import yaml


MAX_AUTOMATIC_REWRITES = 2
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class RevisionAttemptReservation:
    automatic_rewrite_count: int
    automatic_rewrite_number: int
    fencing_token: str
    receipt_path: Path
    receipt_sha256: str

    def reference(self, root: Path) -> dict[str, str]:
        return {
            "path": self.receipt_path.relative_to(root).as_posix(),
            "sha256": self.receipt_sha256,
        }


class RevisionAttemptLockError(RuntimeError):
    """The authoritative revision ledger could not be locked safely."""


def revision_attempt_count(
    *,
    root: Path,
    project: str,
    source_run_id: str,
    candidate_set_id: str,
) -> int:
    """Return the authoritative per-source count under the revision ledger lock."""
    for value in (project, source_run_id, candidate_set_id):
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("live_revision_attempt_count_identity_invalid")
    attempt_dir = _safe_attempt_dir(
        root,
        project=project,
        source_run_id=source_run_id,
    )
    stat = attempt_dir.stat(follow_symlinks=False)
    identity = (stat.st_dev, stat.st_ino)
    from agent_runtime.narrative.production.live_writer_preflight import (
        _locked_run_slot,
        _read_slot_file,
    )

    receipts: list[dict[str, Any]] = []
    with _locked_run_slot(attempt_dir, identity) as slot:
        for number in range(1, MAX_AUTOMATIC_REWRITES + 1):
            content = _read_slot_file(slot, f"attempt-{number:02d}.yml")
            if content is None:
                continue
            receipt = _mapping(content, "live_revision_attempt_lineage_corrupt")
            if not _valid_receipt_shape(receipt, number=number):
                raise ValueError("live_revision_attempt_lineage_corrupt")
            receipts.append(receipt)
    if [int(item["automatic_rewrite_number"]) for item in receipts] != list(
        range(1, len(receipts) + 1)
    ):
        raise ValueError("live_revision_attempt_lineage_corrupt")
    if any(item.get("candidate_set_id") != candidate_set_id for item in receipts):
        raise ValueError("live_revision_candidate_set_mismatch")
    return len(receipts)


@contextmanager
def hold_revision_attempt_lock(
    *,
    root: Path,
    project: str,
    source_run_id: str,
):
    """Serialize final delivery against reservation/fence advancement."""
    if not _IDENTIFIER_RE.fullmatch(project) or not _IDENTIFIER_RE.fullmatch(
        source_run_id
    ):
        raise RevisionAttemptLockError("live_writer_revision_attempt_lock_invalid")
    directory = _attempt_dir(
        root,
        project=project,
        source_run_id=source_run_id,
    )
    from agent_runtime.narrative.production.live_writer_preflight import (
        _has_symlink_component,
        _locked_run_slot,
    )

    try:
        if _has_symlink_component(root, directory) or not directory.is_dir():
            raise RevisionAttemptLockError(
                "live_writer_revision_attempt_lock_invalid"
            )
        resolved = directory.resolve(strict=True)
        stat = resolved.stat(follow_symlinks=False)
        identity = (stat.st_dev, stat.st_ino)
        with _locked_run_slot(resolved, identity):
            yield
            if _has_symlink_component(root, directory):
                raise RevisionAttemptLockError(
                    "live_writer_revision_attempt_lock_invalid"
                )
            current = directory.stat(follow_symlinks=False)
            if (
                (current.st_dev, current.st_ino) != identity
                or directory.resolve(strict=True) != resolved
            ):
                raise RevisionAttemptLockError(
                    "live_writer_revision_attempt_lock_invalid"
                )
    except RevisionAttemptLockError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise RevisionAttemptLockError(
            "live_writer_revision_attempt_lock_invalid"
        ) from exc


def reserve_revision_attempt(
    *,
    root: Path,
    project: str,
    candidate_set_id: str,
    source_job_id: str,
    source_run_id: str,
    triggered_by_audit_id: str,
    task_id: str,
    attempt_id: str,
    lease_token: str,
    lease_expires_at: str,
    preflight_spec_sha256: str,
    claimed_rewrite_count: Any,
    source_candidate_sha256: str,
    triggering_audit_sha256: str,
    revision_contract_sha256: str,
) -> RevisionAttemptReservation:
    """Reserve one of two immutable attempt slots under an exclusive lock."""
    values = {
        "project": project,
        "candidate_set_id": candidate_set_id,
        "source_job_id": source_job_id,
        "source_run_id": source_run_id,
        "triggered_by_audit_id": triggered_by_audit_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "lease_token": lease_token,
    }
    for key, value in values.items():
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"live_revision_{key}_invalid")
    attempt_dir = _safe_attempt_dir(
        root,
        project=project,
        source_run_id=source_run_id,
    )
    stat = attempt_dir.stat(follow_symlinks=False)
    identity = (stat.st_dev, stat.st_ino)
    from agent_runtime.narrative.production.live_writer_preflight import (
        _locked_run_slot,
        _publish_text_exclusive,
        _read_slot_file,
    )

    with _locked_run_slot(attempt_dir, identity) as slot:
        receipt_entries: list[tuple[int, str, dict[str, Any]]] = []
        for number in range(1, MAX_AUTOMATIC_REWRITES + 1):
            name = f"attempt-{number:02d}.yml"
            content = _read_slot_file(slot, name)
            if content is None:
                continue
            receipt = _mapping(content, "live_revision_attempt_lineage_corrupt")
            if not _valid_receipt_shape(receipt, number=number):
                raise ValueError("live_revision_attempt_lineage_corrupt")
            receipt_entries.append((number, content, receipt))
        receipts = [entry[2] for entry in receipt_entries]
        if [int(item["automatic_rewrite_number"]) for item in receipts] != list(
            range(1, len(receipts) + 1)
        ):
            raise ValueError("live_revision_attempt_lineage_corrupt")
        if any(
            receipt.get("candidate_set_id") != candidate_set_id
            for receipt in receipts
        ):
            raise ValueError("live_revision_candidate_set_mismatch")
        for number, content, receipt in receipt_entries:
            if (
                receipt.get("task_id") == task_id
                and receipt.get("attempt_id") == attempt_id
                and receipt.get("preflight_spec_sha256") == preflight_spec_sha256
            ):
                if claimed_rewrite_count != number - 1:
                    raise ValueError("live_revision_automatic_rewrite_count_mismatch")
                path = attempt_dir / f"attempt-{number:02d}.yml"
                if number == len(receipts):
                    _write_fence_head(
                        attempt_dir=attempt_dir,
                        slot=slot,
                        number=number,
                        receipt=receipt,
                        receipt_content=content,
                    )
                return RevisionAttemptReservation(
                    automatic_rewrite_count=number - 1,
                    automatic_rewrite_number=number,
                    fencing_token=str(receipt["fencing_token"]),
                    receipt_path=path,
                    receipt_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
        if len(receipts) >= MAX_AUTOMATIC_REWRITES:
            _persist_rewrite_exhaustion(
                attempt_dir=attempt_dir,
                slot=slot,
                latest_receipt=receipts[-1],
            )
            raise ValueError("live_revision_automatic_rewrite_limit_reached")
        authoritative_count = len(receipts)
        if isinstance(claimed_rewrite_count, bool) or claimed_rewrite_count != authoritative_count:
            raise ValueError("live_revision_automatic_rewrite_count_mismatch")
        number = authoritative_count + 1
        fencing_token = "fence-" + hashlib.sha256(
            (
                f"{project}:{candidate_set_id}:{source_run_id}:"
                f"{number}:{preflight_spec_sha256}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        receipt = {
            "schema_version": 1,
            "status": "reserved",
            "candidate_only": True,
            "production_modified": False,
            **values,
            "lease_expires_at": lease_expires_at,
            "automatic_rewrite_count": authoritative_count,
            "automatic_rewrite_number": number,
            "fencing_token": fencing_token,
            "preflight_spec_sha256": preflight_spec_sha256,
            "source_candidate_sha256": source_candidate_sha256,
            "triggering_audit_sha256": triggering_audit_sha256,
            "revision_contract_sha256": revision_contract_sha256,
        }
        content = yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True)
        path = attempt_dir / f"attempt-{number:02d}.yml"
        _publish_text_exclusive(
            path,
            content,
            conflict_error="live_revision_attempt_slot_conflict",
            expected_parent_identity=identity,
            slot=slot,
        )
        _write_fence_head(
            attempt_dir=attempt_dir,
            slot=slot,
            number=number,
            receipt=receipt,
            receipt_content=content,
        )
        return RevisionAttemptReservation(
            automatic_rewrite_count=authoritative_count,
            automatic_rewrite_number=number,
            fencing_token=fencing_token,
            receipt_path=path,
            receipt_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )


def _write_fence_head(
    *,
    attempt_dir: Path,
    slot: Any,
    number: int,
    receipt: dict[str, Any],
    receipt_content: str,
) -> None:
    """Atomically advance the required monotonic fence head under the slot lock."""
    head = {
        "schema_version": 1,
        "status": "active",
        "candidate_only": True,
        "production_modified": False,
        "project": receipt.get("project"),
        "candidate_set_id": receipt.get("candidate_set_id"),
        "source_run_id": receipt.get("source_run_id"),
        "issued_attempt_count": number,
        "latest_attempt_receipt": f"attempt-{number:02d}.yml",
        "latest_attempt_receipt_sha256": hashlib.sha256(
            receipt_content.encode("utf-8")
        ).hexdigest(),
        "latest_fencing_token": receipt.get("fencing_token"),
    }
    content = yaml.safe_dump(head, sort_keys=False, allow_unicode=True)
    name = "fence-head.yml"
    from agent_runtime.narrative.production.live_writer_preflight import (
        _read_slot_file,
    )

    current_content = _read_slot_file(slot, name)
    if current_content is not None:
        current = _mapping(
            current_content,
            "live_revision_attempt_lineage_corrupt",
        )
        try:
            current_number = int(current.get("issued_attempt_count"))
        except (TypeError, ValueError) as exc:
            raise ValueError("live_revision_attempt_lineage_corrupt") from exc
        if (
            current.get("schema_version") != 1
            or current.get("status") != "active"
            or current.get("candidate_only") is not True
            or current.get("production_modified") is not False
            or current.get("project") != receipt.get("project")
            or current.get("candidate_set_id") != receipt.get("candidate_set_id")
            or current.get("source_run_id") != receipt.get("source_run_id")
            or current_number not in range(1, MAX_AUTOMATIC_REWRITES + 1)
        ):
            raise ValueError("live_revision_attempt_lineage_corrupt")
        if current_number > number:
            return
        if current_number == number:
            if current != head:
                raise ValueError("live_revision_attempt_lineage_corrupt")
            return
    temp_name = f".{name}.{secrets.token_hex(12)}.tmp"
    fd = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=slot.dir_fd,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temp_name,
            name,
            src_dir_fd=slot.dir_fd,
            dst_dir_fd=slot.dir_fd,
        )
        os.fsync(slot.dir_fd)
    finally:
        try:
            os.unlink(temp_name, dir_fd=slot.dir_fd)
        except FileNotFoundError:
            pass


def _persist_rewrite_exhaustion(
    *,
    attempt_dir: Path,
    slot: Any,
    latest_receipt: dict[str, Any],
) -> None:
    """Persist the deterministic terminal state without allocating attempt three."""
    from agent_runtime.narrative.production.live_writer_preflight import (
        _publish_text_exclusive,
    )

    decision = {
        "schema_version": 1,
        "status": "decision_required",
        "reason": "insufficient_revision_uplift",
        "automatic_rewrite_exhausted": True,
        "candidate_only": True,
        "production_modified": False,
        "project": latest_receipt.get("project"),
        "candidate_set_id": latest_receipt.get("candidate_set_id"),
        "source_job_id": latest_receipt.get("source_job_id"),
        "source_run_id": latest_receipt.get("source_run_id"),
        "triggered_by_audit_id": latest_receipt.get("triggered_by_audit_id"),
        "automatic_rewrite_count": MAX_AUTOMATIC_REWRITES,
        "latest_fencing_token": latest_receipt.get("fencing_token"),
    }
    _publish_text_exclusive(
        attempt_dir / "decision_required.yml",
        yaml.safe_dump(decision, sort_keys=False, allow_unicode=True),
        conflict_error="live_revision_decision_required_conflict",
        slot=slot,
    )


def validate_revision_attempt_receipt(
    *,
    root: Path,
    project: str,
    request: dict[str, Any],
    receipt_path: Path | None,
) -> list[str]:
    """Validate the bound receipt and require its fencing token to be current."""
    if receipt_path is None:
        return ["live_writer_revision_attempt_receipt_missing"]
    try:
        receipt = _mapping(
            receipt_path.read_text(encoding="utf-8"),
            "live_writer_revision_attempt_receipt_invalid",
        )
    except OSError:
        return ["live_writer_revision_attempt_receipt_invalid"]
    try:
        number = int(receipt.get("automatic_rewrite_number"))
    except (TypeError, ValueError):
        return ["live_writer_revision_attempt_receipt_invalid"]
    candidate_set_id = str(request.get("candidate_set_id") or "")
    source_run_id = str(request.get("source_run_id") or "")
    expected_dir = _attempt_dir(
        root,
        project=project,
        source_run_id=source_run_id,
    )
    if receipt_path != (expected_dir / f"attempt-{number:02d}.yml").resolve():
        return ["live_writer_revision_attempt_receipt_path_mismatch"]
    expected = {
        "schema_version": 1,
        "status": "reserved",
        "candidate_only": True,
        "production_modified": False,
        "project": project,
        "candidate_set_id": candidate_set_id,
        "source_job_id": request.get("source_job_id"),
        "source_run_id": source_run_id,
        "triggered_by_audit_id": request.get("triggered_by_audit_id"),
        "task_id": request.get("task_id"),
        "attempt_id": request.get("attempt_id"),
        "lease_token": request.get("lease_token"),
        "lease_expires_at": request.get("lease_expires_at"),
        "automatic_rewrite_count": request.get("automatic_rewrite_count"),
        "automatic_rewrite_number": request.get("automatic_rewrite_number"),
        "fencing_token": request.get("fencing_token"),
        "source_candidate_sha256": _ref_hash(request.get("source_candidate")),
        "triggering_audit_sha256": _ref_hash(request.get("triggering_audit")),
        "revision_contract_sha256": _ref_hash(request.get("revision_contract")),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        return ["live_writer_revision_attempt_receipt_mismatch"]
    try:
        from agent_runtime.narrative.production.live_writer_preflight import (
            _read_root_relative_bytes,
        )

        head_raw = _read_root_relative_bytes(root, expected_dir / "fence-head.yml")
        head = _mapping(
            head_raw.decode("utf-8"),
            "live_writer_revision_fence_head_invalid",
        )
        issued_count = int(head.get("issued_attempt_count"))
    except (OSError, UnicodeDecodeError, TypeError, ValueError):
        return ["live_writer_revision_fence_head_invalid"]
    if (
        head.get("schema_version") != 1
        or head.get("status") != "active"
        or head.get("candidate_only") is not True
        or head.get("production_modified") is not False
        or head.get("project") != project
        or head.get("candidate_set_id") != candidate_set_id
        or head.get("source_run_id") != source_run_id
        or issued_count not in range(1, MAX_AUTOMATIC_REWRITES + 1)
        or head.get("latest_attempt_receipt") != f"attempt-{issued_count:02d}.yml"
    ):
        return ["live_writer_revision_fence_head_invalid"]
    if number != issued_count or request.get("fencing_token") != head.get(
        "latest_fencing_token"
    ):
        return ["live_writer_revision_fencing_token_stale"]
    for observed_number in range(1, issued_count + 1):
        try:
            raw = _read_root_relative_bytes(
                root,
                expected_dir / f"attempt-{observed_number:02d}.yml",
            )
            observed = _mapping(
                raw.decode("utf-8"),
                "live_writer_revision_attempt_lineage_corrupt",
            )
        except (OSError, UnicodeDecodeError, ValueError):
            return ["live_writer_revision_attempt_lineage_corrupt"]
        if not _valid_receipt_shape(observed, number=observed_number):
            return ["live_writer_revision_attempt_lineage_corrupt"]
        if observed_number == issued_count and (
            hashlib.sha256(raw).hexdigest()
            != head.get("latest_attempt_receipt_sha256")
        ):
            return ["live_writer_revision_fence_head_invalid"]
    for future_number in range(issued_count + 1, MAX_AUTOMATIC_REWRITES + 1):
        if (expected_dir / f"attempt-{future_number:02d}.yml").exists():
            return ["live_writer_revision_fencing_token_stale"]
    return []


def _safe_attempt_dir(
    root: Path,
    *,
    project: str,
    source_run_id: str,
) -> Path:
    from agent_runtime.narrative.production.live_writer_preflight import (
        _has_symlink_component,
    )

    directory = _attempt_dir(
        root,
        project=project,
        source_run_id=source_run_id,
    )
    if _has_symlink_component(root, directory):
        raise ValueError("live_revision_attempt_dir_symlinked")
    directory.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(root, directory):
        raise ValueError("live_revision_attempt_dir_symlinked")
    resolved = directory.resolve()
    candidate_root = (root / "projects" / project / "candidates").resolve()
    try:
        resolved.relative_to(candidate_root)
    except ValueError as exc:
        raise ValueError("live_revision_attempt_dir_outside_candidates") from exc
    return resolved


def _attempt_dir(
    root: Path,
    *,
    project: str,
    source_run_id: str,
) -> Path:
    return (
        root
        / "projects"
        / project
        / "candidates"
        / "_narrative_revision_attempts"
        / source_run_id
    )


def _mapping(content: str, issue: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        raise ValueError(issue) from exc
    if not isinstance(value, dict):
        raise ValueError(issue)
    return value


def _valid_receipt_shape(receipt: dict[str, Any], *, number: int) -> bool:
    return bool(
        receipt.get("schema_version") == 1
        and receipt.get("status") == "reserved"
        and receipt.get("candidate_only") is True
        and receipt.get("production_modified") is False
        and receipt.get("automatic_rewrite_number") == number
        and receipt.get("automatic_rewrite_count") == number - 1
        and _IDENTIFIER_RE.fullmatch(str(receipt.get("fencing_token") or ""))
    )


def _ref_hash(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("sha256") or "")
