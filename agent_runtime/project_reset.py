"""Hash-bound, fail-closed project reset planning and execution."""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from typing import Iterable, Mapping, Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


class ProjectResetError(RuntimeError):
    """Base error for a reset that cannot proceed safely."""


class ActiveProjectResetError(ProjectResetError):
    """Raised when an active lock or background job protects the project."""


class ProjectResetApplyError(ProjectResetError):
    """Raised with the metadata-only receipt for a partially applied reset."""

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        self.result = result
        super().__init__(message)


_TERMINAL_JOB_STATES = {"blocked", "cancelled", "completed", "failed", "stopped"}
_TERMINAL_LOCK_STATES = {"complete", "completed", "released"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_GLOB_OR_SHELL_CHARS = frozenset("*?[]{};|&")
_EMPTY_RUNTIME_ROOTS = frozenset({"archive", "background_jobs", "candidates", "runs"})
_STATE_FILES = (
    "PROJECT_HANDOFF.md",
    "project_artifact_index.yml",
    "project_brain/project_fact_snapshot.yml",
    "project_brain/fact_distillation.yml",
    "project_brain/project_state_contract.yml",
    "project_brain/revision_log.jsonl",
    "task_index.yml",
)

CROWN_RESET_TARGETS = (
    ".agentlab",
    "PROJECT_HANDOFF.md",
    "agent_docs/00_CONTEXT_PACK.md",
    "agent_docs/01_REPO_MAP.md",
    "agent_docs/02_TASK_LEDGER.yml",
    "agent_docs/04_INTERFACE_REGISTRY.md",
    "agent_docs/07_DEVELOPMENT_LOG.md",
    "agent_docs/08_CODEX_DIALOGUE_LOG.md",
    "agent_docs/09_COST_LEDGER.yml",
    "agent_docs/HandOff.md",
    "archive",
    "background_jobs",
    "candidates",
    "production",
    "project_artifact_index.yml",
    "project_brain",
    "prompt_templates",
    "runs",
    "skill_requests",
    "skills",
    "task_index.yml",
)


def _validated_targets(project_root: Path, targets: Iterable[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for raw in targets:
        target = str(raw).strip()
        pure = PurePosixPath(target)
        if (
            not target
            or target in {".", ".."}
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
            or any(char in target for char in _GLOB_OR_SHELL_CHARS)
        ):
            raise ProjectResetError(f"unsafe reset target: {raw!r}")
        candidate = (project_root / Path(*pure.parts)).resolve(strict=False)
        if candidate == project_root or project_root not in candidate.parents:
            raise ProjectResetError(f"unsafe reset target: {raw!r}")
        normalized = pure.as_posix()
        if normalized in ordered:
            raise ProjectResetError(f"unsafe reset target: duplicate {normalized!r}")
        if any(
            normalized.startswith(f"{existing}/")
            or existing.startswith(f"{normalized}/")
            for existing in ordered
        ):
            raise ProjectResetError(f"unsafe reset target overlap: {normalized!r}")
        ordered.append(normalized)
    if not ordered:
        raise ProjectResetError("unsafe reset target: no targets supplied")
    return tuple(sorted(ordered))


def _active_collaboration_locks(root: Path, project: str) -> tuple[Path, ...]:
    locks_dir = root / ".agents" / "locks"
    if not locks_dir.is_dir():
        return ()
    project_marker = f"projects/{project}"
    active: list[Path] = []
    for path in sorted(locks_dir.glob("*.lock")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            active.append(path)
            continue
        if not isinstance(raw, dict):
            active.append(path)
            continue
        status = str(raw.get("status") or "in_progress").strip().lower()
        if status in _TERMINAL_LOCK_STATES:
            continue
        declared_paths = raw.get("paths")
        if isinstance(declared_paths, list):
            protects_project = any(
                _lock_path_overlaps_project(str(item), project_marker)
                for item in declared_paths
            )
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            protects_project = project_marker in text
        if protects_project:
            active.append(path)
    return tuple(active)


def _lock_path_overlaps_project(raw: str, project_marker: str) -> bool:
    normalized = PurePosixPath(str(raw).strip().rstrip("/")).as_posix()
    parts = PurePosixPath(normalized).parts
    marker_parts = PurePosixPath(project_marker).parts
    contains_project = any(
        parts[index : index + len(marker_parts)] == marker_parts
        for index in range(max(0, len(parts) - len(marker_parts) + 1))
    )
    return (
        contains_project
        or
        normalized == project_marker
        or normalized.startswith(f"{project_marker}/")
        or project_marker.startswith(f"{normalized}/")
    )


_DISTILLATION_FIELDS = frozenset(
    {
        "id",
        "kind",
        "value",
        "attributes",
        "refs",
        "source_hashes",
        "conflict_status",
        "conflict_conclusion",
    }
)
_PROSE_PAYLOAD_KEYS = frozenset(
    {
        "body",
        "content",
        "draft",
        "excerpt",
        "legacy_excerpt",
        "manuscript",
        "prose",
        "quote",
        "raw_prose",
        "raw_text",
        "text",
    }
)


def _metadata_value_issues(value: Any, path: str, *, depth: int = 0) -> list[str]:
    if depth > 8:
        return [f"metadata_depth_exceeded:{path}"]
    if isinstance(value, Mapping):
        issues: list[str] = []
        if len(value) > 100:
            issues.append(f"metadata_mapping_too_large:{path}")
        for key, child in value.items():
            if not isinstance(key, str):
                issues.append(f"invalid_payload_key:{path}")
                continue
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _PROSE_PAYLOAD_KEYS:
                issues.append(f"forbidden_payload_key:{path}.{key}")
                continue
            issues.extend(
                _metadata_value_issues(child, f"{path}.{key}", depth=depth + 1)
            )
        return issues
    if isinstance(value, list):
        issues = [f"metadata_list_too_large:{path}"] if len(value) > 100 else []
        for index, child in enumerate(value):
            issues.extend(
                _metadata_value_issues(child, f"{path}[{index}]", depth=depth + 1)
            )
        return issues
    if isinstance(value, str):
        if len(value) > 500 or "\n" in value or "\r" in value:
            return [f"prose_like_string:{path}"]
        return []
    if value is None or isinstance(value, (bool, int, float)):
        return []
    return [f"unsupported_metadata_value:{path}"]


def fact_distillation_issues(
    document: Mapping[str, Any],
    *,
    allowed_source_hashes: set[str] | None = None,
) -> list[str]:
    """Validate the closed, metadata-only fact seed shared by reset and blueprint."""
    issues: list[str] = []
    schema_version = document.get("schema_version")
    if isinstance(schema_version, bool) or not (
        schema_version == 1 or schema_version == "1"
    ):
        issues.append("invalid_schema_version")
    if document.get("status") != "approved":
        issues.append("not_approved")
    if document.get("legacy_prose_retained") is not False:
        issues.append("legacy_prose_retained")
    facts = document.get("facts")
    if not isinstance(facts, list) or not facts:
        return [*issues, "missing_structured_facts"]
    try:
        encoded_size = len(
            json.dumps(document, ensure_ascii=False, default=str).encode("utf-8")
        )
    except (TypeError, ValueError):
        encoded_size = 1_000_001
    if encoded_size > 1_000_000:
        issues.append("distillation_payload_too_large")
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, Mapping):
            issues.append("invalid_fact_record")
            continue
        fact_id = str(fact.get("id") or "")
        if not _SAFE_ID.fullmatch(fact_id):
            issues.append(f"invalid_id:{fact_id or 'missing'}")
        elif fact_id in seen:
            issues.append(f"duplicate_id:{fact_id}")
        seen.add(fact_id)
        for raw_field in fact:
            if not isinstance(raw_field, str):
                issues.append(f"invalid_field_key:{fact_id or 'missing'}")
            elif raw_field not in _DISTILLATION_FIELDS:
                issues.append(f"forbidden_field:{fact_id or 'missing'}:{raw_field}")
        kind = str(fact.get("kind") or "")
        if not _SAFE_ID.fullmatch(kind):
            issues.append(f"invalid_kind:{fact_id or 'missing'}")
        if not any(field in fact for field in ("value", "attributes", "refs")):
            issues.append(f"missing_fact_value:{fact_id or 'missing'}")
        for field in ("value", "attributes", "refs"):
            if field in fact:
                issues.extend(
                    _metadata_value_issues(
                        fact[field],
                        f"{fact_id or 'missing'}.{field}",
                    )
                )
        hashes = fact.get("source_hashes")
        if not isinstance(hashes, list) or not hashes:
            issues.append(f"invalid_source_hash:{fact_id or 'missing'}")
        else:
            for raw_hash in hashes:
                source_hash = str(raw_hash)
                if not _HASH.fullmatch(source_hash):
                    issues.append(f"invalid_source_hash:{fact_id or 'missing'}")
                elif (
                    allowed_source_hashes is not None
                    and source_hash not in allowed_source_hashes
                ):
                    issues.append(f"unbound_source_hash:{fact_id or 'missing'}:{source_hash}")
        if not str(fact.get("conflict_status") or "").strip():
            issues.append(f"missing_conflict_status:{fact_id or 'missing'}")
        if not str(fact.get("conflict_conclusion") or "").strip():
            issues.append(f"missing_conflict_conclusion:{fact_id or 'missing'}")
        else:
            issues.extend(
                _metadata_value_issues(
                    fact.get("conflict_conclusion"),
                    f"{fact_id or 'missing'}.conflict_conclusion",
                )
            )
    return sorted(set(issues))


def _active_background_jobs(project_root: Path) -> tuple[Path, ...]:
    jobs_dir = project_root / "background_jobs"
    if not jobs_dir.is_dir():
        return ()
    active: list[Path] = []
    for state_path in sorted(jobs_dir.glob("*/job_state.yml")):
        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            active.append(state_path.parent)
            continue
        status = str(state.get("status") or "unknown").strip().lower()
        if status not in _TERMINAL_JOB_STATES or state.get("active_attempt"):
            active.append(state_path.parent)
    return tuple(active)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory_entry(project_root: Path, path: Path) -> dict:
    relative = path.relative_to(project_root).as_posix()
    if path.is_symlink():
        kind = "symlink"
        sha256 = hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    elif path.is_file():
        kind = "file"
        sha256 = _sha256_file(path)
    elif path.is_dir():
        kind = "directory"
        sha256 = None
    elif not path.exists():
        return {
            "path": relative,
            "kind": "missing",
            "sha256": None,
            "status": "absent",
            "deletion_result": "not_applicable",
        }
    else:
        raise ProjectResetError(f"unsupported reset target kind: {relative}")
    return {
        "path": relative,
        "kind": kind,
        "sha256": sha256,
        "status": "present",
        "deletion_result": "pending",
    }


def _inventory(project_root: Path, targets: tuple[str, ...]) -> list[dict]:
    entries: dict[str, dict] = {}
    pending = [project_root / Path(*PurePosixPath(target).parts) for target in targets]
    while pending:
        path = pending.pop()
        entry = _inventory_entry(project_root, path)
        entries[entry["path"]] = entry
        if entry["kind"] == "directory":
            try:
                children = sorted(path.iterdir(), key=lambda item: item.name, reverse=True)
            except OSError as exc:
                raise ProjectResetError(f"cannot inventory reset target {entry['path']}: {exc}") from exc
            pending.extend(children)
    return [entries[path] for path in sorted(entries)]


def _target_covers(target: str, relative: str) -> bool:
    return relative == target or relative.startswith(f"{target}/")


def _reinitialize_declared_state(
    project_root: Path,
    *,
    project: str,
    plan_id: str,
    targets: tuple[str, ...],
    distillation: Mapping[str, Any] | None = None,
) -> None:
    selected = {
        relative
        for relative in _STATE_FILES
        if any(_target_covers(target, relative) for target in targets)
    }
    distilled_facts = list(distillation.get("facts") or []) if distillation else []
    source_hashes = {
        str(fact["id"]): [str(item) for item in fact.get("source_hashes") or []]
        for fact in distilled_facts
        if isinstance(fact, Mapping) and fact.get("id")
    }
    conflicts = [
        {
            "fact_id": str(fact["id"]),
            "status": str(fact.get("conflict_status") or ""),
            "conclusion": str(fact.get("conflict_conclusion") or ""),
        }
        for fact in distilled_facts
        if isinstance(fact, Mapping) and fact.get("id")
    ]
    yaml_documents = {
        "task_index.yml": {"schema_version": 1, "project": project, "tasks": []},
        "project_artifact_index.yml": {
            "schema_version": 1,
            "project": project,
            "artifacts": [],
            "current": {},
        },
        "project_brain/project_fact_snapshot.yml": {
            "schema_version": 1,
            "project": project,
            "reset_plan_id": plan_id,
            "facts": distilled_facts,
            "source_hashes": source_hashes,
            "conflicts": conflicts,
        },
        "project_brain/fact_distillation.yml": dict(distillation or {}),
        "project_brain/project_state_contract.yml": {
            "schema_version": 1,
            "project": project,
            "reset_plan_id": plan_id,
            "candidate_only": True,
            "production_promotion_allowed": False,
            "formal_fact_roots": ["production", "project_brain"],
            "writer_forbidden_roots": [
                "acceptance_runs",
                "agent_docs",
                "archive",
                "background_jobs",
                "candidates",
                "runs",
            ],
        },
    }
    for relative, document in yaml_documents.items():
        if relative in selected:
            atomic_write_yaml(project_root / relative, document)
    if "project_brain/revision_log.jsonl" in selected:
        atomic_write_text(project_root / "project_brain/revision_log.jsonl", "")
    if "PROJECT_HANDOFF.md" in selected:
        atomic_write_text(
            project_root / "PROJECT_HANDOFF.md",
            (
                "# Crown of Ash Project Handoff\n\n"
                f"- Project: {project}\n"
                f"- Reset plan: {plan_id}\n"
                "- Status: reset applied; canonical blueprint rebuild pending\n"
                "- Candidate prose promotion: prohibited pending user review\n"
            ),
        )


def plan_project_reset(
    agentlab_root: Path,
    *,
    project: str,
    targets: Iterable[str],
    plan_id: str | None = None,
    now: str | None = None,
    distillation_seed: str | None = None,
) -> dict:
    """Plan an exact project reset without mutating project state."""
    root = Path(agentlab_root).resolve()
    if not _SAFE_ID.fullmatch(project):
        raise ProjectResetError(f"unsafe project id: {project!r}")
    project_root = root / "projects" / project
    if not project_root.is_dir():
        raise ProjectResetError(f"project root does not exist: {project_root}")
    active = _active_collaboration_locks(root, project)
    if active:
        names = ", ".join(path.name for path in active)
        raise ActiveProjectResetError(f"active project reset lock(s): {names}")
    active_jobs = _active_background_jobs(project_root)
    if active_jobs:
        names = ", ".join(path.name for path in active_jobs)
        raise ActiveProjectResetError(f"active project background job(s): {names}")
    validated_targets = _validated_targets(project_root, targets)
    resolved_plan_id = plan_id or f"reset-{project}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if not _SAFE_ID.fullmatch(resolved_plan_id):
        raise ProjectResetError(f"unsafe reset plan id: {resolved_plan_id!r}")
    entries = _inventory(project_root, validated_targets)
    preserved_distillation = _plan_distillation_seed(
        project_root,
        project=project,
        targets=validated_targets,
        entries=entries,
        relative=distillation_seed,
    )
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result = {
        "schema_version": 1,
        "plan_id": resolved_plan_id,
        "project": project,
        "created_at": now or datetime.now(timezone.utc).isoformat(),
        "status": "preview",
        "targets": list(validated_targets),
        "entry_count": len(entries),
        "inventory_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "entries": entries,
    }
    if preserved_distillation is not None:
        result["preserved_distillation"] = preserved_distillation
    result["plan_binding_sha256"] = _plan_binding_digest(result)
    return result


def _plan_binding_digest(plan: Mapping[str, Any]) -> str:
    payload = {
        "schema_version": plan.get("schema_version"),
        "plan_id": plan.get("plan_id"),
        "project": plan.get("project"),
        "targets": plan.get("targets"),
        "inventory_sha256": plan.get("inventory_sha256"),
        "preserved_distillation": plan.get("preserved_distillation"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _surviving_distillation_path(
    project_root: Path,
    pure: PurePosixPath,
) -> Path:
    cursor = project_root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ProjectResetError("distillation seed path must not contain symlinks")
    resolved = cursor.resolve()
    surviving_root = (project_root / "reset_manifests").resolve()
    if surviving_root not in resolved.parents or not resolved.is_file():
        raise ProjectResetError(
            "distillation seed must resolve inside surviving reset_manifests/"
        )
    return resolved


def _plan_distillation_seed(
    project_root: Path,
    *,
    project: str,
    targets: tuple[str, ...],
    entries: list[dict[str, Any]],
    relative: str | None,
) -> dict[str, Any] | None:
    destroys_crown_facts = project == "Crown_of_Ash" and any(
        target in {"production", "project_brain"} for target in targets
    )
    if relative is None:
        if destroys_crown_facts:
            raise ProjectResetError(
                "Crown reset requires a validated --distillation-seed outside deleted targets"
            )
        return None
    pure = PurePosixPath(str(relative))
    normalized = pure.as_posix()
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not normalized.startswith("reset_manifests/")
        or any(_target_covers(target, normalized) for target in targets)
    ):
        raise ProjectResetError("distillation seed must be under surviving reset_manifests/")
    path = _surviving_distillation_path(project_root, pure)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ProjectResetError(f"cannot read distillation seed: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ProjectResetError("distillation seed must contain a YAML mapping")
    inventory_hashes = {
        str(item["sha256"])
        for item in entries
        if item.get("kind") in {"file", "symlink"} and item.get("sha256")
    }
    issues = fact_distillation_issues(
        document,
        allowed_source_hashes=inventory_hashes,
    )
    if issues:
        raise ProjectResetError(f"invalid distillation seed: {', '.join(issues)}")
    return {
        "path": normalized,
        "sha256": _sha256_file(path),
        "fact_count": len(document["facts"]),
        "status": "validated",
    }


def _inventory_digest(entries: list[dict]) -> str:
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def apply_project_reset(
    agentlab_root: Path,
    *,
    plan: Mapping[str, Any],
    confirm_project: str,
    now: str | None = None,
) -> dict:
    """Apply a previously previewed reset only when every byte is unchanged."""
    root = Path(agentlab_root).resolve()
    project = str(plan.get("project") or "")
    if confirm_project != project or not _SAFE_ID.fullmatch(project):
        raise ProjectResetError("explicit project confirmation does not match reset plan")
    if int(plan.get("schema_version") or 0) != 1 or plan.get("status") != "preview":
        raise ProjectResetError("invalid reset plan schema or status")
    if _plan_binding_digest(plan) != str(plan.get("plan_binding_sha256") or ""):
        raise ProjectResetError("reset plan binding digest mismatch")
    project_root = root / "projects" / project
    targets = _validated_targets(project_root, plan.get("targets") or ())
    if (
        project == "Crown_of_Ash"
        and any(target in {"production", "project_brain"} for target in targets)
        and not isinstance(plan.get("preserved_distillation"), Mapping)
    ):
        raise ProjectResetError("Crown reset apply requires preserved distillation binding")
    expected_entries = plan.get("entries")
    if not isinstance(expected_entries, list) or any(
        not isinstance(item, dict) for item in expected_entries
    ):
        raise ProjectResetError("invalid reset plan entries")
    if _inventory_digest(expected_entries) != str(plan.get("inventory_sha256") or ""):
        raise ProjectResetError("reset plan inventory digest mismatch")
    active = _active_collaboration_locks(root, project)
    active_jobs = _active_background_jobs(project_root)
    if active or active_jobs:
        names = ", ".join(path.name for path in (*active, *active_jobs))
        raise ActiveProjectResetError(f"active project reset protection: {names}")
    current_entries = _inventory(project_root, targets)
    if current_entries != expected_entries:
        raise ProjectResetError("reset inventory changed after preview")
    distillation = _load_planned_distillation(
        project_root,
        plan=plan,
        entries=expected_entries,
    )
    result = json.loads(json.dumps(dict(plan), ensure_ascii=False))
    result_entries = {item["path"]: item for item in result["entries"]}
    ordered = sorted(
        expected_entries,
        key=lambda item: (len(PurePosixPath(item["path"]).parts), item["path"]),
        reverse=True,
    )
    for item in ordered:
        relative = str(item["path"])
        output = result_entries[relative]
        if item["kind"] == "missing":
            continue
        path = project_root / Path(*PurePosixPath(relative).parts)
        try:
            if item["kind"] == "directory":
                path.rmdir()
            else:
                path.unlink()
        except OSError as exc:
            output["deletion_result"] = f"failed:{type(exc).__name__}"
            result["status"] = "failed_partial"
            result["applied_at"] = now or datetime.now(timezone.utc).isoformat()
            raise ProjectResetApplyError(
                f"reset deletion failed at {relative}: {exc}", result
            ) from exc
        output["status"] = "deleted"
        output["deletion_result"] = "deleted"
    for target in targets:
        if target in _EMPTY_RUNTIME_ROOTS:
            (project_root / target).mkdir(parents=True, exist_ok=False)
    _reinitialize_declared_state(
        project_root,
        project=project,
        plan_id=str(plan.get("plan_id") or ""),
        targets=targets,
        distillation=distillation,
    )
    result["status"] = "applied"
    result["applied_at"] = now or datetime.now(timezone.utc).isoformat()
    return result


def _load_planned_distillation(
    project_root: Path,
    *,
    plan: Mapping[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    binding = plan.get("preserved_distillation")
    if binding is None:
        return None
    if not isinstance(binding, Mapping) or binding.get("status") != "validated":
        raise ProjectResetError("invalid preserved distillation binding")
    relative = str(binding.get("path") or "")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not pure.as_posix().startswith("reset_manifests/")
    ):
        raise ProjectResetError("unsafe preserved distillation path")
    path = _surviving_distillation_path(project_root, pure)
    if _sha256_file(path) != str(binding.get("sha256") or ""):
        raise ProjectResetError("preserved distillation seed changed after preview")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ProjectResetError(f"cannot read preserved distillation: {exc}") from exc
    if not isinstance(document, dict):
        raise ProjectResetError("preserved distillation must contain a YAML mapping")
    inventory_hashes = {
        str(item["sha256"])
        for item in entries
        if item.get("kind") in {"file", "symlink"} and item.get("sha256")
    }
    issues = fact_distillation_issues(
        document,
        allowed_source_hashes=inventory_hashes,
    )
    if issues or len(document.get("facts") or []) != int(binding.get("fact_count") or 0):
        raise ProjectResetError("preserved distillation validation changed after preview")
    return document
