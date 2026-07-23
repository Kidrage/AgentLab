"""Conflict-first migration from legacy project files into canonical truth."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

import yaml

from agent_runtime.atomic_io import atomic_write_yaml

from .models import ChangeSet, FactChange, ResourceChange
from .store import ProjectTruthConflict, ProjectTruthStore


_SCAN_ROOTS = ("project_brain", "config", "production")
_STRUCTURED = {".yml", ".yaml", ".json"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scalar_leaves(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _scalar_leaves(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _scalar_leaves(child, (*path, str(index)))
    elif path:
        yield path[-1], value


class ProjectTruthMigrator:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def plan(self, project_id: str) -> dict[str, Any]:
        observations: dict[str, list[dict[str, Any]]] = {}
        scanned: list[dict[str, Any]] = []
        for path in self._source_files():
            relative = path.relative_to(self.project_root).as_posix()
            scanned.append({"path": relative, "sha256": _digest(path)})
            if path.suffix.lower() not in _STRUCTURED:
                continue
            try:
                if path.suffix.lower() == ".json":
                    data = json.loads(path.read_text(encoding="utf-8"))
                else:
                    data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, yaml.YAMLError):
                continue
            for leaf_key, value in _scalar_leaves(data):
                observations.setdefault(leaf_key, []).append(
                    {"path": relative, "value": value}
                )
        conflicts = []
        for leaf_key, entries in sorted(observations.items()):
            encoded = {
                json.dumps(
                    item["value"],
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                for item in entries
            }
            if len(encoded) > 1:
                conflicts.append(
                    {
                        "leaf_key": leaf_key,
                        "values": sorted(encoded),
                        "evidence": entries,
                    }
                )
        return {
            "schema_version": "project-truth-migration-plan/v1",
            "project_id": project_id,
            "status": (
                "requires_human_resolution" if conflicts else "ready_for_manifest"
            ),
            "activation_ready": False,
            "scanned_sources": scanned,
            "potential_fact_conflicts": conflicts,
            "next_action": (
                "Create an explicit project-truth-migration/v1 manifest; "
                "do not infer winners from file timestamps or names."
            ),
        }

    def apply(self, manifest: dict[str, Any]) -> dict[str, Any]:
        if manifest.get("schema_version") != "project-truth-migration/v1":
            raise ValueError("project truth migration schema mismatch")
        project_id = str(manifest.get("project_id") or "")
        if not project_id:
            raise ValueError("migration project_id is required")
        self._verify_sources(manifest.get("expected_source_hashes") or {})
        project_manifest_path = self.project_root / "project.yml"
        project_manifest = (
            yaml.safe_load(project_manifest_path.read_text(encoding="utf-8")) or {}
        )
        features = project_manifest.get("features") or {}
        if features.get("project_truth_mode", "legacy") == "enforced":
            raise ProjectTruthConflict("project truth is already enforced")

        truth = ProjectTruthStore(self.project_root)
        pointer = truth.initialize(project_id)
        facts = tuple(
            FactChange(
                key=str(item["key"]),
                value=item.get("value"),
                owner=str(item["owner"]),
            )
            for item in (manifest.get("facts") or [])
        )
        resources = tuple(
            self._resource_change(item)
            for item in (manifest.get("resources") or [])
        )
        if not facts and not resources:
            raise ValueError("migration manifest contains no canonical truth")
        receipt = truth.commit(
            ChangeSet(
                project_id=project_id,
                expected_snapshot_id=pointer.current_snapshot_id,
                actor_id="user",
                idempotency_key=str(manifest.get("idempotency_key") or ""),
                reason="Explicit legacy project truth migration.",
                facts=facts,
                resources=resources,
            )
        )

        features = project_manifest.setdefault("features", {})
        features["project_truth_mode"] = "enforced"
        features["enable_project_agents"] = (
            manifest.get("enable_project_agents") is True
        )
        project_manifest.setdefault("workspace", {})["isolation"] = "required"
        atomic_write_yaml(project_manifest_path, project_manifest, sort_keys=False)
        result = {
            "schema_version": "project-truth-migration-result/v1",
            "status": "migrated",
            "project_id": project_id,
            "canonical_commit_receipt": receipt.to_dict(),
            "legacy_sources_disposition": "non_authoritative_evidence",
        }
        atomic_write_yaml(
            self.project_root
            / ".agentlab"
            / "truth"
            / "migration_result.yml",
            result,
            sort_keys=False,
        )
        return result

    def _source_files(self) -> Iterator[Path]:
        for root_name in _SCAN_ROOTS:
            root = self.project_root / root_name
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    yield path

    def _verify_sources(self, hashes: dict[str, Any]) -> None:
        for relative, expected in hashes.items():
            path = (self.project_root / str(relative)).resolve()
            try:
                path.relative_to(self.project_root)
            except ValueError as exc:
                raise ValueError("migration source escapes project root") from exc
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"migration source is unavailable: {relative}")
            if _digest(path) != str(expected):
                raise ProjectTruthConflict(
                    f"migration source changed since review: {relative}"
                )

    def _resource_change(self, item: dict[str, Any]) -> ResourceChange:
        relative = str(item["source_path"])
        path = (self.project_root / relative).resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("migration resource escapes project root") from exc
        media_type = str(item.get("media_type") or "application/yaml")
        if media_type == "application/yaml":
            content = yaml.safe_load(path.read_text(encoding="utf-8"))
        elif media_type == "application/json":
            content = json.loads(path.read_text(encoding="utf-8"))
        else:
            content = path.read_text(encoding="utf-8")
        return ResourceChange(
            key=str(item["key"]),
            content=content,
            media_type=media_type,
        )
