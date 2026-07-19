"""Hash-bound integrity checks for a prepared narrative audit snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_audit_source_integrity(
    manifest: Mapping[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    """Recompute every source hash and return one candidate snapshot hash."""
    bindings: list[dict[str, Any]] = []
    issues: list[str] = []
    root = Path(project_root).resolve()
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        issues.append("missing_audit_manifest_sources")
    else:
        for source in sources:
            if not isinstance(source, Mapping) or not isinstance(source.get("files"), Mapping):
                issues.append("invalid_audit_manifest_source")
                continue
            chapter = source.get("chapter")
            for name, record in sorted(source["files"].items()):
                if not isinstance(record, Mapping):
                    issues.append(f"invalid_audit_source_record:{chapter}:{name}")
                    continue
                relative = str(record.get("path") or "")
                expected = str(record.get("sha256") or "")
                try:
                    path = (root / relative).resolve()
                    path.relative_to(root)
                except (ValueError, OSError):
                    issues.append(f"audit_source_path_escape:{chapter}:{name}")
                    continue
                actual = _sha256(path) if path.is_file() else None
                bindings.append(
                    {
                        "chapter": chapter,
                        "name": str(name),
                        "path": relative,
                        "sha256": expected,
                    }
                )
                if not expected:
                    issues.append(f"audit_source_hash_missing:{chapter}:{name}")
                elif actual != expected:
                    issues.append(f"audited_artifact_hash_changed:{chapter}:{name}")
    snapshot = hashlib.sha256(
        json.dumps(bindings, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest() if bindings else None
    return {
        "status": "pass" if not issues else "blocked",
        "candidate_sha256": snapshot,
        "source_count": len(bindings),
        "issues": issues,
    }
