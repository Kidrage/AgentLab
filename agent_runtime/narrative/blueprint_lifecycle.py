"""Generic validation and publication lifecycle for project narrative blueprints."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator
import fcntl
import hashlib
import os
import re
import shutil
import tempfile

import yaml

from agent_runtime.artifact_digest import artifact_sha256
from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.task_runtime_v2 import TaskRuntime


_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_ALLOWED_AUTHORITY_STATUSES = frozenset(
    {"registered_pending_generic_validation", "validated_sealed"}
)
_REQUIRED_SUPPORTING_DOCUMENTS = {
    "project_agent_team": (
        "production/agent_team.yml",
        "project-agent-team/v1",
    ),
    "narrative_modification_contract": (
        "production/narrative_modification_contract.yml",
        "narrative-modification-contract/v1",
    ),
    "project_fact_snapshot": (
        "project_brain/project_fact_snapshot.yml",
        None,
    ),
}
_BLUEPRINT_WORKFLOW_DEPENDENCIES = {
    "brain-plan": [],
    "world-architect": ["brain-plan"],
    "character-keeper": ["brain-plan"],
    "timeline-keeper": ["brain-plan"],
    "plot-mystery-keeper": ["brain-plan"],
    "artifact-producer": [
        "world-architect",
        "character-keeper",
        "timeline-keeper",
        "plot-mystery-keeper",
    ],
    "reviewer": ["artifact-producer"],
    "verifier": ["reviewer"],
}
_BLUEPRINT_REVIEW_WORK_ITEMS = frozenset(
    {
        "world-architect",
        "character-keeper",
        "timeline-keeper",
        "plot-mystery-keeper",
        "reviewer",
        "verifier",
    }
)


def _has_symlink_component(path: Path, root: Path) -> bool:
    lexical_root = root.absolute()
    try:
        relative = path.absolute().relative_to(lexical_root)
    except ValueError:
        return True
    cursor = lexical_root
    if cursor.is_symlink():
        return True
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _validated_id(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"{field} must match {_SAFE_ID.pattern}")
    return normalized


def _load_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


@contextmanager
def _project_lock(project_root: Path) -> Iterator[None]:
    lock_path = project_root / ".agentlab" / "narrative-blueprint.lock"
    if (
        _has_symlink_component(lock_path.parent, project_root)
        or lock_path.is_symlink()
    ):
        raise ValueError("project narrative lock path contains a symlink")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _restore_bytes(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    atomic_write_text(path, content.decode("utf-8"), encoding="utf-8")


def _safe_relative_path(
    raw_path: object,
    *,
    allowed_roots: tuple[str, ...],
) -> Path:
    pure = PurePosixPath(str(raw_path or ""))
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.parts[0] not in allowed_roots
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(
            "path must stay under " + " or ".join(f"{root}/" for root in allowed_roots)
        )
    return Path(*pure.parts)


def _copy_artifact(
    source: Path,
    destination: Path,
    *,
    destination_root: Path | None = None,
) -> None:
    if destination_root is not None and _has_symlink_component(
        destination, destination_root
    ):
        raise ValueError(f"artifact destination contains a symlink: {destination}")
    if destination.exists():
        if destination.is_symlink():
            raise ValueError(f"artifact destination is a symlink: {destination}")
        if artifact_sha256(destination) != artifact_sha256(source):
            raise ValueError(f"immutable archive collision at {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination_root is not None and _has_symlink_component(
        destination, destination_root
    ):
        raise ValueError(f"artifact destination contains a symlink: {destination}")
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _remove_artifact(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink():
        raise ValueError(f"refusing to remove symlink artifact: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _receipt_id(project: str, idempotency_key: str) -> str:
    return hashlib.sha256(
        f"{project}\0{idempotency_key}".encode("utf-8")
    ).hexdigest()


def _create_immutable_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        value,
        sort_keys=False,
        allow_unicode=True,
    ).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            linked = True
        except FileExistsError as exc:
            raise ValueError("immutable publication receipt already exists") from exc
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            if linked:
                path.unlink(missing_ok=True)
            raise
    finally:
        temporary.unlink(missing_ok=True)


def _require_runtime_publication_evidence(
    root: Path,
    *,
    project: str,
    task_id: str,
    manifest: dict[str, Any],
    manifest_path: Path,
    approval: dict[str, Any],
    acceptance_receipt_path: Path,
) -> dict[str, Any]:
    """Bind publication claims to executed Runtime v2 Attempts and evidence."""

    runtime = TaskRuntime(root, project=project)
    projection = runtime.load_task(task_id)
    task_root = root / "projects" / project / "runtime" / "tasks" / task_id
    packet_records = [
        record
        for record in projection.get("trace_records", {}).values()
        if isinstance(record, dict)
        and record.get("record_type") == "narrative_task_packet"
    ]
    if len(packet_records) != 1:
        raise ValueError("blueprint publication requires one immutable task packet")
    packet_record = packet_records[0]
    packet_path = task_root / str(packet_record.get("path") or "")
    if (
        _has_symlink_component(packet_path, task_root)
        or not packet_path.is_file()
        or artifact_sha256(packet_path) != packet_record.get("sha256")
    ):
        raise ValueError("immutable narrative task packet bytes are missing or stale")
    packet = _load_mapping(packet_path, label="immutable narrative task packet")
    if packet != packet_record.get("record_data"):
        raise ValueError("immutable narrative task packet does not match its ledger")
    if (
        packet.get("schema_version") != "narrative-task-packet/v1"
        or packet.get("status") != "compiled"
        or packet.get("runtime_standard") != "task-runtime-v2"
        or packet.get("project") != project
        or packet.get("task_id") != task_id
        or packet.get("change_kind")
        not in {"blueprint_change", "global_character_change"}
    ):
        raise ValueError("blueprint publication requires its compiled Runtime v2 packet")
    request = packet.get("request")
    expected_current = manifest.get("expected_current")
    bindings = packet.get("truth_bindings")
    if (
        not isinstance(request, dict)
        or request.get("idempotency_key") != manifest.get("idempotency_key")
        or not isinstance(expected_current, dict)
        or not isinstance(bindings, dict)
        or bindings.get("blueprint_authority_sha256")
        != expected_current.get("authority_sha256")
        or bindings.get("project_artifact_index_sha256")
        != expected_current.get("artifact_index_sha256")
    ):
        raise ValueError("blueprint publication task truth binding is stale or mismatched")
    try:
        ledger_request = (
            yaml.safe_load(str(projection.get("task", {}).get("user_goal") or ""))
            or {}
        )
    except yaml.YAMLError as exc:
        raise ValueError("Runtime v2 task user goal is not valid YAML") from exc
    if ledger_request != request:
        raise ValueError("narrative task packet request does not match its ledger")
    instructions = projection.get("task", {}).get("instructions") or []
    if not instructions:
        raise ValueError("narrative publication task has no user instruction")
    last_instruction_at = max(
        str(item.get("recorded_at") or "")
        for item in instructions
        if isinstance(item, dict)
    )

    required_roles = packet.get("required_roles")
    if (
        not isinstance(required_roles, list)
        or set(required_roles) != set(_BLUEPRINT_WORKFLOW_DEPENDENCIES)
        or any(not isinstance(item, str) or not item for item in required_roles)
    ):
        raise ValueError("narrative task packet required_roles is incomplete")
    work_items = projection.get("work_items")
    attempts = projection.get("attempts")
    if not isinstance(work_items, dict) or not isinstance(attempts, dict):
        raise ValueError("Runtime v2 publication projection is invalid")
    attempts_by_work_item: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts.values():
        if (
            not isinstance(attempt, dict)
            or attempt.get("status") != "succeeded"
            or str(attempt.get("created_at") or "") < last_instruction_at
        ):
            continue
        work_item_id = str(attempt.get("work_item_id") or "")
        attempts_by_work_item.setdefault(work_item_id, []).append(attempt)
    for work_item_id in required_roles:
        work_item = work_items.get(work_item_id)
        if (
            not isinstance(work_item, dict)
            or work_item.get("depends_on")
            != _BLUEPRINT_WORKFLOW_DEPENDENCIES[work_item_id]
            or work_item.get("status") != "accepted"
            or not attempts_by_work_item.get(work_item_id)
        ):
            raise ValueError(
                f"Runtime v2 work item lacks accepted execution evidence: {work_item_id}"
            )
        for attempt in attempts_by_work_item[work_item_id]:
            runtime.verify_attempt_execution_receipt(
                task_id,
                str(attempt.get("attempt_id") or ""),
            )
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    for record in projection.get("trace_records", {}).values():
        if isinstance(record, dict):
            records_by_type.setdefault(str(record.get("record_type") or ""), []).append(
                record
            )
    for required_type in ("brain_scope_decision", "execution_plan"):
        if len(records_by_type.get(required_type, [])) != 1:
            raise ValueError(
                f"Runtime v2 publication trace is missing: {required_type}"
            )
        record = records_by_type[required_type][0]
        record_path = task_root / str(record.get("path") or "")
        if (
            _has_symlink_component(record_path, task_root)
            or not record_path.is_file()
            or artifact_sha256(record_path) != record.get("sha256")
            or str(record.get("created_at") or "") < last_instruction_at
        ):
            raise ValueError(
                "Runtime v2 publication trace bytes are stale or predate "
                f"the latest instruction: {required_type}"
            )
    scope_data = records_by_type["brain_scope_decision"][0].get("record_data") or {}
    plan_data = records_by_type["execution_plan"][0].get("record_data") or {}
    required_execution_items = set(_BLUEPRINT_WORKFLOW_DEPENDENCIES) - {
        "brain-plan"
    }
    if (
        scope_data.get("approved") is not True
        or plan_data.get("status") != "approved"
        or plan_data.get("route") != "governed_pipeline"
        or not required_execution_items.issubset(
            set(plan_data.get("work_items") or [])
        )
    ):
        raise ValueError("Runtime v2 Brain scope or execution plan is incomplete")

    required_reviews = manifest.get("required_reviews")
    reviews = approval.get("reviews")
    if (
        not isinstance(required_reviews, list)
        or set(required_reviews) != _BLUEPRINT_REVIEW_WORK_ITEMS
        or not isinstance(reviews, list)
    ):
        raise ValueError("blueprint change must require Runtime v2 verifier evidence")
    passed_reviews = [
        item
        for item in reviews
        if isinstance(item, dict) and item.get("status") == "pass"
    ]
    review_by_work_item = {
        str(item.get("work_item_id") or ""): item for item in passed_reviews
    }
    if len(review_by_work_item) != len(passed_reviews):
        raise ValueError("blueprint acceptance contains duplicate Runtime v2 reviews")
    if not set(str(item) for item in required_reviews).issubset(review_by_work_item):
        raise ValueError("blueprint acceptance lacks required Runtime v2 reviews")
    verified_attempts: dict[str, str] = {}
    for work_item_id in required_reviews:
        review = review_by_work_item[str(work_item_id)]
        attempt_id = str(review.get("attempt_id") or "")
        attempt = attempts.get(attempt_id)
        if (
            not attempt_id
            or not isinstance(attempt, dict)
            or attempt.get("status") != "succeeded"
            or attempt.get("work_item_id") != work_item_id
        ):
            raise ValueError(
                f"blueprint review is not bound to a succeeded Attempt: {work_item_id}"
            )
        runtime.verify_attempt_execution_receipt(task_id, attempt_id)
        verified_attempts[str(work_item_id)] = attempt_id

    def evidenced_artifact(
        *,
        artifact_id: str,
        path: Path,
        producer_work_item_id: str,
    ) -> str:
        digest = artifact_sha256(path)
        versions = [
            item
            for item in projection.get("artifacts", {}).values()
            if isinstance(item, dict)
            and item.get("artifact_id") == artifact_id
            and item.get("sha256") == digest
            and item.get("source_path")
            == path.relative_to(task_root).as_posix()
        ]
        if len(versions) != 1:
            raise ValueError(
                f"Runtime v2 immutable artifact evidence is missing: {artifact_id}"
            )
        version = versions[0]
        if str(version.get("created_at") or "") < last_instruction_at:
            raise ValueError(
                f"Runtime v2 artifact predates latest instruction: {artifact_id}"
            )
        attempt_id = str(version.get("producer_attempt_id") or "")
        attempt = attempts.get(attempt_id)
        if (
            not isinstance(attempt, dict)
            or attempt.get("work_item_id") != producer_work_item_id
            or (attempt.get("outcome") or {}).get("output_sha256") != digest
        ):
            raise ValueError(
                f"Runtime v2 producer output mismatch: {artifact_id}"
            )
        runtime.verify_attempt_execution_receipt(task_id, attempt_id)
        bindings_for_version = [
            item
            for item in projection.get("evidence_bindings", {}).values()
            if isinstance(item, dict)
            and item.get("version_id") == version.get("version_id")
            and (item.get("audit") or {}).get("verdict") == "pass"
        ]
        if not bindings_for_version:
            raise ValueError(
                f"Runtime v2 evidence binding is missing: {artifact_id}"
            )
        expected_index_snapshot = str(
            bindings.get("knowledge_index_snapshot_id") or ""
        )
        for binding in bindings_for_version:
            if binding.get("index_snapshot_id") != expected_index_snapshot:
                raise ValueError(
                    f"Runtime v2 evidence snapshot mismatch: {artifact_id}"
                )
        if artifact_id == "blueprint_change_set":
            if not any(
                binding.get("input_manifest_hash")
                == expected_current.get("artifact_index_sha256")
                and expected_current.get("authority_sha256")
                in (binding.get("source_hashes") or {}).values()
                for binding in bindings_for_version
            ):
                raise ValueError("blueprint change set evidence is not bound to current truth")
        elif not any(
            binding.get("input_manifest_hash") == artifact_sha256(manifest_path)
            and artifact_sha256(manifest_path)
            in (binding.get("source_hashes") or {}).values()
            for binding in bindings_for_version
        ):
            raise ValueError("blueprint acceptance evidence is not bound to its change set")
        return str(version["version_id"])

    manifest_version_id = evidenced_artifact(
        artifact_id="blueprint_change_set",
        path=manifest_path,
        producer_work_item_id="artifact-producer",
    )
    acceptance_version_id = evidenced_artifact(
        artifact_id="blueprint_acceptance_receipt",
        path=acceptance_receipt_path,
        producer_work_item_id="verifier",
    )
    verifier_attempt_id = verified_attempts["verifier"]
    if (
        projection["artifacts"][acceptance_version_id].get("producer_attempt_id")
        != verifier_attempt_id
    ):
        raise ValueError("acceptance receipt is not produced by the reviewed Verifier")
    evidence_report = runtime.verify_evidence(task_id)
    if evidence_report.get("ok") is not True:
        raise ValueError("Runtime v2 task evidence verification failed")
    return {
        "task_id": task_id,
        "packet_sha256": artifact_sha256(packet_path),
        "manifest_version_id": manifest_version_id,
        "acceptance_version_id": acceptance_version_id,
        "verified_attempts": verified_attempts,
    }


def _recover_blueprint_transactions(project_root: Path) -> None:
    transactions_root = project_root / ".agentlab" / "narrative_transactions"
    if _has_symlink_component(transactions_root, project_root):
        raise ValueError("narrative transactions root contains a symlink")
    if not transactions_root.is_dir():
        return
    for transaction in sorted(transactions_root.iterdir()):
        if not transaction.is_dir() or transaction.is_symlink():
            raise ValueError("unsafe narrative transaction directory")
        prepared_path = transaction / "prepared.yml"
        if prepared_path.is_symlink() or not prepared_path.is_file():
            remaining = {
                item.name
                for item in transaction.iterdir()
                if not (
                    item.is_file()
                    and item.name.startswith(".prepared.yml.")
                    and item.name.endswith(".tmp")
                )
            }
            if not remaining:
                shutil.rmtree(transaction)
                continue
            raise ValueError(f"incomplete narrative transaction: {transaction.name}")
        prepared = _load_mapping(prepared_path, label="narrative transaction")
        receipt_relative = _safe_relative_path(
            prepared.get("receipt_path"),
            allowed_roots=("project_brain",),
        )
        receipt_path = project_root / receipt_relative
        receipt_committed = False
        if not _has_symlink_component(receipt_path, project_root) and receipt_path.is_file():
            try:
                committed_receipt = _load_mapping(
                    receipt_path,
                    label="narrative publication receipt",
                )
            except ValueError:
                committed_receipt = {}
            receipt_committed = (
                committed_receipt.get("schema_version")
                == "narrative-blueprint-publication-receipt/v1"
                and committed_receipt.get("status") == "published"
                and committed_receipt.get("project") == prepared.get("project")
                and committed_receipt.get("task_id") == prepared.get("task_id")
                and committed_receipt.get("change_set_sha256")
                == prepared.get("change_set_sha256")
            )
        if receipt_committed:
            shutil.rmtree(transaction)
            continue
        records = prepared.get("targets")
        if not isinstance(records, list):
            raise ValueError("narrative transaction target manifest is invalid")
        index_path = project_root / "project_artifact_index.yml"
        index_backup = transaction / "backup" / "project_artifact_index.yml"
        interrupted_archive = (
            project_root / "archive" / "narrative_blueprints" / transaction.name
        )
        if (
            _has_symlink_component(index_path, project_root)
            or _has_symlink_component(index_backup, transaction)
            or _has_symlink_component(interrupted_archive, project_root)
        ):
            raise ValueError("narrative transaction recovery path contains a symlink")
        validated_records: list[tuple[dict[str, Any], Path, Path, Path]] = []
        for record in reversed(records):
            if not isinstance(record, dict):
                raise ValueError("narrative transaction target record is invalid")
            relative = _safe_relative_path(
                record.get("target_path"),
                allowed_roots=("production", "project_brain"),
            )
            target = project_root / relative
            backup = transaction / "backup" / relative
            if (
                _has_symlink_component(target, project_root)
                or _has_symlink_component(backup, transaction)
            ):
                raise ValueError(
                    "narrative transaction recovery target contains a symlink"
                )
            validated_records.append((record, relative, target, backup))
        if index_backup.is_file():
            atomic_write_text(
                index_path,
                index_backup.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        for record, relative, target, backup in validated_records:
            if backup.exists():
                if target.exists():
                    _remove_artifact(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
            elif record.get("existed") is True:
                if not target.exists():
                    raise ValueError(
                        f"narrative transaction lost current artifact: "
                        f"{relative.as_posix()}"
                    )
            elif target.exists():
                _remove_artifact(target)
        if interrupted_archive.exists():
            shutil.rmtree(interrupted_archive)
        shutil.rmtree(transaction)


def _selected_artifact(
    project_root: Path,
    raw_path: object,
    *,
    allowed_roots: tuple[str, ...] = ("production", "project_brain"),
) -> Path:
    relative = PurePosixPath(str(raw_path or ""))
    if (
        relative.is_absolute()
        or not relative.parts
        or relative.parts[0] not in allowed_roots
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(
            "artifact path must stay under "
            + " or ".join(f"{root}/" for root in allowed_roots)
        )
    path = project_root / Path(*relative.parts)
    if _has_symlink_component(path, project_root):
        raise ValueError(f"artifact path contains a symlink: {relative.as_posix()}")
    resolved = path.resolve()
    if project_root not in resolved.parents or not (
        resolved.is_file() or resolved.is_dir()
    ):
        raise ValueError(f"artifact path is missing: {relative.as_posix()}")
    return resolved


def validate_project_blueprint(
    agentlab_root: Path,
    *,
    project: str,
    require_seal_receipt: bool = True,
    allow_unregistered_supporting_documents: bool = False,
) -> dict[str, Any]:
    """Validate one project-specific blueprint and its selected current artifacts."""

    root = Path(agentlab_root).resolve()
    project = _validated_id(project, field="project")
    project_root = root / "projects" / project
    issues: list[str] = []
    if _has_symlink_component(project_root, root / "projects") or not project_root.is_dir():
        issues.append("unsafe_or_missing_project_root")
        return {
            "schema_version": "narrative-blueprint-validation/v1",
            "status": "blocked",
            "project": project,
            "profile": "project_specific",
            "sealed": False,
            "issues": issues,
        }

    authority_path = project_root / "production" / "blueprint_authority.yml"
    index_path = project_root / "project_artifact_index.yml"
    try:
        authority = _load_mapping(authority_path, label="blueprint authority")
        index = _load_mapping(index_path, label="project artifact index")
    except ValueError as exc:
        issues.append(str(exc))
        authority = {}
        index = {}

    if authority.get("schema_version") != "narrative-blueprint-authority/v1":
        issues.append("unsupported_blueprint_schema")
    if authority.get("project") != project:
        issues.append("blueprint_project_mismatch")
    if authority.get("authority_kind") != "project_specific":
        issues.append("blueprint_authority_kind_mismatch")
    if authority.get("status") not in _ALLOWED_AUTHORITY_STATUSES:
        issues.append("blueprint_status_invalid")
    rules = authority.get("authority_rules")
    if not isinstance(rules, dict):
        issues.append("authority_rules_missing")
        rules = {}
    for field in (
        "direct_production_edit_forbidden",
        "one_current_version_per_artifact_id",
        "archive_and_runtime_are_not_current_truth",
        "rag_is_derived_not_authoritative",
    ):
        if rules.get(field) is not True:
            issues.append(f"authority_rule_missing:{field}")
    production_gate = authority.get("production_gate")
    if (
        not isinstance(production_gate, dict)
        or production_gate.get("runtime_standard") != "task-runtime-v2"
    ):
        issues.append("runtime_standard_mismatch")

    story = authority.get("story_contract")
    if not isinstance(story, dict):
        issues.append("story_contract_missing")
    else:
        target = story.get("target_total_chapters")
        accepted = story.get("accepted_chapters")
        next_chapter = story.get("next_production_chapter")
        if (
            type(target) is not int
            or target < 1
            or type(accepted) is not int
            or accepted < 0
            or accepted > target
            or type(next_chapter) is not int
            or next_chapter != accepted + 1
        ):
            issues.append("story_chapter_contract_invalid")

    artifacts = index.get("artifacts")
    current_by_id: dict[str, dict[str, Any]] = {}
    if index.get("project") != project or not isinstance(artifacts, list):
        issues.append("artifact_index_invalid")
        artifacts = []
    for raw in artifacts:
        if not isinstance(raw, dict) or raw.get("status") != "current":
            continue
        artifact_id = str(raw.get("artifact_id") or "").strip()
        if not artifact_id or artifact_id in current_by_id:
            issues.append(f"duplicate_or_missing_current_artifact:{artifact_id}")
            continue
        current_by_id[artifact_id] = raw
        expected = str(raw.get("production_sha256") or "")
        try:
            artifact_path = _selected_artifact(
                project_root,
                raw.get("production_path"),
            )
            if not _SHA256.fullmatch(expected) or artifact_sha256(artifact_path) != expected:
                issues.append(f"current_artifact_hash_mismatch:{artifact_id}")
        except ValueError as exc:
            issues.append(f"current_artifact_invalid:{artifact_id}:{exc}")

    current_map = index.get("current")
    expected_current_map = {
        artifact_id: str(record.get("production_path") or "")
        for artifact_id, record in current_by_id.items()
    }
    if current_map is not None and current_map != expected_current_map:
        issues.append("artifact_index_current_mapping_mismatch")

    sources = authority.get("source_artifacts")
    if not isinstance(sources, dict) or not sources:
        issues.append("blueprint_source_artifacts_missing")
        sources = {}
    seen_source_ids: set[str] = set()
    for source_name, raw in sources.items():
        if not isinstance(raw, dict):
            issues.append(f"blueprint_source_invalid:{source_name}")
            continue
        artifact_id = str(raw.get("artifact_id") or "").strip()
        version = str(raw.get("version") or "").strip()
        expected = str(raw.get("sha256") or "")
        if not artifact_id or artifact_id in seen_source_ids or not version:
            issues.append(f"blueprint_source_identity_invalid:{source_name}")
            continue
        seen_source_ids.add(artifact_id)
        selected = current_by_id.get(artifact_id)
        if (
            selected is None
            or selected.get("production_path") != raw.get("path")
            or selected.get("production_sha256") != expected
        ):
            issues.append(f"blueprint_source_not_current:{artifact_id}")
            continue
        try:
            artifact_path = _selected_artifact(
                project_root,
                raw.get("path"),
                allowed_roots=("production",),
            )
            if not _SHA256.fullmatch(expected) or artifact_sha256(artifact_path) != expected:
                issues.append(f"blueprint_source_hash_mismatch:{artifact_id}")
        except ValueError as exc:
            issues.append(f"blueprint_source_invalid:{artifact_id}:{exc}")

    authority_record = current_by_id.get("narrative_blueprint_authority")
    if (
        authority_record is None
        or authority_record.get("production_path")
        != "production/blueprint_authority.yml"
        or authority_record.get("production_sha256")
        != artifact_sha256(authority_path)
    ):
        issues.append("blueprint_authority_not_current")

    for artifact_id, (
        relative,
        schema_version,
    ) in _REQUIRED_SUPPORTING_DOCUMENTS.items():
        record = current_by_id.get(artifact_id)
        path = project_root / relative
        if (
            record is None
            and allow_unregistered_supporting_documents
            and path.is_file()
        ):
            try:
                document = _load_mapping(path, label=artifact_id)
            except ValueError:
                issues.append(f"required_current_artifact_invalid:{artifact_id}")
                continue
            if document.get("project") != project or (
                schema_version is not None
                and document.get("schema_version") != schema_version
            ):
                issues.append(
                    f"required_current_artifact_identity_mismatch:{artifact_id}"
                )
            continue
        if (
            record is None
            or record.get("production_path") != relative
            or not path.is_file()
            or record.get("production_sha256") != artifact_sha256(path)
        ):
            issues.append(f"required_current_artifact_invalid:{artifact_id}")
            continue
        try:
            document = _load_mapping(path, label=artifact_id)
        except ValueError:
            issues.append(f"required_current_artifact_invalid:{artifact_id}")
            continue
        if document.get("project") != project or (
            schema_version is not None
            and document.get("schema_version") != schema_version
        ):
            issues.append(f"required_current_artifact_identity_mismatch:{artifact_id}")

    if (
        require_seal_receipt
        and authority.get("status") == "validated_sealed"
        and authority_path.is_file()
        and index_path.is_file()
    ):
        receipt_path = (
            project_root / "project_brain" / "blueprint_validation_receipt.yml"
        )
        try:
            receipt = _load_mapping(
                receipt_path,
                label="blueprint validation receipt",
            )
        except ValueError:
            issues.append("blueprint_validation_receipt_missing")
        else:
            if (
                receipt.get("status") != "pass"
                or receipt.get("project") != project
                or receipt.get("authority_sha256") != artifact_sha256(authority_path)
                or receipt.get("artifact_index_sha256") != artifact_sha256(index_path)
            ):
                issues.append("blueprint_validation_receipt_stale")

    unique_issues = sorted(set(issues))
    return {
        "schema_version": "narrative-blueprint-validation/v1",
        "status": "pass" if not unique_issues else "blocked",
        "project": project,
        "profile": "project_specific",
        "sealed": authority.get("status") == "validated_sealed",
        "authority_sha256": (
            artifact_sha256(authority_path) if authority_path.is_file() else None
        ),
        "artifact_index_sha256": (
            artifact_sha256(index_path) if index_path.is_file() else None
        ),
        "issues": unique_issues,
    }


def seal_project_blueprint(
    agentlab_root: Path,
    *,
    project: str,
    source_task: str,
) -> dict[str, Any]:
    """Seal a valid project-specific blueprint and bind its one current index entry."""

    root = Path(agentlab_root).resolve()
    project = _validated_id(project, field="project")
    project_root = root / "projects" / project
    if not source_task.strip() or "/" in source_task or source_task in {".", ".."}:
        raise ValueError("source_task must be one safe task id")
    if _has_symlink_component(project_root, root / "projects") or not project_root.is_dir():
        raise ValueError("project root is missing or unsafe")
    authority_path = project_root / "production" / "blueprint_authority.yml"
    index_path = project_root / "project_artifact_index.yml"
    receipt_path = project_root / "project_brain" / "blueprint_validation_receipt.yml"

    with _project_lock(project_root):
        before = validate_project_blueprint(
            root,
            project=project,
            allow_unregistered_supporting_documents=True,
        )
        if before["status"] != "pass":
            raise ValueError(
                "blueprint validation blocked: "
                + ", ".join(str(item) for item in before["issues"])
            )
        authority = _load_mapping(authority_path, label="blueprint authority")
        if authority.get("status") == "validated_sealed":
            receipt = _load_mapping(
                receipt_path,
                label="blueprint validation receipt",
            )
            if (
                receipt.get("status") != "pass"
                or receipt.get("project") != project
                or receipt.get("authority_sha256") != artifact_sha256(authority_path)
                or receipt.get("artifact_index_sha256") != artifact_sha256(index_path)
            ):
                raise ValueError("sealed blueprint receipt is missing or stale")
            return {
                "schema_version": "narrative-blueprint-seal-result/v1",
                "status": "sealed",
                "project": project,
                "authority_sha256": receipt["authority_sha256"],
                "artifact_index_sha256": receipt["artifact_index_sha256"],
                "validation_receipt": receipt_path.relative_to(root).as_posix(),
                "idempotent_replay": True,
            }

        index = _load_mapping(index_path, label="project artifact index")
        previous_authority = authority_path.read_bytes()
        previous_index = index_path.read_bytes()
        previous_receipt = receipt_path.read_bytes() if receipt_path.is_file() else None
        previous_authority_sha256 = artifact_sha256(authority_path)
        archive_path = (
            project_root
            / "archive"
            / "narrative_blueprints"
            / previous_authority_sha256
            / "blueprint_authority.yml"
        )
        if archive_path.exists():
            if archive_path.read_bytes() != previous_authority:
                raise ValueError("blueprint archive hash collision")
        else:
            atomic_write_text(
                archive_path,
                previous_authority.decode("utf-8"),
                encoding="utf-8",
            )

        next_authority = dict(authority)
        next_authority["status"] = "validated_sealed"
        production_gate = dict(next_authority.get("production_gate") or {})
        production_gate["generic_blueprint_cli_profile_status"] = "implemented"
        next_authority["production_gate"] = production_gate
        next_authority["sealed_from_sha256"] = previous_authority_sha256
        next_authority["sealed_by_task"] = source_task

        try:
            atomic_write_yaml(authority_path, next_authority, sort_keys=False)
            next_authority_sha256 = artifact_sha256(authority_path)
            raw_artifacts = index.get("artifacts")
            if not isinstance(raw_artifacts, list):
                raise ValueError("project artifact index artifacts must be a list")
            next_artifacts: list[dict[str, Any]] = []
            authority_record: dict[str, Any] | None = None
            for raw in raw_artifacts:
                if not isinstance(raw, dict):
                    raise ValueError("project artifact index entry must be a mapping")
                record = dict(raw)
                if (
                    record.get("artifact_id") == "narrative_blueprint_authority"
                    and record.get("status") == "current"
                ):
                    if authority_record is not None:
                        raise ValueError("multiple current blueprint authority records")
                    authority_record = record
                    archived = dict(record)
                    archived["status"] = "archived"
                    archived["archive_path"] = archive_path.relative_to(
                        project_root
                    ).as_posix()
                    archived["archived_sha256"] = previous_authority_sha256
                    archived["superseded_by"] = next_authority_sha256
                    next_artifacts.append(archived)
                    continue
                next_artifacts.append(record)
            if authority_record is None:
                raise ValueError("current blueprint authority record is missing")
            next_artifacts.append(
                {
                    **authority_record,
                    "status": "current",
                    "current_version": f"sealed-{next_authority_sha256[:16]}",
                    "production_sha256": next_authority_sha256,
                    "source_task": source_task,
                    "source_run_artifact": "production/blueprint_authority.yml",
                    "provenance_kind": "bootstrap_in_place_validation",
                    "supersedes": previous_authority_sha256,
                    "archived_versions": [
                        archive_path.relative_to(project_root).as_posix()
                    ],
                    "notes": "Generic project-specific blueprint validated and sealed.",
                }
            )
            registered_current_ids = {
                str(item.get("artifact_id") or "")
                for item in next_artifacts
                if item.get("status") == "current"
            }
            for artifact_id, (
                relative,
                _schema_version,
            ) in _REQUIRED_SUPPORTING_DOCUMENTS.items():
                if artifact_id in registered_current_ids:
                    continue
                supporting_path = project_root / relative
                next_artifacts.append(
                    {
                        "artifact_id": artifact_id,
                        "status": "current",
                        "current_version": (
                            f"sealed-{artifact_sha256(supporting_path)[:16]}"
                        ),
                        "production_path": relative,
                        "production_sha256": artifact_sha256(supporting_path),
                        "source_task": source_task,
                        "source_run_artifact": relative,
                        "evidence_only": False,
                        "notes": (
                            "Supporting narrative authority registered by generic "
                            "blueprint sealing."
                        ),
                    }
                )
            next_index = dict(index)
            next_index["artifacts"] = next_artifacts
            next_index["current"] = {
                str(item["artifact_id"]): str(item["production_path"])
                for item in next_artifacts
                if item.get("status") == "current"
                and str(item.get("artifact_id") or "").strip()
            }
            next_index["updated_at"] = datetime.now(timezone.utc).isoformat()
            atomic_write_yaml(index_path, next_index, sort_keys=False)
            validation = validate_project_blueprint(
                root,
                project=project,
                require_seal_receipt=False,
            )
            if validation["status"] != "pass" or validation["sealed"] is not True:
                raise ValueError(
                    "sealed blueprint validation blocked: "
                    + ", ".join(str(item) for item in validation["issues"])
                )
            receipt = {
                "schema_version": "narrative-blueprint-validation-receipt/v1",
                "status": "pass",
                "project": project,
                "profile": "project_specific",
                "source_task": source_task,
                "authority_sha256": artifact_sha256(authority_path),
                "artifact_index_sha256": artifact_sha256(index_path),
                "validation": validation,
            }
            atomic_write_yaml(receipt_path, receipt, sort_keys=False)
        except BaseException:
            _restore_bytes(authority_path, previous_authority)
            _restore_bytes(index_path, previous_index)
            _restore_bytes(receipt_path, previous_receipt)
            raise

        return {
            "schema_version": "narrative-blueprint-seal-result/v1",
            "status": "sealed",
            "project": project,
            "authority_sha256": receipt["authority_sha256"],
            "artifact_index_sha256": receipt["artifact_index_sha256"],
            "validation_receipt": receipt_path.relative_to(root).as_posix(),
            "idempotent_replay": False,
        }


def publish_blueprint_change(
    agentlab_root: Path,
    *,
    project: str,
    manifest_path: Path,
    acceptance_receipt_path: Path,
) -> dict[str, Any]:
    """Validate, archive, and transactionally publish one blueprint change set."""

    root = Path(agentlab_root).resolve()
    project = _validated_id(project, field="project")
    project_root = root / "projects" / project
    if _has_symlink_component(project_root, root / "projects") or not project_root.is_dir():
        raise ValueError("project root is missing or unsafe")

    with _project_lock(project_root):
        _recover_blueprint_transactions(project_root)
        manifest = _load_mapping(Path(manifest_path), label="blueprint change set")
        if (
            manifest.get("schema_version")
            != "narrative-blueprint-change-set/v1"
            or manifest.get("project") != project
        ):
            raise ValueError("blueprint change set schema or project mismatch")
        task_id = _validated_id(manifest.get("task_id"), field="task_id")
        idempotency_key = str(manifest.get("idempotency_key") or "").strip()
        if (
            not idempotency_key
            or any(character in idempotency_key for character in "\0\r\n")
        ):
            raise ValueError("blueprint change set identity is invalid")
        task_root = project_root / "runtime" / "tasks" / task_id
        artifacts_root = task_root / "artifacts"
        for candidate_path, label in (
            (Path(manifest_path), "blueprint change set"),
            (Path(acceptance_receipt_path), "blueprint acceptance receipt"),
        ):
            resolved = candidate_path.resolve()
            if (
                _has_symlink_component(candidate_path, project_root)
                or artifacts_root.resolve() not in resolved.parents
                or not resolved.is_file()
            ):
                raise ValueError(f"{label} must be a safe Runtime v2 task artifact")

        manifest_sha256 = artifact_sha256(Path(manifest_path))
        receipt_key = _receipt_id(project, idempotency_key)
        receipt_path = (
            project_root
            / "project_brain"
            / "blueprint_change_receipts"
            / f"{receipt_key}.yml"
        )
        if _has_symlink_component(receipt_path.parent, project_root):
            raise ValueError("blueprint publication receipt path contains a symlink")
        if receipt_path.is_symlink():
            raise ValueError("blueprint publication receipt must not be a symlink")

        approval = _load_mapping(
            Path(acceptance_receipt_path),
            label="blueprint acceptance receipt",
        )
        if (
            approval.get("schema_version") != "narrative-blueprint-acceptance/v1"
            or approval.get("status") != "accepted"
            or approval.get("project") != project
            or approval.get("task_id") != task_id
            or approval.get("change_set_sha256") != manifest_sha256
        ):
            raise ValueError("blueprint acceptance receipt is missing or stale")
        runtime_evidence = _require_runtime_publication_evidence(
            root,
            project=project,
            task_id=task_id,
            manifest=manifest,
            manifest_path=Path(manifest_path),
            approval=approval,
            acceptance_receipt_path=Path(acceptance_receipt_path),
        )

        if receipt_path.is_file():
            receipt = _load_mapping(
                receipt_path,
                label="blueprint publication receipt",
            )
            if (
                receipt.get("status") != "published"
                or receipt.get("change_set_sha256") != manifest_sha256
                or receipt.get("project") != project
                or receipt.get("idempotency_key") != idempotency_key
            ):
                raise ValueError(
                    "idempotency key already belongs to another blueprint change"
                )
            if not isinstance(receipt.get("runtime_evidence"), dict):
                raise ValueError(
                    "publication predates Runtime v2 evidence enforcement; "
                    "its current truth remains valid but the old command cannot replay"
                )
            knowledge_sync = receipt.get("knowledge_sync")
            knowledge_snapshot = receipt.get("project_knowledge_snapshot")
            current_knowledge_snapshot = _load_mapping(
                project_root
                / "project_brain"
                / "knowledge_index_snapshot.yml",
                label="project knowledge snapshot",
            )
            if (
                receipt.get("acceptance_receipt_sha256")
                != artifact_sha256(Path(acceptance_receipt_path))
                or receipt.get("runtime_evidence") != runtime_evidence
                or not isinstance(knowledge_sync, dict)
                or knowledge_sync.get("status") != "SYNCED"
                or not isinstance(knowledge_snapshot, dict)
                or knowledge_snapshot != current_knowledge_snapshot
                or knowledge_snapshot.get("build_receipt_id")
                != knowledge_sync.get("receipt_id")
            ):
                raise ValueError(
                    "blueprint publication receipt failed tamper validation"
                )
            current = validate_project_blueprint(root, project=project)
            if (
                current["status"] != "pass"
                or current.get("authority_sha256") != receipt.get("authority_sha256")
                or current.get("artifact_index_sha256")
                != receipt.get("artifact_index_sha256")
            ):
                raise ValueError("published blueprint receipt is not current")
            return {
                **receipt,
                "publication_receipt": receipt_path.relative_to(root).as_posix(),
                "idempotent_replay": True,
            }

        current = validate_project_blueprint(root, project=project)
        if current["status"] != "pass" or current["sealed"] is not True:
            raise ValueError(
                "current blueprint is not sealed: "
                + ", ".join(str(item) for item in current["issues"])
            )
        expected = manifest.get("expected_current")
        if not isinstance(expected, dict) or (
            expected.get("authority_sha256") != current.get("authority_sha256")
            or expected.get("artifact_index_sha256")
            != current.get("artifact_index_sha256")
        ):
            raise ValueError("stale blueprint change set: current hashes changed")

        raw_changes = manifest.get("changes")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise ValueError("blueprint change set has no artifact changes")
        changes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_targets: set[str] = set()
        for raw_change in raw_changes:
            if not isinstance(raw_change, dict):
                raise ValueError("blueprint change entry must be a mapping")
            artifact_id = str(raw_change.get("artifact_id") or "").strip()
            source_relative = _safe_relative_path(
                raw_change.get("source_path"),
                allowed_roots=("artifacts",),
            )
            target_relative = _safe_relative_path(
                raw_change.get("production_path"),
                allowed_roots=("production", "project_brain"),
            )
            if (
                not artifact_id
                or artifact_id in seen_ids
                or target_relative.as_posix() in seen_targets
            ):
                raise ValueError("blueprint change has duplicate artifact identity")
            source = task_root / source_relative
            if (
                _has_symlink_component(source, task_root)
                or source.is_symlink()
                or not (source.is_file() or source.is_dir())
            ):
                raise ValueError(f"blueprint change source is missing: {source_relative}")
            expected_sha256 = str(raw_change.get("sha256") or "")
            if (
                not _SHA256.fullmatch(expected_sha256)
                or artifact_sha256(source) != expected_sha256
            ):
                raise ValueError(f"blueprint change source hash mismatch: {artifact_id}")
            seen_ids.add(artifact_id)
            seen_targets.add(target_relative.as_posix())
            changes.append(
                {
                    "artifact_id": artifact_id,
                    "source_relative": source_relative,
                    "target_relative": target_relative,
                    "source": source,
                    "candidate_sha256": expected_sha256,
                }
            )
        authority_changes = [
            item
            for item in changes
            if item["artifact_id"] == "narrative_blueprint_authority"
            and item["target_relative"].as_posix()
            == "production/blueprint_authority.yml"
        ]
        if len(authority_changes) != 1:
            raise ValueError(
                "blueprint change must include one narrative blueprint authority"
            )

        transaction_root = (
            project_root
            / ".agentlab"
            / "narrative_transactions"
            / receipt_key
        )
        if transaction_root.exists():
            raise ValueError("unrecovered narrative transaction already exists")
        if _has_symlink_component(transaction_root.parent, project_root):
            raise ValueError("narrative transaction path contains a symlink")
        stage_project = transaction_root / "stage" / "projects" / project
        backup_root = transaction_root / "backup"
        transaction_root.mkdir(parents=True)
        try:
            atomic_write_yaml(
                transaction_root / "prepared.yml",
                {
                    "schema_version": "narrative-blueprint-transaction/v1",
                    "status": "staging",
                    "project": project,
                    "task_id": task_id,
                    "change_set_sha256": manifest_sha256,
                    "receipt_path": receipt_path.relative_to(
                        project_root
                    ).as_posix(),
                    "targets": [],
                },
                sort_keys=False,
            )
        except BaseException:
            shutil.rmtree(transaction_root, ignore_errors=True)
            raise
        try:
            shutil.copytree(
                project_root / "production",
                stage_project / "production",
            )
            if (project_root / "project_brain").is_dir():
                shutil.copytree(
                    project_root / "project_brain",
                    stage_project / "project_brain",
                )
            shutil.copy2(
                project_root / "project_artifact_index.yml",
                stage_project / "project_artifact_index.yml",
            )
            index = _load_mapping(
                stage_project / "project_artifact_index.yml",
                label="staged project artifact index",
            )
            raw_artifacts = index.get("artifacts")
            if not isinstance(raw_artifacts, list):
                raise ValueError("project artifact index artifacts must be a list")
            current_records = {
                str(item.get("artifact_id") or ""): dict(item)
                for item in raw_artifacts
                if isinstance(item, dict) and item.get("status") == "current"
            }
            if len(current_records) != sum(
                1
                for item in raw_artifacts
                if isinstance(item, dict) and item.get("status") == "current"
            ):
                raise ValueError("project artifact index has duplicate current records")

            for change in changes:
                staged_target = stage_project / change["target_relative"]
                _remove_artifact(staged_target)
                staged_target.parent.mkdir(parents=True, exist_ok=True)
                _copy_artifact(change["source"], staged_target)

            staged_authority_path = (
                stage_project / "production" / "blueprint_authority.yml"
            )
            next_authority = _load_mapping(
                staged_authority_path,
                label="candidate blueprint authority",
            )
            if (
                next_authority.get("schema_version")
                != "narrative-blueprint-authority/v1"
                or next_authority.get("project") != project
                or next_authority.get("status")
                != "registered_pending_generic_validation"
            ):
                raise ValueError("candidate blueprint authority identity is invalid")
            next_authority["status"] = "validated_sealed"
            next_gate = dict(next_authority.get("production_gate") or {})
            next_gate["generic_blueprint_cli_profile_status"] = "implemented"
            next_authority["production_gate"] = next_gate
            next_authority["sealed_from_sha256"] = current["authority_sha256"]
            next_authority["sealed_by_task"] = task_id
            atomic_write_yaml(
                staged_authority_path,
                next_authority,
                sort_keys=False,
            )

            archive_root = (
                project_root / "archive" / "narrative_blueprints" / receipt_key
            )
            if _has_symlink_component(archive_root, project_root):
                raise ValueError("blueprint archive path contains a symlink")
            if archive_root.exists():
                raise ValueError(
                    "blueprint archive path already exists without a publication receipt"
                )
            next_records = [
                dict(item)
                for item in raw_artifacts
                if not (
                    isinstance(item, dict)
                    and item.get("status") == "current"
                    and str(item.get("artifact_id") or "") in seen_ids
                )
            ]
            for change in changes:
                artifact_id = change["artifact_id"]
                previous = current_records.get(artifact_id)
                if previous is None:
                    raise ValueError(
                        f"blueprint change artifact is not current: {artifact_id}"
                    )
                target_relative = change["target_relative"]
                if PurePosixPath(
                    str(previous.get("production_path") or "")
                ) != PurePosixPath(target_relative.as_posix()):
                    raise ValueError(
                        f"blueprint change target does not match current index: {artifact_id}"
                    )
                old_target = project_root / target_relative
                if not (old_target.is_file() or old_target.is_dir()):
                    raise ValueError(
                        f"current blueprint artifact is missing: {artifact_id}"
                    )
                archive_relative = (
                    Path("archive")
                    / "narrative_blueprints"
                    / receipt_key
                    / target_relative
                )
                archived = dict(previous)
                archived["status"] = "archived"
                archived["archive_path"] = archive_relative.as_posix()
                archived["archived_sha256"] = artifact_sha256(old_target)
                next_records.append(archived)
                staged_target = stage_project / target_relative
                final_sha256 = artifact_sha256(staged_target)
                next_records.append(
                    {
                        **previous,
                        "status": "current",
                        "current_version": f"{task_id}-{final_sha256[:16]}",
                        "production_sha256": final_sha256,
                        "source_task": task_id,
                        "source_run_artifact": change[
                            "source_relative"
                        ].as_posix(),
                        "supersedes": archived["archived_sha256"],
                        "archived_versions": [archive_relative.as_posix()],
                    }
                )
            next_index = dict(index)
            next_index["artifacts"] = next_records
            next_index["current"] = {
                str(item["artifact_id"]): str(item["production_path"])
                for item in next_records
                if item.get("status") == "current"
            }
            next_index["updated_at"] = datetime.now(timezone.utc).isoformat()
            atomic_write_yaml(
                stage_project / "project_artifact_index.yml",
                next_index,
                sort_keys=False,
            )
            staged_validation = validate_project_blueprint(
                transaction_root / "stage",
                project=project,
                require_seal_receipt=False,
            )
            if (
                staged_validation["status"] != "pass"
                or staged_validation["sealed"] is not True
            ):
                raise ValueError(
                    "candidate blueprint validation blocked: "
                    + ", ".join(str(item) for item in staged_validation["issues"])
                )
            validation_receipt = {
                "schema_version": "narrative-blueprint-validation-receipt/v1",
                "status": "pass",
                "project": project,
                "profile": "project_specific",
                "source_task": task_id,
                "change_set_sha256": manifest_sha256,
                "authority_sha256": staged_validation["authority_sha256"],
                "artifact_index_sha256": staged_validation[
                    "artifact_index_sha256"
                ],
                "validation": staged_validation,
            }
            staged_validation_receipt = (
                stage_project
                / "project_brain"
                / "blueprint_validation_receipt.yml"
            )
            atomic_write_yaml(
                staged_validation_receipt,
                validation_receipt,
                sort_keys=False,
            )

            target_records: list[dict[str, Any]] = []
            for change in changes:
                target_relative = change["target_relative"]
                target = project_root / target_relative
                _copy_artifact(
                    target,
                    archive_root / target_relative,
                    destination_root=project_root,
                )
                target_records.append(
                    {
                        "target_path": target_relative.as_posix(),
                        "existed": target.exists(),
                    }
                )
            validation_relative = Path(
                "project_brain/blueprint_validation_receipt.yml"
            )
            target_records.append(
                {
                    "target_path": validation_relative.as_posix(),
                    "existed": (
                        project_root / validation_relative
                    ).exists(),
                }
            )
            knowledge_snapshot_relative = Path(
                "project_brain/knowledge_index_snapshot.yml"
            )
            knowledge_snapshot_path = project_root / knowledge_snapshot_relative
            if _has_symlink_component(knowledge_snapshot_path, project_root):
                raise ValueError("project knowledge snapshot path contains a symlink")
            if knowledge_snapshot_relative.as_posix() not in {
                str(record["target_path"])
                for record in target_records
            }:
                target_records.append(
                    {
                        "target_path": knowledge_snapshot_relative.as_posix(),
                        "existed": knowledge_snapshot_path.is_file(),
                        "install_from_stage": False,
                    }
                )
            backup_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(
                project_root / "project_artifact_index.yml",
                backup_root / "project_artifact_index.yml",
            )
            prepared = {
                "schema_version": "narrative-blueprint-transaction/v1",
                "status": "prepared",
                "project": project,
                "task_id": task_id,
                "change_set_sha256": manifest_sha256,
                "receipt_path": receipt_path.relative_to(project_root).as_posix(),
                "targets": target_records,
            }
            atomic_write_yaml(
                transaction_root / "prepared.yml",
                prepared,
                sort_keys=False,
            )

            installed: list[Path] = []
            try:
                for record in target_records:
                    relative = Path(str(record["target_path"]))
                    target = project_root / relative
                    staged = stage_project / relative
                    backup = backup_root / relative
                    if record.get("install_from_stage") is False:
                        if target.exists():
                            backup.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(target, backup)
                        installed.append(relative)
                        continue
                    if target.exists():
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(target, backup)
                    installed.append(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, target)
                staged_index = stage_project / "project_artifact_index.yml"
                atomic_write_text(
                    project_root / "project_artifact_index.yml",
                    staged_index.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                final_validation = validate_project_blueprint(
                    root,
                    project=project,
                )
                if (
                    final_validation["status"] != "pass"
                    or final_validation["sealed"] is not True
                ):
                    raise ValueError(
                        "published blueprint validation blocked: "
                        + ", ".join(
                            str(item) for item in final_validation["issues"]
                        )
                    )
                publication_receipt = {
                    "schema_version": "narrative-blueprint-publication-receipt/v1",
                    "status": "published",
                    "project": project,
                    "task_id": task_id,
                    "idempotency_key": idempotency_key,
                    "change_set_sha256": manifest_sha256,
                    "acceptance_receipt_sha256": artifact_sha256(
                        Path(acceptance_receipt_path)
                    ),
                    "runtime_evidence": runtime_evidence,
                    "previous_authority_sha256": current["authority_sha256"],
                    "previous_artifact_index_sha256": current[
                        "artifact_index_sha256"
                    ],
                    "authority_sha256": final_validation["authority_sha256"],
                    "artifact_index_sha256": final_validation[
                        "artifact_index_sha256"
                    ],
                    "archive_root": archive_root.relative_to(project_root).as_posix(),
                    "changed_artifact_ids": sorted(seen_ids),
                }
            except BaseException:
                backup_index = backup_root / "project_artifact_index.yml"
                atomic_write_text(
                    project_root / "project_artifact_index.yml",
                    backup_index.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                for relative in reversed(installed):
                    target = project_root / relative
                    backup = backup_root / relative
                    _remove_artifact(target)
                    if backup.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(backup, target)
                receipt_path.unlink(missing_ok=True)
                if archive_root.exists():
                    shutil.rmtree(archive_root)
                if transaction_root.exists():
                    shutil.rmtree(transaction_root)
                raise
        except BaseException:
            if transaction_root.exists():
                try:
                    _recover_blueprint_transactions(project_root)
                except (OSError, ValueError) as recovery_error:
                    raise RuntimeError(
                        "blueprint transaction failed and recovery also failed"
                    ) from recovery_error
            raise

        knowledge_sync_status: str | None = None
        try:
            from agent_runtime.knowledge_system import sync_committed

            knowledge_sync = sync_committed(
                {
                    "agentlab_root": root,
                    "project": project,
                    "status": "promoted",
                    "domain": "longform_narrative",
                }
            ).as_dict()
            knowledge_sync_status = str(knowledge_sync.get("status") or "")
            if knowledge_sync_status != "SYNCED":
                raise ValueError(
                    "project knowledge sync did not commit: "
                    f"{knowledge_sync_status or 'unknown'}"
                )
            publication_receipt["knowledge_sync"] = knowledge_sync
            from agent_runtime.knowledge_system.operations import (
                write_project_knowledge_snapshot,
            )

            publication_receipt["project_knowledge_snapshot"] = (
                write_project_knowledge_snapshot(
                    root,
                    project=project,
                    build_receipt={
                        "projects": [project],
                        "receipt_id": knowledge_sync["receipt_id"],
                    },
                )
            )
            _create_immutable_yaml(receipt_path, publication_receipt)
        except BaseException:
            if transaction_root.exists():
                try:
                    _recover_blueprint_transactions(project_root)
                except (OSError, ValueError) as recovery_error:
                    raise RuntimeError(
                        "blueprint publication failed and recovery also failed"
                    ) from recovery_error
            if knowledge_sync_status == "SYNCED":
                try:
                    from agent_runtime.knowledge_system.config import (
                        load_knowledge_config,
                    )
                    from agent_runtime.knowledge_system.models import (
                        validate_namespace,
                    )
                    from agent_runtime.knowledge_system.storage import KnowledgeStore

                    knowledge_config = load_knowledge_config(root)
                    knowledge_store = KnowledgeStore(
                        root,
                        knowledge_config.runtime_path,
                        knowledge_config.keyword_backend,
                    )
                    for namespace in (
                        validate_namespace(f"project.{project}"),
                        validate_namespace("domain.longform_narrative"),
                    ):
                        knowledge_store.mark_stale(namespace)
                except Exception as repair_error:
                    raise RuntimeError(
                        "blueprint production rolled back but project knowledge "
                        "invalidation failed"
                    ) from repair_error
            raise
        if transaction_root.exists():
            shutil.rmtree(transaction_root)
        return {
            **publication_receipt,
            "publication_receipt": receipt_path.relative_to(root).as_posix(),
            "idempotent_replay": False,
        }
