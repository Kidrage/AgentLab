"""Central Skill Vault for durable, local-first skill lifecycle storage."""

from __future__ import annotations

# text-integrity: keep this file as real physical lines in Git and GitHub raw.
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import shutil

import yaml

from atomic_io import atomic_write_yaml, safe_read_yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "enabled": True,
    "local_root": "memory/global/skills",
    "layout": {
        "inbox": "inbox",
        "drafts": "drafts",
        "approved": "approved",
        "staging": "staging",
        "active": "active",
        "rejected": "rejected",
        "retired": "retired",
        "quarantine": "quarantine",
    },
    "registry": {
        "file": "registry.yml",
        "manifest": "MANIFEST.yml",
        "require_source_trace": True,
        "require_validation_plan": True,
        "require_manual_approval": True,
    },
    "project_run_pointers": {
        "enabled": True,
        "pointer_filename": "POINTER.yml",
        "keep_lightweight_copy": False,
    },
    "git_policy": {
        "track_vault_contents": False,
        "track_config_only": True,
    },
    "safety": {
        "auto_promote": False,
        "external_discovery_enabled": False,
        "require_approval_for_self_learned": True,
        "require_approval_for_external": True,
        "auto_backup_on_skill_change": False,
    },
}

STATUSES = ("drafts", "approved", "staging", "active", "rejected", "retired", "quarantine")
INBOX_CHILDREN = ("self_learned", "external_imports", "discovered")
SKILL_FILES = (
    "SKILL.md",
    "metadata.yml",
    "validation_plan.yml",
    "evidence_map.yml",
    "source_trace.yml",
    "origin_pointer.yml",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_skill_vault_config(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "skill_vault.yml"
    data = safe_read_yaml(path, default={}) or {}
    return _deep_merge(DEFAULT_CONFIG, data if isinstance(data, dict) else {})


def vault_root(agentlab_root: Path, config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_skill_vault_config(agentlab_root)
    root = Path(str(cfg.get("local_root") or DEFAULT_CONFIG["local_root"]))
    return root if root.is_absolute() else agentlab_root / root


def _registry_path(agentlab_root: Path, config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_skill_vault_config(agentlab_root)
    return vault_root(agentlab_root, cfg) / str((cfg.get("registry") or {}).get("file") or "registry.yml")


def _manifest_path(agentlab_root: Path, config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_skill_vault_config(agentlab_root)
    return vault_root(agentlab_root, cfg) / str((cfg.get("registry") or {}).get("manifest") or "MANIFEST.yml")


def ensure_skill_vault_layout(agentlab_root: Path, config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_skill_vault_config(agentlab_root)
    root = vault_root(agentlab_root, cfg)
    root.mkdir(parents=True, exist_ok=True)
    inbox = root / str((cfg.get("layout") or {}).get("inbox") or "inbox")
    for child in INBOX_CHILDREN:
        (inbox / child).mkdir(parents=True, exist_ok=True)
    for status in STATUSES:
        (root / status).mkdir(parents=True, exist_ok=True)
    registry = _registry_path(agentlab_root, cfg)
    if not registry.exists():
        atomic_write_yaml(registry, {"version": 1, "skills": {}})
    manifest = _manifest_path(agentlab_root, cfg)
    if not manifest.exists():
        atomic_write_yaml(manifest, {"version": 1, "generated_at": utc_now(), "entries": []})
    return root


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_skill_path(agentlab_root: Path, skill_id: str, status: str = "drafts") -> Path:
    ensure_skill_vault_layout(agentlab_root)
    return vault_root(agentlab_root) / status / skill_id


def _load_registry(agentlab_root: Path) -> dict[str, Any]:
    ensure_skill_vault_layout(agentlab_root)
    data = safe_read_yaml(_registry_path(agentlab_root), default={}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("skills", {})
    return data


def write_registry_entry(agentlab_root: Path, skill_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    registry = _load_registry(agentlab_root)
    skills = registry.setdefault("skills", {})
    previous = skills.get(skill_id, {}) if isinstance(skills.get(skill_id), dict) else {}
    merged = dict(previous)
    merged.update(entry)
    merged["updated_at"] = utc_now()
    skills[skill_id] = merged
    atomic_write_yaml(_registry_path(agentlab_root), registry)
    return merged


def _file_role(path: Path) -> str:
    if path.name == "registry.yml":
        return "registry"
    if path.name == "MANIFEST.yml":
        return "manifest"
    if path.name == "metadata.yml":
        return "metadata"
    if path.name == "source_trace.yml":
        return "source_trace"
    if path.name == "origin_pointer.yml":
        return "origin_pointer"
    return "skill_artifact"


def update_manifest(agentlab_root: Path) -> dict[str, Any]:
    root = ensure_skill_vault_layout(agentlab_root)
    manifest_path = _manifest_path(agentlab_root)
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        data = path.read_bytes()
        entries.append({
            "path": _rel(path, agentlab_root),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "role": _file_role(path),
        })
    manifest = {"version": 1, "generated_at": utc_now(), "entries": entries}
    atomic_write_yaml(manifest_path, manifest)
    return manifest


def _copy_skill_files(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in SKILL_FILES:
        source = source_dir / name
        if source.exists() and source.is_file():
            shutil.copy2(source, target_dir / name)


def register_skill(
    agentlab_root: Path,
    skill_id: str,
    skill_dir: Path,
    metadata: dict[str, Any],
    *,
    status: str = "drafts",
) -> dict[str, Any]:
    ensure_skill_vault_layout(agentlab_root)
    metadata_path = skill_dir / "metadata.yml"
    metadata["id"] = skill_id
    metadata["status"] = status.rstrip("s") if status.endswith("s") else status
    metadata["vault_path"] = _rel(skill_dir, agentlab_root)
    metadata.setdefault("manual_approval_required", True)
    metadata.setdefault("auto_promote", False)
    atomic_write_yaml(metadata_path, metadata)
    entry = {
        "name": metadata.get("name") or skill_id,
        "status": metadata["status"],
        "source_type": metadata.get("source_type", "unknown"),
        "project": metadata.get("project"),
        "task_ids": metadata.get("task_ids") or [],
        "vault_path": _rel(skill_dir, agentlab_root),
        "created_at": metadata.get("created_at") or utc_now(),
        "updated_at": utc_now(),
        "risk_level": metadata.get("risk_level", "unknown"),
        "reuse_score": metadata.get("reuse_score"),
        "validation_signal": metadata.get("validation_signal"),
        "manual_approval_required": bool(metadata.get("manual_approval_required", True)),
        "auto_promote": False,
    }
    write_registry_entry(agentlab_root, skill_id, entry)
    update_manifest(agentlab_root)
    return entry


def move_skill_status(agentlab_root: Path, skill_id: str, from_status: str, to_status: str) -> Path:
    ensure_skill_vault_layout(agentlab_root)
    source = resolve_skill_path(agentlab_root, skill_id, from_status)
    if not source.exists():
        raise FileNotFoundError(f"Skill not found in {from_status}: {skill_id}")
    target = resolve_skill_path(agentlab_root, skill_id, to_status)
    if target.exists():
        raise FileExistsError(f"Target skill already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    metadata = safe_read_yaml(target / "metadata.yml", default={}) or {}
    if not isinstance(metadata, dict):
        metadata = {"id": skill_id}
    metadata["status"] = to_status.rstrip("s") if to_status.endswith("s") else to_status
    metadata["vault_path"] = _rel(target, agentlab_root)
    atomic_write_yaml(target / "metadata.yml", metadata)
    write_registry_entry(agentlab_root, skill_id, {
        "status": metadata["status"],
        "vault_path": _rel(target, agentlab_root),
        "project": metadata.get("project"),
        "task_ids": metadata.get("task_ids") or [],
        "name": metadata.get("name") or skill_id,
        "source_type": metadata.get("source_type", "unknown"),
        "risk_level": metadata.get("risk_level", "unknown"),
        "reuse_score": metadata.get("reuse_score"),
        "validation_signal": metadata.get("validation_signal"),
        "manual_approval_required": bool(metadata.get("manual_approval_required", True)),
        "auto_promote": False,
    })
    update_manifest(agentlab_root)
    return target


def create_project_run_pointer(
    agentlab_root: Path,
    project: str,
    task_id: str,
    skill_id: str,
    vault_path: Path,
    *,
    status: str = "draft",
) -> Path:
    cfg = load_skill_vault_config(agentlab_root)
    pointer_cfg = cfg.get("project_run_pointers") or {}
    pointer_name = str(pointer_cfg.get("pointer_filename") or "POINTER.yml")
    pointer_dir = agentlab_root / "projects" / project / "runs" / task_id / "skill_drafts" / skill_id
    pointer_dir.mkdir(parents=True, exist_ok=True)
    pointer = {
        "skill_id": skill_id,
        "vault_path": _rel(vault_path, agentlab_root),
        "source_project": project,
        "source_task_id": task_id,
        "status": status,
    }
    atomic_write_yaml(pointer_dir / pointer_name, pointer)
    return pointer_dir / pointer_name


def list_vault_skills(agentlab_root: Path, project: str | None = None, statuses: list[str] | None = None) -> list[dict[str, Any]]:
    registry = _load_registry(agentlab_root)
    wanted = {s.rstrip("s") for s in statuses} if statuses else None
    rows: list[dict[str, Any]] = []
    for skill_id, entry in sorted((registry.get("skills") or {}).items()):
        if not isinstance(entry, dict):
            continue
        if project and entry.get("project") != project:
            continue
        if wanted and str(entry.get("status", "")).rstrip("s") not in wanted:
            continue
        row = dict(entry)
        row["id"] = skill_id
        row["path"] = str(agentlab_root / str(entry.get("vault_path", "")))
        row["task_id"] = ((entry.get("task_ids") or [""])[0])
        rows.append(row)
    return rows


def migrate_project_run_draft_to_vault(
    agentlab_root: Path,
    project: str,
    *,
    dry_run: bool = True,
    execute: bool = False,
) -> dict[str, Any]:
    run_root = agentlab_root / "projects" / project / "runs"
    migrations: list[dict[str, Any]] = []
    if not run_root.exists():
        return {"project": project, "dry_run": dry_run or not execute, "migrations": []}
    for draft_dir in sorted(run_root.glob("*/skill_drafts/*")):
        if not draft_dir.is_dir():
            continue
        if not (draft_dir / "SKILL.md").exists() or not (draft_dir / "metadata.yml").exists():
            continue
        skill_id = draft_dir.name
        target = resolve_skill_path(agentlab_root, skill_id, "drafts")
        item = {"skill_id": skill_id, "source": _rel(draft_dir, agentlab_root), "target": _rel(target, agentlab_root)}
        if target.exists():
            item["status"] = "already_exists"
        else:
            item["status"] = "planned" if (dry_run or not execute) else "migrated"
            if execute and not dry_run:
                _copy_skill_files(draft_dir, target)
                metadata = safe_read_yaml(target / "metadata.yml", default={}) or {}
                if not isinstance(metadata, dict):
                    metadata = {"id": skill_id}
                metadata.setdefault("project", project)
                metadata.setdefault("task_ids", [draft_dir.parents[1].name])
                metadata["legacy_task_scoped_path"] = _rel(draft_dir, agentlab_root)
                origin = {
                    "source_project": project,
                    "source_task_id": draft_dir.parents[1].name,
                    "source_run_path": _rel(draft_dir.parents[1], agentlab_root),
                    "original_draft_path": _rel(draft_dir, agentlab_root),
                    "created_by": "skill_vault_migrate",
                    "created_at": utc_now(),
                }
                atomic_write_yaml(target / "origin_pointer.yml", origin)
                register_skill(agentlab_root, skill_id, target, metadata, status="drafts")
                create_project_run_pointer(agentlab_root, project, draft_dir.parents[1].name, skill_id, target)
        migrations.append(item)
    if execute and not dry_run:
        update_manifest(agentlab_root)
    return {"project": project, "dry_run": dry_run or not execute, "migrations": migrations}


def vault_status(agentlab_root: Path) -> dict[str, Any]:
    root = ensure_skill_vault_layout(agentlab_root)
    rows = list_vault_skills(agentlab_root)
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"vault_root": _rel(root, agentlab_root), "counts": counts, "total": len(rows)}
