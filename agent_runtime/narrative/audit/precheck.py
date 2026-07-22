"""Deterministic candidate checks that must run before literary judges."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping, Any

import yaml


_TIMELINE_SLOT = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}(?:[T ][0-9:Z+.-]+)?|[A-Za-z_]+:\d+|T\d+(?:-[A-Z0-9_]+)+|[A-Za-z][A-Za-z0-9_]*_t\d+(?:_[A-Za-z0-9]+)+)$"
)
_CJK = re.compile(r"[\u3400-\u9fff]")
_LEGACY_TIME = re.compile(
    r"(?:第?[一二三四五六七八九十百零0-9]+(?:日|天|年|月|时|刻)|凌晨|清晨|正午|黄昏|夜|之后|之前|抵达)"
)


def _valid_timeline_slot(value: str) -> bool:
    if _TIMELINE_SLOT.fullmatch(value):
        return True
    return bool(
        value
        and len(value) <= 1000
        and "\n" not in value
        and _CJK.search(value)
        and _LEGACY_TIME.search(value)
    )


def candidate_manifest_from_audit_bundle(
    audit_manifest: Mapping[str, Any],
    *,
    source_root: Path,
) -> dict[str, object]:
    """Project a prepared audit bundle into the deterministic check schema."""
    root = Path(source_root).resolve()
    chapters: list[dict[str, object]] = []
    for source in audit_manifest.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        files = source.get("files")
        if not isinstance(files, Mapping):
            files = {}
        draft = files.get("fiction_draft.md")
        packet = files.get("chapter_packet.yml")
        ledger = files.get("continuity_ledger.yml")
        if not isinstance(draft, Mapping):
            draft = {}

        def read_mapping(record: object) -> dict[str, Any]:
            if not isinstance(record, Mapping) or not record.get("path"):
                return {}
            try:
                path = (root / str(record["path"])).resolve()
                path.relative_to(root)
                value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError, yaml.YAMLError):
                return {}
            return value if isinstance(value, dict) else {}

        packet_value = read_mapping(packet)
        ledger_value = read_mapping(ledger)
        chapter_intent = packet_value.get("chapter_intent")
        if not isinstance(chapter_intent, Mapping):
            chapter_intent = {}
        beat_plan = chapter_intent.get("beat_plan")
        if not isinstance(beat_plan, Mapping):
            beat_plan = {}
        timeline = ledger_value.get("timeline")
        if not isinstance(timeline, Mapping):
            timeline = {}
        timeline_slot = (
            chapter_intent.get("timeline_position")
            or timeline.get("timeline_position")
            or (
                f"chapter_day:{timeline['chapter_day']}"
                if timeline.get("chapter_day") is not None
                else None
            )
        )
        packet_timeline = chapter_intent.get("timeline_position")
        ledger_timeline = timeline.get("timeline_position")
        chapters.append(
            {
                "chapter_id": int(source.get("chapter") or 0),
                "artifact_path": str(draft.get("path") or ""),
                "artifact_sha256": str(draft.get("sha256") or ""),
                "pov": str(beat_plan.get("pov") or packet_value.get("pov") or ""),
                "timeline_slot": str(timeline_slot or ""),
                "timeline_consistent": bool(
                    timeline.get("monotonic") is True
                    and not (
                        packet_timeline
                        and ledger_timeline
                        and str(packet_timeline) != str(ledger_timeline)
                    )
                ),
            }
        )
    return {"manifest_version": 1, "chapters": chapters}


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

    paragraph_owners: dict[str, int] = {}
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
        if not _valid_timeline_slot(timeline):
            block("invalid_timeline_slot", chapter_id=chapter_id)
        if record.get("timeline_consistent") is False:
            block("inconsistent_timeline_metadata", chapter_id=chapter_id)
        text = artifact.read_text(encoding="utf-8", errors="replace")
        for paragraph in re.split(r"\n\s*\n", text):
            normalized = " ".join(paragraph.split()).strip()
            if len(normalized) < 80 or normalized.startswith("#"):
                continue
            paragraph_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            prior = paragraph_owners.get(paragraph_hash)
            if prior is None:
                paragraph_owners[paragraph_hash] = chapter_id
            else:
                block(
                    "duplicate_paragraph",
                    chapter_id=chapter_id,
                    detail=f"matches_chapter:{prior}",
                )

    blocking_codes = sorted({str(finding["code"]) for finding in findings})
    return {
        "schema_version": 1,
        "status": "blocked" if findings else "pass",
        "blocking_codes": blocking_codes,
        "findings": findings,
        "checked_chapters": sorted(by_chapter),
    }
