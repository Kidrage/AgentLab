"""Immutable shared context manifests for narrative roles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from agent_runtime.atomic_io import atomic_write_text


def _source_record(path: Path, *, source_root: Path) -> dict[str, object]:
    resolved = Path(path).resolve()
    relative = resolved.relative_to(source_root)
    payload = resolved.read_bytes()
    return {
        "path": relative.as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_context_bundle(
    output_dir: Path,
    *,
    source_root: Path,
    canon_snapshot_sha256: str,
    chapter_window: Iterable[int],
    shared_files: Iterable[Path],
    role_specific_files: Mapping[str, Iterable[Path]],
) -> dict[str, object]:
    """Build or reuse one content-addressed narrative context manifest."""
    root = Path(source_root).resolve()
    shared = sorted(
        (_source_record(path, source_root=root) for path in shared_files),
        key=lambda item: str(item["path"]),
    )
    role_specific = {
        role: sorted(
            (_source_record(path, source_root=root) for path in paths),
            key=lambda item: str(item["path"]),
        )
        for role, paths in sorted(role_specific_files.items())
    }
    identity_payload = {
        "canon_snapshot_sha256": canon_snapshot_sha256,
        "chapter_window": sorted(set(int(chapter) for chapter in chapter_window)),
        "shared_files": shared,
        "role_specific_files": role_specific,
    }
    context_bundle_id = "ctx-" + hashlib.sha256(
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    manifest = {
        "schema_version": 1,
        "context_bundle_id": context_bundle_id,
        **identity_payload,
        "context_bytes": sum(int(item["bytes"]) for item in shared)
        + sum(
            int(item["bytes"])
            for records in role_specific.values()
            for item in records
        ),
    }
    payload = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    manifest_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / f"{context_bundle_id}.yml"
    reused = manifest_path.exists()
    if reused:
        if manifest_path.read_text(encoding="utf-8") != payload:
            raise ValueError("context bundle id collision or mutable manifest")
    else:
        atomic_write_text(manifest_path, payload)
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "reused": reused,
    }
