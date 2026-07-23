"""Load only hash-bound revision selections accepted by the background controller."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

import yaml


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _has_symlink_component(root: Path, path: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def load_selected_revision_records(
    request: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    """Verify the closure receipt and return its exact per-chapter bindings."""
    rewrite = (request.get("prior_results") or {}).get("rewrite_batch") or {}
    if not rewrite:
        return {}
    if not isinstance(rewrite, Mapping) or rewrite.get("status") != "pass":
        raise ValueError("revision_selection_invalid")
    root = Path(str(request.get("agentlab_root") or "")).resolve(strict=True)
    from agent_runtime.narrative.production.live_writer_preflight import (
        _read_root_relative_bytes,
    )
    project = str(request.get("project") or "")
    job_id = str(request.get("job_id") or "")
    if not _ID_RE.fullmatch(project) or not _ID_RE.fullmatch(job_id):
        raise ValueError("revision_selection_identity_invalid")
    raw_path = str(rewrite.get("revision_closure_receipt") or "")
    expected_hash = str(rewrite.get("revision_closure_receipt_sha256") or "")
    if not _SHA_RE.fullmatch(expected_hash):
        raise ValueError("revision_selection_receipt_hash_missing")
    path = Path(raw_path)
    path = path if path.is_absolute() else root / path
    expected_root = root / "projects" / project / "background_jobs" / job_id / "attempts"
    try:
        relative = path.absolute().relative_to(expected_root.absolute())
    except ValueError as exc:
        raise ValueError("revision_selection_receipt_path_invalid") from exc
    if len(relative.parts) != 2 or relative.parts[-1] != "revision_closure_receipt.yml":
        raise ValueError("revision_selection_receipt_path_invalid")
    if _has_symlink_component(root, path) or not path.is_file():
        raise ValueError("revision_selection_receipt_unsafe")
    raw = _read_root_relative_bytes(root, path)
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("revision_selection_receipt_hash_mismatch")
    try:
        receipt = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError("revision_selection_receipt_invalid") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("status") != "pass"
        or receipt.get("candidate_only") is not True
        or receipt.get("production_modified") is not False
        or receipt.get("project") != project
        or receipt.get("job_id") != job_id
        or receipt.get("selected_revisions") != rewrite.get("selected_revisions")
        or receipt.get("changed_chapters") != rewrite.get("changed_chapters")
    ):
        raise ValueError("revision_selection_receipt_mismatch")

    state_path = root / "projects" / project / "background_jobs" / job_id / "job_state.yml"
    if state_path.is_file():
        if _has_symlink_component(root, state_path):
            raise ValueError("revision_selection_state_unsafe")
        try:
            state = yaml.safe_load(
                _read_root_relative_bytes(root, state_path).decode("utf-8")
            ) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("revision_selection_state_invalid") from exc
        persisted = (state.get("last_action_results") or {}).get("rewrite_batch")
        if persisted != dict(rewrite):
            raise ValueError("revision_selection_not_authoritative_state")

    selected = receipt.get("selected_revisions")
    if (
        not isinstance(selected, Mapping)
        or not selected
        or receipt.get("selected_revision_count") != len(selected)
    ):
        raise ValueError("revision_selection_invalid")
    records: dict[int, dict[str, Any]] = {}
    required_hashes = (
        "draft_sha256",
        "proposal_sha256",
        "contract_sha256",
        "revision_request_sha256",
        "writer_output_contract_sha256",
        "writer_session_receipt_sha256",
        "triggering_audit_sha256",
    )
    for raw_chapter, raw_record in selected.items():
        if not isinstance(raw_record, Mapping):
            raise ValueError("revision_selection_invalid")
        try:
            chapter = int(raw_chapter)
        except (TypeError, ValueError) as exc:
            raise ValueError("revision_selection_invalid") from exc
        record = dict(raw_record)
        if chapter < 1 or record.get("chapter") != chapter:
            raise ValueError("revision_selection_invalid")
        if any(not _SHA_RE.fullmatch(str(record.get(key) or "")) for key in required_hashes):
            raise ValueError("revision_selection_hash_invalid")
        for key in (
            "job_id",
            "candidate_set_id",
            "revision_attempt_id",
            "task_id",
            "source_task_id",
        ):
            if not _ID_RE.fullmatch(str(record.get(key) or "")):
                raise ValueError("revision_selection_identity_invalid")
        if record.get("job_id") != job_id:
            raise ValueError("revision_selection_job_mismatch")
        records[chapter] = record
    return records
