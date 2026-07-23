"""Deterministic assembly of hash-bound, audited narrative candidates."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any
import hashlib
import re

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


class NarrativeAssemblyError(RuntimeError):
    """Raised when audited candidates cannot be assembled safely."""


_ACCEPTED_AUDIT_STATUSES = {"completed", "pass", "passed"}
_RUNTIME_METADATA = re.compile(
    r"(?im)^\s*(?:task_id|run_id|worker|model|receipt|status|sha256)\s*:|AGENTLAB_EDIT"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_path(root: Path, project: str, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise NarrativeAssemblyError(f"unsafe candidate path: {relative!r}")
    path = (root / Path(*pure.parts)).resolve()
    runs_root = (root / "projects" / project / "runs").resolve()
    if runs_root not in path.parents:
        raise NarrativeAssemblyError(f"candidate is outside project runs: {relative}")
    return path


def _title(text: str, chapter: int) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    title = first.lstrip("#").strip()
    if not title or ("章" not in title and "chapter" not in title.lower()):
        raise NarrativeAssemblyError(f"chapter {chapter} has no chapter title")
    return title


def assemble_candidate_chapters(
    agentlab_root: Path,
    *,
    project: str,
    audit_manifest: Path,
    output_path: Path,
    delivery_manifest: Path,
) -> dict[str, Any]:
    """Assemble exactly the candidate bytes approved by one continuous audit."""
    root = Path(agentlab_root).resolve()
    audit_path = Path(audit_manifest).resolve()
    try:
        audit = yaml.safe_load(audit_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise NarrativeAssemblyError(f"cannot read audit manifest: {exc}") from exc
    if not isinstance(audit, dict):
        raise NarrativeAssemblyError("audit manifest must contain a mapping")
    if str(audit.get("project") or "") != project:
        raise NarrativeAssemblyError("audit project does not match assembly project")
    if str(audit.get("status") or "").lower() not in _ACCEPTED_AUDIT_STATUSES:
        raise NarrativeAssemblyError("continuous audit has not passed")
    if audit.get("candidate_only") is not True or audit.get("continuous_review") is not True:
        raise NarrativeAssemblyError("audit must be candidate-only and continuous")
    chapter_range = audit.get("chapter_range")
    if (
        not isinstance(chapter_range, list)
        or len(chapter_range) != 2
        or not all(isinstance(item, int) for item in chapter_range)
    ):
        raise NarrativeAssemblyError("audit chapter_range must be [start, end]")
    start, end = chapter_range
    expected = list(range(start, end + 1))
    raw_chapters = audit.get("chapters")
    if not isinstance(raw_chapters, list) or any(
        not isinstance(item, dict) for item in raw_chapters
    ):
        raise NarrativeAssemblyError("audit chapters must be a list of mappings")
    chapters = sorted(raw_chapters, key=lambda item: int(item.get("chapter") or 0))
    if [int(item.get("chapter") or 0) for item in chapters] != expected:
        raise NarrativeAssemblyError("audit chapters are missing, duplicated, or out of range")

    assembled: list[str] = []
    manifest_chapters: list[dict[str, Any]] = []
    titles: set[str] = set()
    for item in chapters:
        chapter = int(item["chapter"])
        relative = str(item.get("path") or "")
        path = _candidate_path(root, project, relative)
        expected_hash = str(item.get("sha256") or "")
        actual_hash = _sha256(path)
        if not expected_hash or actual_hash != expected_hash:
            raise NarrativeAssemblyError(f"chapter {chapter} candidate hash mismatch")
        text = path.read_text(encoding="utf-8").rstrip()
        if _RUNTIME_METADATA.search(text):
            raise NarrativeAssemblyError(f"chapter {chapter} contains runtime metadata")
        title = _title(text, chapter)
        if title in titles:
            raise NarrativeAssemblyError(f"duplicate chapter title: {title}")
        titles.add(title)
        assembled.append(text)
        manifest_chapters.append(
            {
                "chapter": chapter,
                "title": title,
                "task_id": str(item.get("task_id") or ""),
                "source_path": relative,
                "source_sha256": actual_hash,
            }
        )

    output = Path(output_path).resolve()
    production_root = (root / "projects" / project / "production").resolve()
    if output == production_root or production_root in output.parents:
        raise NarrativeAssemblyError("candidate assembly cannot write into production")
    content = "\n\n".join(assembled) + "\n"
    atomic_write_text(output, content)
    result = {
        "schema_version": 1,
        "status": "assembled",
        "project": project,
        "candidate_only": True,
        "chapter_range": [start, end],
        "chapter_count": len(manifest_chapters),
        "output_path": str(output),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "audit_manifest": str(audit_path),
        "audit_manifest_sha256": _sha256(audit_path),
        "chapters": manifest_chapters,
    }
    atomic_write_yaml(Path(delivery_manifest).resolve(), result)
    return result
