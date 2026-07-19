"""Deterministic candidate checks that must run before literary judges."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping, Any


_TIMELINE_SLOT = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}(?:[T ][0-9:Z+.-]+)?|[A-Za-z_]+:\d+)$"
)


def run_deterministic_precheck(
    candidate_manifest: Mapping[str, Any],
    *,
    source_root: Path,
    required_chapters: Iterable[int],
    expected_manifest_version: int,
) -> dict[str, object]:
    """Validate candidate identity and cheap structural invariants."""
    root = Path(source_root).resolve()
    findings: list[dict[str, object]] = []

    def block(code: str, *, chapter_id: int | None = None, detail: str = "") -> None:
        finding: dict[str, object] = {"code": code, "severity": "blocking"}
        if chapter_id is not None:
            finding["chapter_id"] = chapter_id
        if detail:
            finding["detail"] = detail
        findings.append(finding)

    if int(candidate_manifest.get("manifest_version") or 0) != int(
        expected_manifest_version
    ):
        block("invalid_manifest_version")

    records = candidate_manifest.get("chapters")
    if not isinstance(records, list):
        records = []
    by_chapter: dict[int, Mapping[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("chapter_id"), int):
            block("invalid_chapter_record")
            continue
        chapter_id = int(raw["chapter_id"])
        if chapter_id in by_chapter:
            block("duplicate_chapter", chapter_id=chapter_id)
            continue
        by_chapter[chapter_id] = raw

    for chapter_id in sorted(set(int(chapter) for chapter in required_chapters)):
        if chapter_id not in by_chapter:
            block("missing_chapter", chapter_id=chapter_id)

    for chapter_id, record in sorted(by_chapter.items()):
        path_value = record.get("artifact_path")
        if not isinstance(path_value, str) or not path_value:
            block("missing_artifact", chapter_id=chapter_id)
            continue
        try:
            artifact = (root / path_value).resolve()
            artifact.relative_to(root)
        except ValueError:
            block("unsafe_artifact_path", chapter_id=chapter_id)
            continue
        if not artifact.is_file():
            block("missing_artifact", chapter_id=chapter_id)
            continue
        actual_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if record.get("artifact_sha256") != actual_hash:
            block("artifact_hash_mismatch", chapter_id=chapter_id)
        if not str(record.get("pov") or "").strip():
            block("missing_pov", chapter_id=chapter_id)
        timeline = str(record.get("timeline_slot") or "")
        if not _TIMELINE_SLOT.fullmatch(timeline):
            block("invalid_timeline_slot", chapter_id=chapter_id)

    blocking_codes = sorted({str(finding["code"]) for finding in findings})
    return {
        "schema_version": 1,
        "status": "blocked" if findings else "pass",
        "blocking_codes": blocking_codes,
        "findings": findings,
        "checked_chapters": sorted(by_chapter),
    }
