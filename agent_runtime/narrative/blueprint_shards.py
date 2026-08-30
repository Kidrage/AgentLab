"""Bounded, resumable chapter-blueprint sharding primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from collections.abc import Mapping, Sequence

import yaml

from agent_runtime.outbound_context import is_forbidden_source_path
from agent_runtime.task_runtime_v2.runtime import TaskRuntime


_CHAPTER_HEADING = re.compile(r"(?m)^## C(\d{3})(?:[ \t]+([^\r\n]+))?[ \t]*$")
_SHARD_CHEVRON_START = re.compile(
    r"(?m)^(?P<left><{3,8})[ \t]*AGENTLAB_EDIT"
    r"(?P<meta>[^<>\r\n]*?)(?P<right>>{3,8})?[ \t]*$"
)
_SHARD_CHEVRON_METADATA = re.compile(
    r"(?:|candidate|:[ \t]*[A-Za-z0-9_.-]+|"
    r"(?:(?:candidate|candidate_id|artifact_id|target_id)(?:=|:[ \t]*)"
    r"[A-Za-z0-9_.-]+)"
    r"(?:[ \t]+(?:candidate|candidate_id|artifact_id|target_id)(?:=|:[ \t]*)"
    r"[A-Za-z0-9_.-]+)*)"
)
_SHARD_HTML_START = re.compile(
    r"(?m)^<!--[ \t]*(?:(?:BEGIN|START)[ \t]+AGENTLAB_EDIT\b|"
    r"AGENTLAB_EDIT(?![ \t]*:[ \t]*END\b|_END\b))[^>\r\n]*-->[ \t]*$"
)
_SHARD_MARKDOWN_START = re.compile(r"(?m)^```[ \t]*AGENTLAB_EDIT\b[^\r\n]*$")
_SHARD_XML_START = re.compile(r"(?m)^<AGENTLAB_EDIT(?:[ \t][^>\r\n]*)?>[ \t]*$")
_SHARD_PROVIDER_TRAILER = re.compile(
    r"(?m)^(?:##[ \t]+stderr\b|#[ \t]+Writer Report\b)"
)
_REQUIRED_CARD_FIELDS = ("objective", "conflict", "turn", "consequence", "promise")


@dataclass(frozen=True, slots=True)
class BlueprintShard:
    """One volume-sized, contiguous chapter blueprint shard."""

    volume_id: str
    start_chapter: int
    end_chapter: int

    @property
    def chapters(self) -> range:
        return range(self.start_chapter, self.end_chapter + 1)


def build_blueprint_shard_plan(
    *, total_chapters: int, volume_count: int
) -> tuple[BlueprintShard, ...]:
    """Return an exact equal-volume partition of ``total_chapters``."""

    if total_chapters <= 0 or volume_count <= 0:
        raise ValueError("chapter and volume counts must be positive")
    if total_chapters % volume_count:
        raise ValueError("chapters must divide evenly across volumes")
    chapters_per_volume = total_chapters // volume_count
    return tuple(
        BlueprintShard(
            volume_id=f"V{volume:02d}",
            start_chapter=(volume - 1) * chapters_per_volume + 1,
            end_chapter=volume * chapters_per_volume,
        )
        for volume in range(1, volume_count + 1)
    )


def split_blueprint_shard(
    shard: BlueprintShard, *, max_chapters: int
) -> tuple[BlueprintShard, ...]:
    """Split one volume into bounded generation segments without changing its identity."""

    if max_chapters <= 0:
        raise ValueError("max chapters per generation must be positive")
    return tuple(
        BlueprintShard(
            volume_id=shard.volume_id,
            start_chapter=start,
            end_chapter=min(start + max_chapters - 1, shard.end_chapter),
        )
        for start in range(shard.start_chapter, shard.end_chapter + 1, max_chapters)
    )


def validate_blueprint_shard(
    shard: BlueprintShard,
    text: str,
    *,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
    strict_fields: bool = False,
) -> tuple[str, ...]:
    """Validate exact chapter coverage and the compact chapter-card contract."""

    matches = list(_CHAPTER_HEADING.finditer(text))
    observed = [int(match.group(1)) for match in matches]
    expected = list(shard.chapters)
    issues: list[str] = []
    missing = [chapter for chapter in expected if chapter not in observed]
    unexpected = [chapter for chapter in observed if chapter not in expected]
    duplicates = sorted(
        {chapter for chapter in observed if observed.count(chapter) > 1}
    )
    if missing:
        issues.append(
            "missing chapters: " + ", ".join(f"C{item:03d}" for item in missing)
        )
    if unexpected:
        issues.append(
            "out-of-range chapters: " + ", ".join(f"C{item:03d}" for item in unexpected)
        )
    if duplicates:
        issues.append(
            "duplicate chapters: " + ", ".join(f"C{item:03d}" for item in duplicates)
        )
    for index, match in enumerate(matches):
        chapter = int(match.group(1))
        if chapter not in shard.chapters:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        card = text[match.end() : end]
        if strict_fields:
            observed_fields: list[str] = []
            unexpected_lines: list[str] = []
            for line in card.splitlines():
                if not line.strip():
                    continue
                field_match = re.fullmatch(r"- ([A-Za-z][A-Za-z0-9_]*):\s*\S.*", line)
                if field_match is None:
                    unexpected_lines.append(line)
                    continue
                observed_fields.append(field_match.group(1))
            if tuple(observed_fields) != tuple(required_fields):
                issues.append(
                    f"C{chapter:03d} field contract mismatch: "
                    + ", ".join(observed_fields)
                )
            if unexpected_lines:
                issues.append(f"C{chapter:03d} contains undeclared card content")
        for field in required_fields:
            if not re.search(rf"(?m)^- {re.escape(field)}:\s*\S", card):
                issues.append(f"C{chapter:03d} missing field: {field}")
        if "chapter_id" in required_fields:
            chapter_id_match = re.search(r"(?m)^- chapter_id:\s*(\S+)\s*$", card)
            if chapter_id_match and chapter_id_match.group(1) != f"C{chapter:03d}":
                issues.append(
                    f"C{chapter:03d} chapter_id mismatch: {chapter_id_match.group(1)}"
                )
        if "title" in required_fields:
            title_match = re.search(r"(?m)^- title:\s*(\S.*?)\s*$", card)
            heading_title = (match.group(2) or "").strip()
            if title_match and title_match.group(1).strip() != heading_title:
                issues.append(
                    f"C{chapter:03d} title mismatch: {title_match.group(1).strip()}"
                )
        if "volume" in required_fields:
            volume_match = re.search(r"(?m)^- volume:\s*(\S+)\s*$", card)
            if volume_match and volume_match.group(1) != shard.volume_id:
                issues.append(
                    f"C{chapter:03d} volume mismatch: {volume_match.group(1)}"
                )
    return tuple(issues)


def extract_blueprint_shard_cards(
    shard: BlueprintShard,
    text: str,
    *,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
) -> str:
    """Return only the validated chapter-card payload from a provider envelope."""

    matches = list(_CHAPTER_HEADING.finditer(text))
    if not matches:
        raise ValueError(f"invalid blueprint shard {shard.volume_id}: no chapter cards")
    start = matches[0].start()
    search_start = matches[-1].end()
    trailer_candidates = [
        match
        for match in (_SHARD_PROVIDER_TRAILER.search(text, search_start),)
        if match is not None
    ]
    chevron_starts = [
        match
        for match in _SHARD_CHEVRON_START.finditer(text, 0, start)
        if (
            (
                not match.group("right")
                or len(match.group("left")) == len(match.group("right"))
            )
            and _SHARD_CHEVRON_METADATA.fullmatch(match.group("meta").strip())
        )
    ]
    if chevron_starts:
        opener = chevron_starts[-1]
        left_width = len(opener.group("left"))
        right_width = len(opener.group("right") or "") or left_width
        for pattern in (
            rf"(?m)^>{{{left_width}}}[ \t]*$",
            rf"(?m)^>{{{left_width}}}[ \t]*AGENTLAB_EDIT[ \t]*$",
            rf"(?m)^>{{{left_width}}}[ \t]*AGENTLAB_EDIT[ \t]+candidate[ \t]*$",
            rf"(?m)^<{{{left_width}}}[ \t]*END_AGENTLAB_EDIT[ \t]*>{{{right_width}}}[ \t]*$",
            rf"(?m)^>{{{left_width}}}[ \t]*END_AGENTLAB_EDIT[ \t]*>{{{right_width}}}[ \t]*$",
        ):
            match = re.compile(pattern).search(text, search_start)
            if match is not None:
                trailer_candidates.append(match)
    if _SHARD_HTML_START.search(text, 0, start):
        html_trailer = re.compile(
            r"(?m)^<!--[ \t]*(?:/[ \t]*AGENTLAB_EDIT|END[ \t]+AGENTLAB_EDIT\b[^>\r\n]*|"
            r"AGENTLAB_EDIT(?::[ \t]*END\b[^>\r\n]*|_END\b[^>\r\n]*))"
            r"[ \t]*-->[ \t]*$"
        ).search(text, search_start)
        if html_trailer is not None:
            trailer_candidates.append(html_trailer)
    if _SHARD_MARKDOWN_START.search(text, 0, start):
        markdown_trailer = re.compile(
            r"(?m)^```[ \t]*$(?=\r?\n(?:[ \t]*\r?\n)*##[ \t]+stderr\b)"
        ).search(text, search_start)
        if markdown_trailer is not None:
            trailer_candidates.append(markdown_trailer)
    if _SHARD_XML_START.search(text, 0, start):
        xml_trailer = re.compile(r"(?m)^</AGENTLAB_EDIT>[ \t]*$").search(
            text, search_start
        )
        if xml_trailer is not None:
            trailer_candidates.append(xml_trailer)
    trailer = min(trailer_candidates, key=lambda match: match.start(), default=None)
    end = trailer.start() if trailer is not None else len(text)
    payload = text[start:end].strip()
    normalized = payload + "\n"
    issues = validate_blueprint_shard(
        shard,
        normalized,
        required_fields=required_fields,
        strict_fields=True,
    )
    if issues:
        raise ValueError(
            f"invalid blueprint shard {shard.volume_id}: {'; '.join(issues)}"
        )
    return normalized


def assemble_blueprint_volume_segments(
    volume: BlueprintShard,
    segments: Sequence[BlueprintShard],
    outputs: Mapping[tuple[int, int], str],
    *,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
    semantic_contract: Mapping[str, object] | None = None,
) -> str:
    """Reassemble bounded generation segments as one validated volume shard."""

    ordered = tuple(segments)
    observed_chapters = [chapter for segment in ordered for chapter in segment.chapters]
    if (
        not ordered
        or any(segment.volume_id != volume.volume_id for segment in ordered)
        or observed_chapters != list(volume.chapters)
    ):
        raise ValueError(f"generation segments do not exactly cover {volume.volume_id}")
    payloads: list[str] = []
    for segment in ordered:
        key = (segment.start_chapter, segment.end_chapter)
        if key not in outputs:
            raise ValueError(
                f"missing generation segment C{segment.start_chapter:03d}-"
                f"C{segment.end_chapter:03d}"
            )
        payloads.append(
            extract_blueprint_shard_cards(
                segment, outputs[key], required_fields=required_fields
            ).strip()
        )
    assembled = "\n\n".join(payloads).strip() + "\n"
    issues = validate_blueprint_shard(
        volume,
        assembled,
        required_fields=required_fields,
        strict_fields=True,
    )
    issues += validate_blueprint_shard_semantics(
        volume, assembled, semantic_contract or {}
    )
    if issues:
        raise ValueError(
            f"invalid assembled blueprint volume {volume.volume_id}: "
            + "; ".join(issues)
        )
    return assembled


def assemble_blueprint_shards(
    plan: Sequence[BlueprintShard],
    outputs: Mapping[str, str],
    *,
    title: str,
    protocol_ref: str,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
) -> str:
    """Deterministically assemble only complete, valid shards."""

    if not plan:
        raise ValueError("blueprint shard plan is empty")
    sections = [
        f"# {title}：{sum(len(item.chapters) for item in plan)}章故事蓝本",
        "",
        f"blueprint_protocol: {protocol_ref}",
        "chapter_card_contract: " + "/".join(required_fields),
        "",
    ]
    for shard in plan:
        if shard.volume_id not in outputs:
            raise ValueError(f"missing blueprint shard: {shard.volume_id}")
        raw_text = outputs[shard.volume_id]
        text = extract_blueprint_shard_cards(
            shard, raw_text, required_fields=required_fields
        ).strip()
        sections.extend(
            [
                f"# {shard.volume_id} C{shard.start_chapter:03d}-C{shard.end_chapter:03d}",
                "",
                text,
                "",
            ]
        )
    assembled = "\n".join(sections).rstrip() + "\n"
    observed = [int(match.group(1)) for match in _CHAPTER_HEADING.finditer(assembled)]
    expected = [chapter for shard in plan for chapter in shard.chapters]
    if observed != expected:
        raise ValueError("assembled blueprint chapter order is incomplete")
    return assembled


def validate_blueprint_shard_semantics(
    shard: BlueprintShard,
    text: str,
    contract: Mapping[str, object],
) -> tuple[str, ...]:
    """Apply deterministic must-contain/must-not-contain checks to one shard."""

    issues: list[str] = []
    required_text = "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith("- forbidden_early_payoffs:")
    )
    for phrase in contract.get("required_phrases") or []:
        normalized = str(phrase).strip()
        if normalized and normalized not in required_text:
            issues.append(f"{shard.volume_id} missing required phrase: {normalized}")
    for phrase in contract.get("forbidden_phrases") or []:
        normalized = str(phrase).strip()
        if normalized and normalized in text:
            issues.append(f"{shard.volume_id} contains forbidden phrase: {normalized}")
    chapter_rules = contract.get("chapter_rules") or {}
    if not isinstance(chapter_rules, Mapping):
        return (*issues, f"{shard.volume_id} chapter_rules must be a mapping")
    matches = list(_CHAPTER_HEADING.finditer(text))
    cards: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        cards[f"C{int(match.group(1)):03d}"] = text[match.start() : end]
    for raw_chapter_id, raw_rule in chapter_rules.items():
        chapter_id = str(raw_chapter_id).strip()
        if chapter_id not in cards:
            issues.append(
                f"{shard.volume_id} chapter rule target missing: {chapter_id}"
            )
            continue
        if not isinstance(raw_rule, Mapping):
            issues.append(f"{chapter_id} semantic rule must be a mapping")
            continue
        card_text = cards[chapter_id]
        required_card_text = "\n".join(
            line
            for line in card_text.splitlines()
            if not line.startswith("- forbidden_early_payoffs:")
        )
        for phrase in raw_rule.get("required_phrases") or []:
            normalized = str(phrase).strip()
            if normalized and normalized not in required_card_text:
                issues.append(f"{chapter_id} missing required phrase: {normalized}")
        for phrase in raw_rule.get("forbidden_phrases") or []:
            normalized = str(phrase).strip()
            if normalized and normalized in card_text:
                issues.append(f"{chapter_id} contains forbidden phrase: {normalized}")
    return tuple(issues)


def _segment_semantic_contract(
    segment: BlueprintShard,
    contract: Mapping[str, object],
) -> dict[str, object]:
    """Return only rules that can be decided from one bounded generation segment."""

    scoped = dict(contract)
    scoped.pop("required_phrases", None)
    chapter_rules = contract.get("chapter_rules") or {}
    if isinstance(chapter_rules, Mapping):
        scoped["chapter_rules"] = {
            str(chapter_id): dict(rule)
            for chapter_id, rule in chapter_rules.items()
            if isinstance(rule, Mapping)
            and (match := re.fullmatch(r"C(\d{3})", str(chapter_id).strip()))
            and int(match.group(1)) in segment.chapters
        }
    return scoped


def _utf8_prefix(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _materialize_content_addressed_text(
    directory: Path,
    *,
    stem: str,
    text: str,
    suffix: str,
    boundary: Path | None = None,
) -> tuple[Path, str]:
    """Write immutable text under a content-addressed name and verify re-entry."""

    payload = text.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-.") or "payload"
    path = directory / f"{safe_stem}-{digest}{suffix}"
    directory_fd = _open_bounded_directory(
        boundary or directory, directory, create=True
    )
    try:
        _atomic_write_or_verify_at(directory_fd, path.name, payload)
        observed = _read_regular_file_at(directory_fd, path.name)
    finally:
        os.close(directory_fd)
    if hashlib.sha256(observed).hexdigest() != digest:
        raise ValueError("content-addressed blueprint input hash mismatch")
    return path, digest


def _materialize_content_addressed_yaml(
    directory: Path,
    *,
    stem: str,
    payload: Mapping[str, object],
    boundary: Path | None = None,
) -> tuple[Path, str]:
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    return _materialize_content_addressed_text(
        directory, stem=stem, text=text, suffix=".yml", boundary=boundary
    )


def _open_bounded_directory(boundary: Path, directory: Path, *, create: bool) -> int:
    lexical_boundary = boundary.absolute()
    lexical_directory = directory.absolute()
    try:
        relative = lexical_directory.relative_to(lexical_boundary)
    except ValueError as exc:
        raise ValueError("blueprint evidence directory escaped its Task") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lexical_boundary, flags)
        for part in relative.parts:
            if part in {"", ".", ".."} or Path(part).name != part:
                raise ValueError("blueprint evidence path component is invalid")
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise ValueError(
            "blueprint evidence ancestry contains a symlink or invalid directory"
        ) from exc
    except ValueError:
        if "descriptor" in locals():
            os.close(descriptor)
        raise


def _read_regular_file_at(directory_fd: int, leaf: str) -> bytes:
    if Path(leaf).name != leaf or not leaf:
        raise ValueError("blueprint evidence leaf is invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(leaf, flags, dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("blueprint evidence is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_write_or_verify_at(directory_fd: int, leaf: str, content: bytes) -> None:
    try:
        observed = _read_regular_file_at(directory_fd, leaf)
    except FileNotFoundError:
        observed = None
    if observed is not None:
        if observed != content:
            raise ValueError("content-addressed blueprint input has drifted")
        return
    temporary = f".{leaf}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        try:
            os.link(
                temporary,
                leaf,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if _read_regular_file_at(directory_fd, leaf) != content:
                raise ValueError("content-addressed blueprint input has drifted")
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _read_bounded_regular_file(
    candidate: Path, *, boundary: Path
) -> tuple[Path, bytes] | None:
    """Read one file only when every lexical component stays regular and bounded."""

    lexical_boundary = boundary.absolute()
    lexical_candidate = candidate.absolute()
    try:
        relative = lexical_candidate.relative_to(lexical_boundary)
        if not relative.parts:
            return None
        directory_fd = _open_bounded_directory(
            lexical_boundary,
            lexical_candidate.parent,
            create=False,
        )
        try:
            payload = _read_regular_file_at(directory_fd, lexical_candidate.name)
        finally:
            os.close(directory_fd)
        return lexical_candidate, payload
    except (OSError, ValueError):
        return None


def build_blueprint_segment_context_projection(
    *,
    task_id: str,
    revision: int,
    segment: BlueprintShard,
    sources: Sequence[Mapping[str, object]],
    max_bytes_per_source: int = 8192,
) -> dict[str, object]:
    """Build a bounded, source-hash-bound context projection for one segment."""

    if max_bytes_per_source < 512:
        raise ValueError("segment context source budget must be at least 512 bytes")
    chapter_tokens = {f"C{chapter:03d}" for chapter in segment.chapters}
    volume_number = int(segment.volume_id[1:])
    volume_tokens = {
        segment.volume_id,
        f"Vol {volume_number}",
        f"Vol {volume_number:02d}",
        f"volume {volume_number}",
        f"卷{volume_number}",
    }
    projected_sources: list[dict[str, object]] = []
    for source in sources:
        artifact_type = str(source.get("artifact_type") or "").strip()
        source_path = str(source.get("path") or "").strip()
        source_sha256 = str(source.get("sha256") or "").strip()
        source_text = source.get("text")
        if (
            not artifact_type
            or not source_path
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
            or not isinstance(source_text, str)
        ):
            raise ValueError("segment context source is malformed")
        lines = source_text.splitlines()
        relevant_indices: set[int] = set()
        tokens = chapter_tokens | volume_tokens
        for index, line in enumerate(lines):
            if any(token in line for token in tokens):
                relevant_indices.update(
                    range(max(0, index - 6), min(len(lines), index + 7))
                )
        relevant = "\n".join(lines[index] for index in sorted(relevant_indices))
        global_anchor = "\n".join(lines[:64])
        relevant_budget = (max_bytes_per_source * 2) // 3
        relevant_excerpt = _utf8_prefix(relevant, relevant_budget)
        prefix = "[segment-relevant]\n" + relevant_excerpt + "\n[global-anchor]\n"
        remaining = max_bytes_per_source - len(prefix.encode("utf-8"))
        if remaining < 0:
            excerpt = _utf8_prefix(prefix, max_bytes_per_source)
        else:
            excerpt = prefix + _utf8_prefix(global_anchor, remaining)
        excerpt = excerpt.rstrip() + "\n"
        if len(excerpt.encode("utf-8")) > max_bytes_per_source:
            excerpt = _utf8_prefix(excerpt, max_bytes_per_source)
        projected_sources.append(
            {
                "artifact_type": artifact_type,
                "source_path": source_path,
                "source_sha256": source_sha256,
                "source_size_bytes": len(source_text.encode("utf-8")),
                "excerpt": excerpt,
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "excerpt_size_bytes": len(excerpt.encode("utf-8")),
                "truncated": len(excerpt.encode("utf-8"))
                < len(source_text.encode("utf-8")),
            }
        )
    return {
        "schema_version": "narrative-blueprint-segment-context/v1",
        "task_id": task_id,
        "revision": revision,
        "volume_id": segment.volume_id,
        "chapter_range": [segment.start_chapter, segment.end_chapter],
        "max_bytes_per_source": max_bytes_per_source,
        "source_count": len(projected_sources),
        "sources": projected_sources,
    }


def build_blueprint_generation_contract_sha256(
    *,
    task_id: str,
    revision: int,
    segment: BlueprintShard,
    context_manifest_sha256: str,
    segment_context_sha256: str,
    governed_source_manifest_sha256: str,
    semantic_contract: Mapping[str, object],
    required_fields: Sequence[str],
) -> str:
    """Seal the exact inputs that make one generated segment reusable."""

    payload = {
        "schema_version": "narrative-blueprint-generation-contract/v1",
        "task_id": task_id,
        "revision": revision,
        "volume_id": segment.volume_id,
        "chapter_range": [segment.start_chapter, segment.end_chapter],
        "context_manifest_sha256": context_manifest_sha256,
        "segment_context_sha256": segment_context_sha256,
        "governed_source_manifest_sha256": governed_source_manifest_sha256,
        "semantic_contract": dict(semantic_contract),
        "required_fields": list(required_fields),
    }
    serialized = yaml.safe_dump(payload, allow_unicode=True, sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(serialized).hexdigest()


def validated_blueprint_attempt_output(
    *,
    task_root: Path,
    attempts: Mapping[str, object],
    attempt_id: str,
    target: BlueprintShard,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
    semantic_contract: Mapping[str, object] | None = None,
    expected_context_manifest_sha256: str | None = None,
    expected_generation_contract_sha256: str | None = None,
) -> str | None:
    """Return one validated output only when its immutable evidence still matches."""

    attempt = attempts.get(attempt_id)
    output_path = task_root / "attempt_logs" / attempt_id / "output.md"
    output_snapshot = _read_bounded_regular_file(output_path, boundary=task_root)
    if (
        not isinstance(attempt, Mapping)
        or attempt.get("status") != "succeeded"
        or (attempt.get("output_validation") or {}).get("status") != "pass"
        or output_snapshot is None
    ):
        return None
    output_bytes = output_snapshot[1]
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    expected_output_sha256 = str(
        (attempt.get("outcome") or {}).get("output_sha256") or ""
    )
    validation = attempt.get("output_validation") or {}
    if (
        not expected_output_sha256
        or output_sha256 != expected_output_sha256
        or validation.get("output_sha256") != output_sha256
    ):
        return None
    receipt_path_text = str(validation.get("receipt_path") or "")
    if not receipt_path_text:
        return None
    receipt_candidate = task_root / receipt_path_text
    attempt_root = (task_root / "attempt_logs" / attempt_id).absolute()
    try:
        receipt_snapshot = _read_bounded_regular_file(
            receipt_candidate, boundary=task_root
        )
        if receipt_snapshot is None:
            return None
        receipt_path, receipt_bytes = receipt_snapshot
        if not receipt_path.is_relative_to(attempt_root):
            return None
        if hashlib.sha256(receipt_bytes).hexdigest() != str(
            validation.get("receipt_sha256") or ""
        ):
            return None
        receipt = yaml.safe_load(receipt_bytes.decode("utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(receipt, Mapping) or any(
        (
            receipt.get("schema_version") != "protocol-artifact-validation/v1",
            receipt.get("status") != "pass",
            receipt.get("attempt_id") != attempt_id,
            receipt.get("output_sha256") != output_sha256,
            expected_context_manifest_sha256 is not None
            and receipt.get("context_manifest_sha256")
            != expected_context_manifest_sha256,
            expected_generation_contract_sha256 is not None
            and receipt.get("generation_contract_sha256")
            != expected_generation_contract_sha256,
        )
    ):
        return None
    try:
        candidate = extract_blueprint_shard_cards(
            target,
            output_bytes.decode("utf-8"),
            required_fields=required_fields,
        )
    except (UnicodeDecodeError, ValueError):
        return None
    if validate_blueprint_shard_semantics(target, candidate, semantic_contract or {}):
        return None
    return candidate


def validated_legacy_blueprint_attempt_output(
    *,
    task_root: Path,
    attempts: Mapping[str, object],
    attempt_id: str,
    target: BlueprintShard,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
    semantic_contract: Mapping[str, object] | None = None,
) -> tuple[str, dict[str, object]] | None:
    """Derive an explicitly described numeric-volume compatibility transform."""

    attempt = attempts.get(attempt_id)
    output_path = task_root / "attempt_logs" / attempt_id / "output.md"
    output_snapshot = _read_bounded_regular_file(output_path, boundary=task_root)
    if (
        not isinstance(attempt, Mapping)
        or attempt.get("status") != "succeeded"
        or (attempt.get("output_validation") or {}).get("status") != "pass"
        or output_snapshot is None
    ):
        return None
    output_bytes = output_snapshot[1]
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    outcome_sha256 = str((attempt.get("outcome") or {}).get("output_sha256") or "")
    validation = attempt.get("output_validation") or {}
    validation_sha256 = str(validation.get("output_sha256") or "")
    if (
        outcome_sha256 != output_sha256
        or validation_sha256 != output_sha256
        or not validation.get("receipt_path")
    ):
        return None
    receipt_candidate = task_root / str(validation["receipt_path"])
    receipt_snapshot = _read_bounded_regular_file(receipt_candidate, boundary=task_root)
    if receipt_snapshot is None:
        return None
    receipt_path, receipt_bytes = receipt_snapshot
    attempt_root = (task_root / "attempt_logs" / attempt_id).absolute()
    if not receipt_path.is_relative_to(attempt_root) or hashlib.sha256(
        receipt_bytes
    ).hexdigest() != str(validation.get("receipt_sha256") or ""):
        return None
    try:
        receipt = yaml.safe_load(receipt_bytes.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(receipt, Mapping) or any(
        (
            receipt.get("schema_version") != "protocol-artifact-validation/v1",
            receipt.get("status") != "pass",
            receipt.get("attempt_id") != attempt_id,
            receipt.get("output_sha256") != output_sha256,
        )
    ):
        return None
    try:
        output_text = output_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    numeric_volume = str(int(target.volume_id[1:]))
    transformed_text, replacement_count = re.subn(
        rf"(?m)^- volume:\s*{re.escape(numeric_volume)}\s*$",
        f"- volume: {target.volume_id}",
        output_text,
    )
    if replacement_count != len(target.chapters):
        return None
    try:
        candidate = extract_blueprint_shard_cards(
            target,
            transformed_text,
            required_fields=required_fields,
        )
    except ValueError:
        return None
    if validate_blueprint_shard_semantics(target, candidate, semantic_contract or {}):
        return None
    return candidate, {
        "kind": "historical_numeric_volume_to_canonical_id",
        "field": "volume",
        "from": numeric_volume,
        "to": target.volume_id,
        "replacement_count": replacement_count,
        "source_output_sha256": output_sha256,
        "transformed_output_sha256": hashlib.sha256(
            candidate.encode("utf-8")
        ).hexdigest(),
    }


def blueprint_composite_matches(
    *,
    task_root: Path,
    attempt_id: str,
    attempt: Mapping[str, object],
    expected_child_attempt_ids: Sequence[str],
    expected_output_sha256: str,
    expected_context_manifest_sha256: str,
    expected_legacy_transform_receipts: Sequence[Mapping[str, str]] = (),
) -> bool:
    """Verify that an existing deterministic assembly is exactly this assembly."""

    outcome = attempt.get("outcome") or {}
    output_path = task_root / "attempt_logs" / attempt_id / "output.md"
    output_snapshot = _read_bounded_regular_file(output_path, boundary=task_root)
    if (
        attempt.get("status") != "succeeded"
        or list(outcome.get("composite_child_attempt_ids") or [])
        != list(expected_child_attempt_ids)
        or output_snapshot is None
    ):
        return False
    output_bytes = output_snapshot[1]
    if (
        hashlib.sha256(output_bytes).hexdigest() != expected_output_sha256
        or outcome.get("output_sha256") != expected_output_sha256
    ):
        return False
    validation = attempt.get("output_validation")
    if validation is None:
        return False
    if not isinstance(validation, Mapping) or validation.get("status") != "pass":
        return False
    receipt_candidate = task_root / str(validation.get("receipt_path") or "")
    attempt_root = task_root / "attempt_logs" / attempt_id
    try:
        receipt_snapshot = _read_bounded_regular_file(
            receipt_candidate, boundary=task_root
        )
        if receipt_snapshot is None:
            return False
        receipt_path, receipt_bytes = receipt_snapshot
        if not receipt_path.is_relative_to(attempt_root.resolve(strict=True)):
            return False
        if hashlib.sha256(receipt_bytes).hexdigest() != str(
            validation.get("receipt_sha256") or ""
        ):
            return False
        receipt = yaml.safe_load(receipt_bytes.decode("utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    return isinstance(receipt, Mapping) and all(
        (
            receipt.get("schema_version") == "protocol-artifact-validation/v1",
            receipt.get("status") == "pass",
            receipt.get("attempt_id") == attempt_id,
            receipt.get("context_manifest_sha256") == expected_context_manifest_sha256,
            list(receipt.get("child_attempt_ids") or [])
            == list(expected_child_attempt_ids),
            receipt.get("output_sha256") == expected_output_sha256,
            list(receipt.get("legacy_transform_receipts") or [])
            == [dict(item) for item in expected_legacy_transform_receipts],
        )
    )


def find_reusable_blueprint_shard_attempts(
    *,
    task_root: Path,
    attempts: Mapping[str, object],
    shard: BlueprintShard,
    baseline_revision: int,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
    semantic_contract: Mapping[str, object] | None = None,
) -> tuple[str, ...] | None:
    """Find baseline attempts that still assemble under current contracts."""

    baseline_attempt_id = f"attempt-writer-assembled-{baseline_revision:03d}"
    baseline_attempt = attempts.get(baseline_attempt_id)
    if not isinstance(baseline_attempt, Mapping):
        return None
    if (
        baseline_attempt.get("status") != "succeeded"
        or (baseline_attempt.get("output_validation") or {}).get("status") != "pass"
    ):
        return None
    child_attempt_ids = (baseline_attempt.get("outcome") or {}).get(
        "composite_child_attempt_ids"
    )
    if not isinstance(child_attempt_ids, list):
        return None
    candidate_ids = [
        str(raw_attempt_id or "")
        for raw_attempt_id in child_attempt_ids
        if f"-{shard.volume_id.lower()}-" in str(raw_attempt_id or "")
    ]
    candidates: list[tuple[BlueprintShard, str, str]] = []
    for attempt_id in candidate_ids:
        attempt = attempts.get(attempt_id)
        if not isinstance(attempt, Mapping):
            continue
        output_path = task_root / "attempt_logs" / str(attempt_id) / "output.md"
        output_snapshot = _read_bounded_regular_file(output_path, boundary=task_root)
        try:
            output_text = output_snapshot[1].decode("utf-8") if output_snapshot else ""
        except UnicodeDecodeError:
            output_text = ""
        if (
            attempt.get("status") != "succeeded"
            or (attempt.get("output_validation") or {}).get("status") != "pass"
            or not output_text
        ):
            continue
        observed = [
            int(match.group(1)) for match in _CHAPTER_HEADING.finditer(output_text)
        ]
        if not observed or any(chapter not in shard.chapters for chapter in observed):
            continue
        segment = BlueprintShard(
            volume_id=shard.volume_id,
            start_chapter=min(observed),
            end_chapter=max(observed),
        )
        segment_contract = _segment_semantic_contract(
            segment,
            semantic_contract or {},
        )
        candidate_text = validated_blueprint_attempt_output(
            task_root=task_root,
            attempts=attempts,
            attempt_id=attempt_id,
            target=segment,
            required_fields=required_fields,
            semantic_contract=segment_contract,
        )
        if candidate_text is None:
            legacy = validated_legacy_blueprint_attempt_output(
                task_root=task_root,
                attempts=attempts,
                attempt_id=attempt_id,
                target=segment,
                required_fields=required_fields,
                semantic_contract=segment_contract,
            )
            if legacy is None:
                continue
            candidate_text = legacy[0]
        candidates.append((segment, str(attempt_id), candidate_text))
    candidates.sort(key=lambda item: item[0].start_chapter)
    try:
        assemble_blueprint_volume_segments(
            shard,
            [item[0] for item in candidates],
            {
                (item[0].start_chapter, item[0].end_chapter): item[2]
                for item in candidates
            },
            required_fields=required_fields,
            semantic_contract=semantic_contract,
        )
    except ValueError:
        return None
    return tuple(item[1] for item in candidates)


def find_reusable_blueprint_shard_attempt(
    *,
    task_root: Path,
    attempts: Mapping[str, object],
    shard: BlueprintShard,
    baseline_revision: int,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
    semantic_contract: Mapping[str, object] | None = None,
) -> str | None:
    """Compatibility helper for callers that require one whole-volume attempt."""

    reusable = find_reusable_blueprint_shard_attempts(
        task_root=task_root,
        attempts=attempts,
        shard=shard,
        baseline_revision=baseline_revision,
        required_fields=required_fields,
        semantic_contract=semantic_contract,
    )
    return reusable[0] if reusable is not None and len(reusable) == 1 else None


def run_blueprint_shard_workflow(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    total_chapters: int,
    volume_count: int,
    blueprint_title: str,
    writer_work_item_id: str,
    story_artifact_type: str,
    candidate_gate_id: str,
    context_artifact_types: Sequence[str],
    required_fields: Sequence[str],
    writer_instruction_path: Path,
    external_context_request_path: Path,
    timeout: int = 600,
    retries_per_volume: int = 2,
    chapters_per_generation: int | None = None,
    revision: int = 1,
    revision_guidance_path: Path | None = None,
    volume_ids: Sequence[str] = (),
    baseline_revision: int | None = None,
    semantic_contract_path: Path,
    assembly_only_baseline: bool = False,
) -> dict[str, object]:
    """Generate, validate, resume, assemble, and gate a sharded blueprint."""

    from agent_runtime.production_protocols import ProductionProtocolRunner
    from agent_runtime.task_runtime_v2.role_executor import RoleAttemptExecutor

    root = Path(agentlab_root).resolve(strict=False)
    runtime = TaskRuntime(root, project=project)
    task_root = runtime._task_dir(task_id).resolve(strict=True)
    task_inputs_root = task_root / "inputs"
    external_request_candidate = Path(external_context_request_path)
    lexical_external_request = external_request_candidate.absolute()
    if (
        task_inputs_root.is_symlink()
        or not lexical_external_request.is_relative_to(task_inputs_root)
        or is_forbidden_source_path(lexical_external_request)
    ):
        raise ValueError("external context request path is forbidden")
    cursor = task_inputs_root
    for part in lexical_external_request.relative_to(task_inputs_root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("external context request path is forbidden")
    resolved_external_request = external_request_candidate.resolve(strict=True)
    if (
        not resolved_external_request.is_file()
        or not resolved_external_request.is_relative_to(task_inputs_root)
        or is_forbidden_source_path(resolved_external_request)
    ):
        raise ValueError("external context request must be a regular Task input file")
    external_request = yaml.safe_load(
        resolved_external_request.read_text(encoding="utf-8")
    )
    if not isinstance(external_request, dict):
        raise ValueError("external context request must be a mapping")
    try:
        expires_at = datetime.fromisoformat(
            str(external_request.get("expires_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("external context request expiry is invalid") from exc
    if expires_at.tzinfo is None or (
        not assembly_only_baseline and expires_at <= datetime.now(timezone.utc)
    ):
        raise ValueError("external context request is expired")
    if (
        not str(external_request.get("purpose") or "").strip()
        or not str(external_request.get("minimal_fragment") or "").strip()
    ):
        raise ValueError("external context request purpose and fragment are required")
    runner = ProductionProtocolRunner(root, project=project)
    projection = runner.prepare(task_id)
    compiled = projection["task"].get("compiled_protocol") or {}
    writer_binding = next(
        (
            binding
            for binding in compiled.get("role_bindings") or []
            if binding.get("node_id") == writer_work_item_id
        ),
        None,
    )
    story_contract = next(
        (
            contract
            for contract in compiled.get("artifact_contracts") or []
            if contract.get("artifact_type") == story_artifact_type
        ),
        None,
    )
    candidate_gate = next(
        (
            gate
            for gate in compiled.get("promotion_gate_bindings") or []
            if gate.get("gate_id") == candidate_gate_id
        ),
        None,
    )
    artifact_contracts = {
        str(contract.get("artifact_type") or ""): contract
        for contract in compiled.get("artifact_contracts") or []
    }
    if (
        not isinstance(writer_binding, Mapping)
        or writer_binding.get("role") != "Writer"
    ):
        raise ValueError("writer identity does not match the compiled protocol")
    if (
        not isinstance(story_contract, Mapping)
        or story_contract.get("producer_node") != writer_work_item_id
    ):
        raise ValueError("story artifact does not match the compiled writer contract")
    if (
        not isinstance(candidate_gate, Mapping)
        or candidate_gate.get("work_item_id") != writer_work_item_id
        or candidate_gate.get("evidence_kind") != "automated"
        or set(candidate_gate.get("subject_artifact_types") or [])
        != {story_artifact_type}
    ):
        raise ValueError("candidate gate does not match the compiled protocol")
    writer = projection["work_items"].get(writer_work_item_id) or {}
    if writer.get("status") not in {"ready", "running", "waiting_review"}:
        raise ValueError(f"writer WorkItem is not executable: {writer.get('status')}")
    if revision <= 0:
        raise ValueError("revision must be positive")
    plan = build_blueprint_shard_plan(
        total_chapters=total_chapters, volume_count=volume_count
    )
    chapters_per_volume = total_chapters // volume_count
    if chapters_per_generation is None:
        chapters_per_generation = chapters_per_volume
    if chapters_per_generation <= 0:
        raise ValueError("chapters per generation must be positive")
    bounded_generation = chapters_per_generation < chapters_per_volume
    known_volume_ids = {item.volume_id for item in plan}
    requested_volume_ids = {str(item).upper() for item in volume_ids}
    unknown_volume_ids = sorted(requested_volume_ids - known_volume_ids)
    if unknown_volume_ids:
        raise ValueError(
            "unknown blueprint volume ids: " + ", ".join(unknown_volume_ids)
        )
    if assembly_only_baseline and requested_volume_ids:
        raise ValueError("assembly-only baseline cannot regenerate volumes")
    if requested_volume_ids or assembly_only_baseline:
        if baseline_revision is None:
            baseline_revision = revision - 1
        if baseline_revision <= 0 or baseline_revision >= revision:
            raise ValueError(
                "baseline revision must be positive and older than revision"
            )
    normalized_fields = tuple(str(field).strip() for field in required_fields)
    if (
        not normalized_fields
        or any(not field for field in normalized_fields)
        or len(set(normalized_fields)) != len(normalized_fields)
    ):
        raise ValueError("required chapter fields must be unique and non-empty")
    required_fields = normalized_fields
    instruction_path = Path(writer_instruction_path).resolve(strict=True)
    if (
        Path(writer_instruction_path).is_symlink()
        or not instruction_path.is_file()
        or not instruction_path.is_relative_to(task_root / "inputs")
    ):
        raise ValueError("writer instruction must be a regular Task input file")
    instruction_bytes = instruction_path.read_bytes()
    instruction_digest = hashlib.sha256(instruction_bytes).hexdigest()
    try:
        instruction_text = instruction_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("writer instruction is not UTF-8") from exc
    immutable_inputs_root = task_root / "inputs" / "blueprint_immutable"
    instruction_source_path, _ = _materialize_content_addressed_text(
        immutable_inputs_root,
        stem="writer-instruction",
        text=instruction_text,
        suffix=instruction_path.suffix or ".md",
        boundary=task_root,
    )
    artifacts = projection.get("artifacts") or {}
    latest_by_type: dict[str, tuple[str, Mapping[str, object]]] = {}
    for version_id, artifact in artifacts.items():
        if (
            isinstance(artifact, Mapping)
            and artifact.get("disposition", "eligible") == "eligible"
            and artifact.get("artifact_id") != story_artifact_type
        ):
            latest_by_type[str(artifact.get("artifact_id") or "")] = (
                str(version_id),
                artifact,
            )
    required_context = {
        str(item).strip() for item in context_artifact_types if str(item).strip()
    }
    if not required_context:
        raise ValueError("writer context artifact types are required")
    invalid_context = sorted(
        artifact_type
        for artifact_type in required_context
        if artifact_type not in artifact_contracts
        or artifact_contracts[artifact_type].get("producer_node") == writer_work_item_id
    )
    if invalid_context:
        raise ValueError(
            "writer context types do not match upstream protocol artifacts: "
            + ", ".join(invalid_context)
        )
    missing = sorted(required_context - set(latest_by_type))
    if missing:
        raise ValueError("writer context artifacts are missing: " + ", ".join(missing))
    manifest_entries: list[dict[str, object]] = []
    context_source_paths: list[Path] = []
    context_projection_sources: list[dict[str, object]] = []
    for artifact_type in sorted(required_context):
        version_id, artifact = latest_by_type[artifact_type]
        path = (task_root / str(artifact.get("path") or "")).resolve(strict=True)
        source_bytes = path.read_bytes()
        digest = hashlib.sha256(source_bytes).hexdigest()
        if digest != artifact.get("sha256"):
            raise ValueError(f"writer context artifact drifted: {artifact_type}")
        try:
            source_text = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"writer context artifact is not UTF-8: {artifact_type}"
            ) from exc
        manifest_entries.append(
            {
                "artifact_type": artifact_type,
                "version_id": version_id,
                "path": path.relative_to(task_root).as_posix(),
                "sha256": digest,
                "size_bytes": len(source_bytes),
            }
        )
        context_source_paths.append(path)
        snapshot_path, snapshot_sha256 = _materialize_content_addressed_text(
            immutable_inputs_root,
            stem=f"context-{artifact_type}",
            text=source_text,
            suffix=path.suffix or ".md",
            boundary=task_root,
        )
        if snapshot_sha256 != digest:
            raise ValueError(f"writer context snapshot drifted: {artifact_type}")
        context_source_paths[-1] = snapshot_path
        context_projection_sources.append(
            {
                "artifact_type": artifact_type,
                "path": path.relative_to(task_root).as_posix(),
                "sha256": digest,
                "text": source_text,
            }
        )
    context_manifest = {
        "schema_version": "narrative-blueprint-shard-context/v1",
        "task_id": task_id,
        "total_chapters": total_chapters,
        "volume_count": volume_count,
        "chapters_per_volume": chapters_per_volume,
        "revision": revision,
        "required_fields": list(required_fields),
        "regenerated_volume_ids": (
            []
            if assembly_only_baseline
            else sorted(requested_volume_ids or known_volume_ids)
        ),
        "reused_volume_ids": (
            sorted(known_volume_ids)
            if assembly_only_baseline
            else (
                sorted(known_volume_ids - requested_volume_ids)
                if requested_volume_ids
                else []
            )
        ),
        "baseline_revision": baseline_revision,
        "artifacts": manifest_entries,
        "writer_instruction": {
            "path": instruction_path.relative_to(task_root).as_posix(),
            "sha256": instruction_digest,
        },
    }
    guidance_path: Path | None = None
    guidance_source_path: Path | None = None
    if revision_guidance_path is not None:
        guidance_path = Path(revision_guidance_path).resolve(strict=True)
        if not guidance_path.is_relative_to(task_root):
            raise ValueError("revision guidance must be inside the Task")
        guidance_bytes = guidance_path.read_bytes()
        guidance_digest = hashlib.sha256(guidance_bytes).hexdigest()
        try:
            guidance_text = guidance_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("revision guidance is not UTF-8") from exc
        guidance_source_path, guidance_snapshot_sha256 = (
            _materialize_content_addressed_text(
                immutable_inputs_root,
                stem="revision-guidance",
                text=guidance_text,
                suffix=guidance_path.suffix or ".md",
                boundary=task_root,
            )
        )
        if guidance_snapshot_sha256 != guidance_digest:
            raise ValueError("revision guidance snapshot drifted")
        context_manifest["revision_guidance"] = {
            "path": guidance_path.relative_to(task_root).as_posix(),
            "sha256": guidance_digest,
        }
    semantic_contracts: dict[str, Mapping[str, object]] = {}
    if semantic_contract_path is not None:
        resolved_contract_path = Path(semantic_contract_path).resolve(strict=True)
        if not resolved_contract_path.is_relative_to(task_root):
            raise ValueError("semantic contract must be inside the Task")
        contract_bytes = resolved_contract_path.read_bytes()
        try:
            loaded_contract = yaml.safe_load(contract_bytes.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("semantic contract is invalid") from exc
        if not isinstance(loaded_contract, Mapping):
            raise ValueError("semantic contract must be a mapping")
        raw_volume_contracts = loaded_contract.get("volumes") or {}
        if not isinstance(raw_volume_contracts, Mapping):
            raise ValueError("semantic contract volumes must be a mapping")
        for volume_id, contract in raw_volume_contracts.items():
            normalized_volume_id = str(volume_id).upper()
            if normalized_volume_id not in known_volume_ids or not isinstance(
                contract, Mapping
            ):
                raise ValueError(f"invalid semantic contract volume: {volume_id}")
            semantic_contracts[normalized_volume_id] = contract
        context_manifest["semantic_contract"] = {
            "path": resolved_contract_path.relative_to(task_root).as_posix(),
            "sha256": hashlib.sha256(contract_bytes).hexdigest(),
        }
        missing_contracts = sorted(known_volume_ids - set(semantic_contracts))
        if missing_contracts:
            raise ValueError(
                "semantic contract missing final assembly volumes: "
                + ", ".join(missing_contracts)
            )
    context_manifest_path, context_manifest_sha256 = (
        _materialize_content_addressed_yaml(
            immutable_inputs_root,
            stem=f"writer-shard-context-v{revision:03d}",
            payload=context_manifest,
            boundary=task_root,
        )
    )
    executor = RoleAttemptExecutor(root, project=project)
    attempts_snapshot: Mapping[str, object] = projection.get("attempts") or {}
    accepted_children: list[str] = []
    legacy_transform_receipts: list[dict[str, str]] = []
    outputs: dict[str, str] = {}
    previous_handoff_path: Path | None = None

    def validated_attempt_output(
        attempt_id: str,
        target: BlueprintShard,
        contract: Mapping[str, object],
        *,
        attempts: Mapping[str, object] | None = None,
        expected_context_sha256: str | None = None,
        expected_generation_sha256: str | None = None,
    ) -> str | None:
        return validated_blueprint_attempt_output(
            task_root=task_root,
            attempts=(
                attempts
                if attempts is not None
                else runtime.load_task(task_id).get("attempts") or {}
            ),
            attempt_id=attempt_id,
            target=target,
            required_fields=required_fields,
            semantic_contract=contract,
            expected_context_manifest_sha256=expected_context_sha256,
            expected_generation_contract_sha256=expected_generation_sha256,
        )

    def write_handoff(text: str, suffix: str) -> Path:
        matches = list(_CHAPTER_HEADING.finditer(text))
        handoff_start = matches[-3].start() if len(matches) >= 3 else 0
        path, _ = _materialize_content_addressed_text(
            immutable_inputs_root,
            stem=f"writer-shard-handoff-v{revision:03d}-{suffix}",
            text=text[handoff_start:].strip() + "\n",
            suffix=".md",
            boundary=task_root,
        )
        return path

    for volume_shard in plan:
        semantic_contract = semantic_contracts.get(volume_shard.volume_id, {})
        accepted_volume_attempts: list[str] = []
        volume_text: str | None = None
        if assembly_only_baseline or (
            requested_volume_ids and volume_shard.volume_id not in requested_volume_ids
        ):
            reusable_attempts = find_reusable_blueprint_shard_attempts(
                task_root=task_root,
                attempts=(runtime.load_task(task_id).get("attempts") or {}),
                shard=volume_shard,
                baseline_revision=int(baseline_revision),
                required_fields=required_fields,
                semantic_contract=semantic_contract,
            )
            if reusable_attempts is None:
                raise ValueError(
                    "no reusable validated baseline output for "
                    f"{volume_shard.volume_id}"
                )
            baseline_segments: list[BlueprintShard] = []
            baseline_outputs: dict[tuple[int, int], str] = {}
            for reusable_attempt in reusable_attempts:
                output_path = (
                    task_root / "attempt_logs" / reusable_attempt / "output.md"
                )
                output_snapshot = _read_bounded_regular_file(
                    output_path, boundary=task_root
                )
                if output_snapshot is None:
                    raise ValueError(
                        "reusable baseline output escaped its Task boundary"
                    )
                try:
                    reusable_output_text = output_snapshot[1].decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("reusable baseline output is not UTF-8") from exc
                observed = [
                    int(match.group(1))
                    for match in _CHAPTER_HEADING.finditer(reusable_output_text)
                ]
                segment = BlueprintShard(
                    volume_id=volume_shard.volume_id,
                    start_chapter=min(observed),
                    end_chapter=max(observed),
                )
                segment_contract = _segment_semantic_contract(
                    segment,
                    semantic_contract,
                )
                candidate = validated_attempt_output(
                    reusable_attempt, segment, segment_contract
                )
                if candidate is None:
                    legacy = validated_legacy_blueprint_attempt_output(
                        task_root=task_root,
                        attempts=runtime.load_task(task_id).get("attempts") or {},
                        attempt_id=reusable_attempt,
                        target=segment,
                        required_fields=required_fields,
                        semantic_contract=segment_contract,
                    )
                    if legacy is None:
                        raise ValueError(
                            "reusable baseline output drifted for "
                            f"{volume_shard.volume_id}"
                        )
                    candidate, transform = legacy
                    transform_path, transform_sha256 = (
                        _materialize_content_addressed_yaml(
                            task_root
                            / "attempt_logs"
                            / f"attempt-writer-assembled-{revision:03d}"
                            / "baseline_transforms",
                            stem=reusable_attempt,
                            payload={
                                "schema_version": (
                                    "narrative-blueprint-baseline-transform/v1"
                                ),
                                "task_id": task_id,
                                "target_revision": revision,
                                "baseline_revision": baseline_revision,
                                "source_attempt_id": reusable_attempt,
                                "volume_id": volume_shard.volume_id,
                                "chapter_range": [
                                    segment.start_chapter,
                                    segment.end_chapter,
                                ],
                                "transform": transform,
                            },
                            boundary=task_root,
                        )
                    )
                    legacy_transform_receipts.append(
                        {
                            "path": transform_path.relative_to(task_root).as_posix(),
                            "sha256": transform_sha256,
                        }
                    )
                baseline_segments.append(segment)
                baseline_outputs[(segment.start_chapter, segment.end_chapter)] = (
                    candidate
                )
            volume_text = assemble_blueprint_volume_segments(
                volume_shard,
                baseline_segments,
                baseline_outputs,
                required_fields=required_fields,
                semantic_contract=semantic_contract,
            )
            accepted_volume_attempts.extend(reusable_attempts)
        else:
            prefix = "" if revision == 1 else f"rev{revision}-"
            for retry in range(1, retries_per_volume + 1):
                whole_attempt_id = (
                    f"attempt-writer-{prefix}{volume_shard.volume_id.lower()}-"
                    f"r{retry:02d}"
                )
                existing_text = validated_attempt_output(
                    whole_attempt_id,
                    volume_shard,
                    semantic_contract,
                    expected_context_sha256=context_manifest_sha256,
                )
                if existing_text is not None:
                    volume_text = existing_text
                    accepted_volume_attempts.append(whole_attempt_id)
                    break

            if volume_text is None:
                segments = split_blueprint_shard(
                    volume_shard, max_chapters=chapters_per_generation
                )
                segment_outputs: dict[tuple[int, int], str] = {}
                for segment in segments:
                    segment_contract = _segment_semantic_contract(
                        segment,
                        semantic_contract,
                    )
                    segment_token = volume_shard.volume_id.lower()
                    if len(segments) > 1:
                        segment_token += (
                            f"-c{segment.start_chapter:03d}-c{segment.end_chapter:03d}"
                        )
                    segment_context_sha256 = context_manifest_sha256
                    segment_context_source_paths = list(context_source_paths)
                    if bounded_generation:
                        segment_context_projection = (
                            build_blueprint_segment_context_projection(
                                task_id=task_id,
                                revision=revision,
                                segment=segment,
                                sources=context_projection_sources,
                            )
                        )
                        segment_context_path, segment_context_sha256 = (
                            _materialize_content_addressed_yaml(
                                immutable_inputs_root,
                                stem=(
                                    f"writer-segment-context-v{revision:03d}-"
                                    f"{segment_token}"
                                ),
                                payload=segment_context_projection,
                                boundary=task_root,
                            )
                        )
                        segment_context_source_paths = [segment_context_path]
                    prior_volume_text = "\n".join(
                        line
                        for output in segment_outputs.values()
                        for line in output.splitlines()
                        if not line.startswith("- forbidden_early_payoffs:")
                    )
                    remaining_volume_phrases = [
                        str(phrase).strip()
                        for phrase in semantic_contract.get("required_phrases") or []
                        if str(phrase).strip()
                        and str(phrase).strip() not in prior_volume_text
                    ]
                    prompt_contract = dict(segment_contract)
                    if remaining_volume_phrases:
                        prompt_contract["required_phrases"] = remaining_volume_phrases
                    shard_source_paths = [
                        *segment_context_source_paths,
                        instruction_source_path,
                    ]
                    if guidance_source_path is not None:
                        shard_source_paths.append(guidance_source_path)
                    if semantic_contract_path is not None:
                        volume_contract_path, _ = _materialize_content_addressed_yaml(
                            immutable_inputs_root,
                            stem=(
                                f"writer-semantic-contract-v{revision:03d}-"
                                f"{segment_token}"
                            ),
                            payload={
                                "schema_version": "narrative-blueprint-semantic-contract/v1",
                                "source_contract_sha256": context_manifest[
                                    "semantic_contract"
                                ]["sha256"],
                                "volumes": {volume_shard.volume_id: prompt_contract},
                            },
                            boundary=task_root,
                        )
                        shard_source_paths.append(volume_contract_path)
                    if previous_handoff_path is not None:
                        shard_source_paths.append(previous_handoff_path)
                    governed_sources = []
                    for source_path in shard_source_paths:
                        source_file = _read_bounded_regular_file(
                            source_path, boundary=task_root
                        )
                        if source_file is None:
                            raise ValueError(
                                "governed blueprint source escaped its Task boundary"
                            )
                        source_snapshot = source_file[1]
                        governed_sources.append(
                            {
                                "path": source_path.relative_to(task_root).as_posix(),
                                "sha256": hashlib.sha256(source_snapshot).hexdigest(),
                            }
                        )
                    governed_source_manifest_path, governed_source_manifest_sha256 = (
                        _materialize_content_addressed_yaml(
                            immutable_inputs_root,
                            stem=(
                                f"writer-governed-sources-v{revision:03d}-"
                                f"{segment_token}"
                            ),
                            payload={
                                "schema_version": "task-runtime-governed-source-manifest/v1",
                                "task_id": task_id,
                                "work_item_id": writer_work_item_id,
                                "sources": governed_sources,
                            },
                            boundary=task_root,
                        )
                    )
                    generation_contract_sha256 = (
                        build_blueprint_generation_contract_sha256(
                            task_id=task_id,
                            revision=revision,
                            segment=segment,
                            context_manifest_sha256=context_manifest_sha256,
                            segment_context_sha256=segment_context_sha256,
                            governed_source_manifest_sha256=(
                                governed_source_manifest_sha256
                            ),
                            semantic_contract=prompt_contract,
                            required_fields=required_fields,
                        )
                    )

                    def volume_completion_issues(candidate: str) -> list[str]:
                        if segment.end_chapter != volume_shard.end_chapter:
                            return []
                        tentative_outputs = dict(segment_outputs)
                        tentative_outputs[
                            (segment.start_chapter, segment.end_chapter)
                        ] = candidate
                        try:
                            assemble_blueprint_volume_segments(
                                volume_shard,
                                segments,
                                tentative_outputs,
                                required_fields=required_fields,
                                semantic_contract=semantic_contract,
                            )
                        except ValueError as exc:
                            return [str(exc)]
                        return []

                    accepted_attempt: str | None = None
                    candidate_text: str | None = None
                    for retry in range(1, retries_per_volume + 1):
                        child_id = (
                            f"attempt-writer-{prefix}{segment_token}-r{retry:02d}"
                        )
                        candidate_text = validated_attempt_output(
                            child_id,
                            segment,
                            segment_contract,
                            attempts=attempts_snapshot,
                            expected_context_sha256=context_manifest_sha256,
                            expected_generation_sha256=(generation_contract_sha256),
                        )
                        if candidate_text is not None and not volume_completion_issues(
                            candidate_text
                        ):
                            accepted_attempt = child_id
                            break
                        existing = attempts_snapshot.get(child_id)
                        if existing is not None:
                            continue
                        messages = [
                            {
                                "role": "system",
                                "content": (
                                    f"你是《{blueprint_title}》{total_chapters}章蓝本的 Writer。"
                                    f"只生成本次连续章段恰好{len(segment.chapters)}张章节卡。"
                                    "以下确定性语义门优先于所有其他上下文；必含词至少在实质叙事字段出现一次，"
                                    "禁含词不得出现在任何输出字段；语义合同只供校验，禁止摘抄到输出：\n"
                                    f"{yaml.safe_dump(prompt_contract, allow_unicode=True, sort_keys=True)}"
                                    "每章标题严格为 ## Cnnn 章名，随后严格写这些非空字段且每字段独占一行："
                                    + "、".join(
                                        f"- {field}:" for field in required_fields
                                    )
                                    + "。"
                                    "每个字段写具体人物、行动、资源或代价，禁止空泛概括；"
                                    "章节标题必须严格覆盖指定起止范围且无额外标题。"
                                    "forbidden_early_payoffs 只能写故事内尚不可兑现的事件。"
                                    "题材、节奏、人物和叙事要求只服从哈希密封的 writer instruction。"
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"context_manifest_sha256={context_manifest_sha256}\n"
                                    f"segment_context_sha256={segment_context_sha256}\n"
                                    f"生成 {volume_shard.volume_id} 的连续章段，范围 "
                                    f"C{segment.start_chapter:03d}-C{segment.end_chapter:03d}。"
                                    "严格执行密封的写作指令与语义合同。\n"
                                    "候选上下文、修订合同与前段连续性交接均在哈希密封来源中；"
                                    "只取与本章段相关的信息，不要复述原文。"
                                    "\n\n本章段确定性语义门（违反任何一项都会拒绝）：\n"
                                    f"{yaml.safe_dump(prompt_contract, allow_unicode=True, sort_keys=True)}"
                                ),
                            },
                        ]
                        result = executor.execute(
                            task_id=task_id,
                            work_item_id=writer_work_item_id,
                            attempt_id=child_id,
                            role="Writer",
                            messages=messages,
                            source_paths=shard_source_paths,
                            governed_source_manifest_path=governed_source_manifest_path,
                            external_context_request=external_request,
                            idempotency_key=(
                                f"{task_id}-rev{revision}-{segment_token}-r{retry:02d}"
                            ),
                            timeout=timeout,
                        )
                        current = result["projection"]
                        attempts_snapshot = current.get("attempts") or {}
                        attempt = current["attempts"][child_id]
                        if (
                            attempt.get("status") != "succeeded"
                            or result.get("output_path") is None
                        ):
                            continue
                        output_snapshot = _read_bounded_regular_file(
                            Path(str(result["output_path"])), boundary=task_root
                        )
                        if output_snapshot is None:
                            raise ValueError(
                                "Writer output escaped its Attempt boundary"
                            )
                        output_path, output_bytes = output_snapshot
                        output_sha256 = hashlib.sha256(output_bytes).hexdigest()
                        try:
                            text = output_bytes.decode("utf-8")
                            candidate_text = extract_blueprint_shard_cards(
                                segment,
                                text,
                                required_fields=required_fields,
                            )
                            issues = list(
                                validate_blueprint_shard_semantics(
                                    segment, candidate_text, segment_contract
                                )
                            )
                            issues.extend(volume_completion_issues(candidate_text))
                        except (UnicodeDecodeError, ValueError) as exc:
                            issues = [str(exc)]
                            candidate_text = None
                        validation_path, _ = _materialize_content_addressed_yaml(
                            output_path.parent,
                            stem="artifact-validation",
                            payload={
                                "schema_version": "protocol-artifact-validation/v1",
                                "status": "fail" if issues else "pass",
                                "task_id": task_id,
                                "work_item_id": writer_work_item_id,
                                "attempt_id": child_id,
                                "artifact_type": f"{story_artifact_type}_shard",
                                "volume_id": volume_shard.volume_id,
                                "chapter_range": [
                                    segment.start_chapter,
                                    segment.end_chapter,
                                ],
                                "context_manifest_path": (
                                    context_manifest_path.relative_to(
                                        task_root
                                    ).as_posix()
                                ),
                                "context_manifest_sha256": context_manifest_sha256,
                                "segment_context_sha256": segment_context_sha256,
                                "governed_source_manifest_sha256": (
                                    governed_source_manifest_sha256
                                ),
                                "generation_contract_sha256": (
                                    generation_contract_sha256
                                ),
                                "output_sha256": output_sha256,
                                "issues": issues,
                            },
                            boundary=task_root,
                        )
                        runtime.record_attempt_output_validation(
                            task_id,
                            attempt_id=child_id,
                            status="fail" if issues else "pass",
                            validation_receipt_path=validation_path,
                            issues=issues,
                            idempotency_key=(
                                f"{task_id}-rev{revision}-{segment_token}-"
                                f"r{retry:02d}-validate"
                            ),
                        )
                        if not issues:
                            accepted_attempt = child_id
                            break
                    if accepted_attempt is None or candidate_text is None:
                        raise ValueError(
                            "no valid Writer output for "
                            f"{volume_shard.volume_id} "
                            f"C{segment.start_chapter:03d}-C{segment.end_chapter:03d}"
                        )
                    accepted_volume_attempts.append(accepted_attempt)
                    segment_outputs[(segment.start_chapter, segment.end_chapter)] = (
                        candidate_text
                    )
                    previous_handoff_path = write_handoff(candidate_text, segment_token)
                volume_text = assemble_blueprint_volume_segments(
                    volume_shard,
                    segments,
                    segment_outputs,
                    required_fields=required_fields,
                    semantic_contract=semantic_contract,
                )
        if volume_text is None:
            raise ValueError(f"no valid Writer output for {volume_shard.volume_id}")
        accepted_children.extend(accepted_volume_attempts)
        outputs[volume_shard.volume_id] = volume_text
        previous_handoff_path = write_handoff(
            volume_text, volume_shard.volume_id.lower()
        )
    assembled = assemble_blueprint_shards(
        plan,
        outputs,
        title=blueprint_title,
        protocol_ref=str(projection["task"].get("protocol_ref") or ""),
        required_fields=required_fields,
    )
    composite_id = f"attempt-writer-assembled-{revision:03d}"
    composite = runtime.load_task(task_id)["attempts"].get(composite_id)
    assembled_sha256 = hashlib.sha256(assembled.encode("utf-8")).hexdigest()
    if composite is None:
        executor.assemble_validated_attempts(
            task_id=task_id,
            work_item_id=writer_work_item_id,
            attempt_id=composite_id,
            child_attempt_ids=accepted_children,
            output_text=assembled,
            idempotency_key=f"{task_id}-writer-assembly-v{revision}",
        )
    elif not isinstance(composite, Mapping) or not blueprint_composite_matches(
        task_root=task_root,
        attempt_id=composite_id,
        attempt=composite,
        expected_child_attempt_ids=accepted_children,
        expected_output_sha256=assembled_sha256,
        expected_context_manifest_sha256=context_manifest_sha256,
        expected_legacy_transform_receipts=legacy_transform_receipts,
    ):
        raise ValueError(
            "existing blueprint composite does not match current children or context"
        )
    composite_output = task_root / "attempt_logs" / composite_id / "output.md"
    current = runtime.load_task(task_id)
    if (current["attempts"][composite_id].get("output_validation") or {}).get(
        "status"
    ) is None:
        composite_snapshot = _read_bounded_regular_file(
            composite_output, boundary=task_root
        )
        if composite_snapshot is None:
            raise ValueError("blueprint composite output escaped its Attempt boundary")
        observed_composite_sha256 = hashlib.sha256(composite_snapshot[1]).hexdigest()
        if observed_composite_sha256 != assembled_sha256:
            raise ValueError(
                "blueprint composite output hash drifted before validation"
            )
        validation_path, _ = _materialize_content_addressed_yaml(
            composite_output.parent,
            stem="artifact-validation",
            payload={
                "schema_version": "protocol-artifact-validation/v1",
                "status": "pass",
                "task_id": task_id,
                "work_item_id": writer_work_item_id,
                "attempt_id": composite_id,
                "artifact_type": story_artifact_type,
                "context_manifest_path": context_manifest_path.relative_to(
                    task_root
                ).as_posix(),
                "context_manifest_sha256": context_manifest_sha256,
                "child_attempt_ids": accepted_children,
                "legacy_transform_receipts": legacy_transform_receipts,
                "output_sha256": observed_composite_sha256,
                "issues": [],
            },
            boundary=task_root,
        )
        runtime.record_attempt_output_validation(
            task_id,
            attempt_id=composite_id,
            status="pass",
            validation_receipt_path=validation_path,
            issues=[],
            idempotency_key=(f"{task_id}-writer-assembly-validation-v{revision}"),
        )
    runner.execute_node(
        task_id,
        work_item_id=writer_work_item_id,
        messages=[{"role": "user", "content": "Finalize validated shard assembly."}],
        source_paths=[],
        external_context_request=external_request,
        attempt_id=composite_id,
        idempotency_key=f"{task_id}-writer-finalize-v{revision}",
        timeout=timeout,
    )
    current = runtime.load_task(task_id)
    story_versions = [
        (version_id, artifact)
        for version_id, artifact in current["artifacts"].items()
        if artifact.get("artifact_id") == story_artifact_type
        and artifact.get("producer_attempt_id") == composite_id
        and artifact.get("disposition", "eligible") == "eligible"
    ]
    if len(story_versions) != 1:
        raise ValueError("assembled blueprint artifact is not unique")
    story_version_id, story_artifact = story_versions[0]
    if candidate_gate_id not in current["protocol_gates"]:
        subjects = {story_artifact_type: str(story_artifact["sha256"])}
        evidence_sha256 = hashlib.sha256(
            json.dumps(
                subjects, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        runtime.record_protocol_gate(
            task_id,
            gate_id=candidate_gate_id,
            work_item_id=writer_work_item_id,
            evidence_kind="automated",
            evidence_sha256=evidence_sha256,
            attempt_id=composite_id,
            subject_version_ids=[story_version_id],
            actor="agentlab_blueprint_shard_workflow",
            idempotency_key=f"{task_id}-candidate-hash-gate-v{revision}",
        )
    current = runtime.load_task(task_id)
    if current["work_items"][writer_work_item_id]["status"] == "waiting_review":
        current = runtime.transition_work_item(
            task_id,
            work_item_id=writer_work_item_id,
            status="accepted",
            idempotency_key=f"{task_id}-writer-accepted-v{revision}",
        )
    return {
        "status": "accepted",
        "task_id": task_id,
        "work_item_id": writer_work_item_id,
        "volumes": len(plan),
        "chapters": total_chapters,
        "regenerated_volume_ids": (
            []
            if assembly_only_baseline
            else sorted(requested_volume_ids or known_volume_ids)
        ),
        "reused_volume_ids": (
            sorted(known_volume_ids)
            if assembly_only_baseline
            else (
                sorted(known_volume_ids - requested_volume_ids)
                if requested_volume_ids
                else []
            )
        ),
        "child_attempt_ids": accepted_children,
        "composite_attempt_id": composite_id,
        "blueprint_version_id": story_version_id,
        "blueprint_sha256": story_artifact["sha256"],
        "context_manifest_sha256": context_manifest_sha256,
        "projection": current,
    }
