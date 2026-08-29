"""Bounded, resumable chapter-blueprint sharding primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from collections.abc import Mapping, Sequence

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
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
_SHARD_MARKDOWN_START = re.compile(
    r"(?m)^```[ \t]*AGENTLAB_EDIT\b[^\r\n]*$"
)
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
    duplicates = sorted({chapter for chapter in observed if observed.count(chapter) > 1})
    if missing:
        issues.append("missing chapters: " + ", ".join(f"C{item:03d}" for item in missing))
    if unexpected:
        issues.append(
            "out-of-range chapters: "
            + ", ".join(f"C{item:03d}" for item in unexpected)
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
                field_match = re.fullmatch(
                    r"- ([A-Za-z][A-Za-z0-9_]*):\s*\S.*", line
                )
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
            if (
                chapter_id_match
                and chapter_id_match.group(1) != f"C{chapter:03d}"
            ):
                issues.append(
                    f"C{chapter:03d} chapter_id mismatch: "
                    f"{chapter_id_match.group(1)}"
                )
        if "title" in required_fields:
            title_match = re.search(r"(?m)^- title:\s*(\S.*?)\s*$", card)
            heading_title = (match.group(2) or "").strip()
            if title_match and title_match.group(1).strip() != heading_title:
                issues.append(
                    f"C{chapter:03d} title mismatch: {title_match.group(1).strip()}"
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
        xml_trailer = re.compile(
            r"(?m)^</AGENTLAB_EDIT>[ \t]*$"
        ).search(text, search_start)
        if xml_trailer is not None:
            trailer_candidates.append(xml_trailer)
    trailer = min(trailer_candidates, key=lambda match: match.start(), default=None)
    end = trailer.start() if trailer is not None else len(text)
    payload = text[start:end].strip()
    normalized_lines: list[str] = []
    current_chapter_id = ""
    current_title = ""
    for line in payload.splitlines():
        heading = _CHAPTER_HEADING.fullmatch(line)
        if heading is not None:
            current_chapter_id = f"C{int(heading.group(1)):03d}"
            current_title = (heading.group(2) or "").strip()
            normalized_lines.append(line)
            continue
        if line.startswith("- chapter_id:") and current_chapter_id:
            normalized_lines.append(f"- chapter_id: {current_chapter_id}")
            continue
        if line.startswith("- title:") and current_chapter_id:
            normalized_lines.append(f"- title: {current_title}")
            continue
        if line.startswith("- volume:"):
            normalized_lines.append(f"- volume: {shard.volume_id}")
            continue
        normalized_lines.append(line)
    normalized = "\n".join(normalized_lines).strip() + "\n"
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
        chapter_match = re.fullmatch(r"C(\d{3})", chapter_id)
        if chapter_match and int(chapter_match.group(1)) not in shard.chapters:
            continue
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
    segment: BlueprintShard, contract: Mapping[str, object]
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


def find_reusable_blueprint_shard_attempt(
    *,
    task_root: Path,
    attempts: Mapping[str, object],
    shard: BlueprintShard,
    baseline_revision: int,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
    semantic_contract: Mapping[str, object] | None = None,
) -> str | None:
    """Find a baseline shard that still passes current structure and semantics."""

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
    for attempt_id in candidate_ids:
        attempt = attempts.get(attempt_id)
        if not isinstance(attempt, Mapping):
            continue
        output_path = task_root / "attempt_logs" / str(attempt_id) / "output.md"
        output_text = (
            output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
        )
        if (
            attempt.get("status") != "succeeded"
            or (attempt.get("output_validation") or {}).get("status") != "pass"
            or not output_text
        ):
            continue
        try:
            candidate_text = extract_blueprint_shard_cards(
                shard,
                output_text,
                required_fields=required_fields,
            )
        except ValueError:
            continue
        if not validate_blueprint_shard_semantics(
            shard,
            candidate_text,
            semantic_contract or {},
        ):
            return str(attempt_id)
    return None


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
    if not isinstance(writer_binding, Mapping) or writer_binding.get("role") != "Writer":
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
    known_volume_ids = {item.volume_id for item in plan}
    requested_volume_ids = {str(item).upper() for item in volume_ids}
    unknown_volume_ids = sorted(requested_volume_ids - known_volume_ids)
    if unknown_volume_ids:
        raise ValueError("unknown blueprint volume ids: " + ", ".join(unknown_volume_ids))
    if assembly_only_baseline and requested_volume_ids:
        raise ValueError("assembly-only baseline cannot regenerate volumes")
    if requested_volume_ids or assembly_only_baseline:
        if baseline_revision is None:
            baseline_revision = revision - 1
        if baseline_revision <= 0 or baseline_revision >= revision:
            raise ValueError("baseline revision must be positive and older than revision")
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
    instruction_digest = hashlib.sha256(instruction_path.read_bytes()).hexdigest()
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
    required_context = {str(item).strip() for item in context_artifact_types if str(item).strip()}
    if not required_context:
        raise ValueError("writer context artifact types are required")
    invalid_context = sorted(
        artifact_type
        for artifact_type in required_context
        if artifact_type not in artifact_contracts
        or artifact_contracts[artifact_type].get("producer_node")
        == writer_work_item_id
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
    for artifact_type in sorted(required_context):
        version_id, artifact = latest_by_type[artifact_type]
        path = (task_root / str(artifact.get("path") or "")).resolve(strict=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != artifact.get("sha256"):
            raise ValueError(f"writer context artifact drifted: {artifact_type}")
        manifest_entries.append(
            {
                "artifact_type": artifact_type,
                "version_id": version_id,
                "path": path.relative_to(task_root).as_posix(),
                "sha256": digest,
                "size_bytes": len(path.read_bytes()),
            }
        )
        context_source_paths.append(path)
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
    if revision_guidance_path is not None:
        guidance_path = Path(revision_guidance_path).resolve(strict=True)
        if not guidance_path.is_relative_to(task_root):
            raise ValueError("revision guidance must be inside the Task")
        guidance_digest = hashlib.sha256(guidance_path.read_bytes()).hexdigest()
        context_manifest["revision_guidance"] = {
            "path": guidance_path.relative_to(task_root).as_posix(),
            "sha256": guidance_digest,
        }
    semantic_contracts: dict[str, Mapping[str, object]] = {}
    if semantic_contract_path is not None:
        resolved_contract_path = Path(semantic_contract_path).resolve(strict=True)
        if not resolved_contract_path.is_relative_to(task_root):
            raise ValueError("semantic contract must be inside the Task")
        loaded_contract = yaml.safe_load(
            resolved_contract_path.read_text(encoding="utf-8")
        )
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
            "sha256": hashlib.sha256(
                resolved_contract_path.read_bytes()
            ).hexdigest(),
        }
        missing_contracts = sorted(known_volume_ids - set(semantic_contracts))
        if missing_contracts:
            raise ValueError(
                "semantic contract missing final assembly volumes: "
                + ", ".join(missing_contracts)
            )
    context_manifest_path = (
        task_root / "inputs" / f"writer-shard-context-v{revision:03d}.yml"
    )
    atomic_write_yaml(context_manifest_path, context_manifest)
    context_manifest_sha256 = hashlib.sha256(
        context_manifest_path.read_bytes()
    ).hexdigest()
    executor = RoleAttemptExecutor(root, project=project)
    accepted_children: list[str] = []
    outputs: dict[str, str] = {}
    previous_handoff_path: Path | None = None

    def validated_attempt_output(
        attempt_id: str,
        target: BlueprintShard,
        contract: Mapping[str, object],
    ) -> str | None:
        attempt = (runtime.load_task(task_id).get("attempts") or {}).get(attempt_id)
        output_path = task_root / "attempt_logs" / attempt_id / "output.md"
        if (
            not isinstance(attempt, Mapping)
            or attempt.get("status") != "succeeded"
            or (attempt.get("output_validation") or {}).get("status") != "pass"
            or not output_path.is_file()
        ):
            return None
        try:
            candidate = extract_blueprint_shard_cards(
                target,
                output_path.read_text(encoding="utf-8"),
                required_fields=required_fields,
            )
        except ValueError:
            return None
        if validate_blueprint_shard_semantics(target, candidate, contract):
            return None
        return candidate

    def write_handoff(text: str, suffix: str) -> Path:
        matches = list(_CHAPTER_HEADING.finditer(text))
        handoff_start = matches[-3].start() if len(matches) >= 3 else 0
        path = (
            task_root
            / "inputs"
            / f"writer-shard-handoff-v{revision:03d}-{suffix}.md"
        )
        atomic_write_text(path, text[handoff_start:].strip() + "\n")
        return path

    for volume_shard in plan:
        semantic_contract = semantic_contracts.get(volume_shard.volume_id, {})
        accepted_volume_attempts: list[str] = []
        volume_text: str | None = None
        if assembly_only_baseline or (
            requested_volume_ids and volume_shard.volume_id not in requested_volume_ids
        ):
            accepted_attempt = find_reusable_blueprint_shard_attempt(
                task_root=task_root,
                attempts=(runtime.load_task(task_id).get("attempts") or {}),
                shard=volume_shard,
                baseline_revision=int(baseline_revision),
                required_fields=required_fields,
                semantic_contract=semantic_contract,
            )
            if accepted_attempt is None:
                raise ValueError(
                    "no reusable validated baseline output for "
                    f"{volume_shard.volume_id}"
                )
            volume_text = validated_attempt_output(
                accepted_attempt, volume_shard, semantic_contract
            )
            if volume_text is None:
                raise ValueError(
                    f"reusable baseline output drifted for {volume_shard.volume_id}"
                )
            accepted_volume_attempts.append(accepted_attempt)
        else:
            prefix = "" if revision == 1 else f"rev{revision}-"
            for retry in range(1, retries_per_volume + 1):
                whole_attempt_id = (
                    f"attempt-writer-{prefix}{volume_shard.volume_id.lower()}-"
                    f"r{retry:02d}"
                )
                existing_text = validated_attempt_output(
                    whole_attempt_id, volume_shard, semantic_contract
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
                        segment, semantic_contract
                    )
                    segment_token = volume_shard.volume_id.lower()
                    if len(segments) > 1:
                        segment_token += (
                            f"-c{segment.start_chapter:03d}-c{segment.end_chapter:03d}"
                        )
                    accepted_attempt: str | None = None
                    candidate_text: str | None = None
                    for retry in range(1, retries_per_volume + 1):
                        child_id = (
                            f"attempt-writer-{prefix}{segment_token}-r{retry:02d}"
                        )
                        candidate_text = validated_attempt_output(
                            child_id, segment, segment_contract
                        )
                        if candidate_text is not None:
                            accepted_attempt = child_id
                            break
                        current = runtime.load_task(task_id)
                        existing = (current.get("attempts") or {}).get(child_id)
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
                                    f"{yaml.safe_dump(segment_contract, allow_unicode=True, sort_keys=True)}"
                                    "每章标题严格为 ## Cnnn 章名，随后严格写这些非空字段且每字段独占一行："
                                    + "、".join(f"- {field}:" for field in required_fields)
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
                                    f"生成 {volume_shard.volume_id} 的连续章段，范围 "
                                    f"C{segment.start_chapter:03d}-C{segment.end_chapter:03d}。"
                                    "严格执行密封的写作指令与语义合同。\n"
                                    "候选上下文、修订合同与前段连续性交接均在哈希密封来源中；"
                                    "只取与本章段相关的信息，不要复述原文。"
                                    "\n\n本章段确定性语义门（违反任何一项都会拒绝）：\n"
                                    f"{yaml.safe_dump(segment_contract, allow_unicode=True, sort_keys=True)}"
                                ),
                            },
                        ]
                        shard_source_paths = [*context_source_paths, instruction_path]
                        if guidance_path is not None:
                            shard_source_paths.append(guidance_path)
                        if semantic_contract_path is not None:
                            volume_contract_path = (
                                task_root
                                / "inputs"
                                / (
                                    f"writer-semantic-contract-v{revision:03d}-"
                                    f"{segment_token}.yml"
                                )
                            )
                            atomic_write_yaml(
                                volume_contract_path,
                                {
                                    "schema_version": "narrative-blueprint-semantic-contract/v1",
                                    "source_contract_sha256": context_manifest[
                                        "semantic_contract"
                                    ]["sha256"],
                                    "volumes": {
                                        volume_shard.volume_id: segment_contract
                                    },
                                },
                            )
                            shard_source_paths.append(volume_contract_path)
                        if previous_handoff_path is not None:
                            shard_source_paths.append(previous_handoff_path)
                        governed_source_manifest_path = (
                            task_root
                            / "inputs"
                            / (
                                f"writer-governed-sources-v{revision:03d}-"
                                f"{segment_token}.yml"
                            )
                        )
                        atomic_write_yaml(
                            governed_source_manifest_path,
                            {
                                "schema_version": "task-runtime-governed-source-manifest/v1",
                                "task_id": task_id,
                                "work_item_id": writer_work_item_id,
                                "sources": [
                                    {
                                        "path": path.relative_to(task_root).as_posix(),
                                        "sha256": hashlib.sha256(
                                            path.read_bytes()
                                        ).hexdigest(),
                                    }
                                    for path in shard_source_paths
                                ],
                            },
                        )
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
                                f"{task_id}-rev{revision}-{segment_token}-"
                                f"r{retry:02d}"
                            ),
                            timeout=timeout,
                        )
                        current = result["projection"]
                        attempt = current["attempts"][child_id]
                        if (
                            attempt.get("status") != "succeeded"
                            or result.get("output_path") is None
                        ):
                            continue
                        output_path = Path(str(result["output_path"])).resolve(
                            strict=True
                        )
                        text = output_path.read_text(encoding="utf-8")
                        try:
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
                        except ValueError as exc:
                            issues = [str(exc)]
                            candidate_text = None
                        validation_path = (
                            output_path.parent / "artifact_validation_receipt.yml"
                        )
                        atomic_write_yaml(
                            validation_path,
                            {
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
                                "context_manifest_sha256": context_manifest_sha256,
                                "output_sha256": hashlib.sha256(
                                    output_path.read_bytes()
                                ).hexdigest(),
                                "issues": issues,
                            },
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
                    segment_outputs[
                        (segment.start_chapter, segment.end_chapter)
                    ] = candidate_text
                    previous_handoff_path = write_handoff(
                        candidate_text, segment_token
                    )
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
    if composite is None:
        executor.assemble_validated_attempts(
            task_id=task_id,
            work_item_id=writer_work_item_id,
            attempt_id=composite_id,
            child_attempt_ids=accepted_children,
            output_text=assembled,
            idempotency_key=f"{task_id}-writer-assembly-v{revision}",
        )
    composite_output = task_root / "attempt_logs" / composite_id / "output.md"
    current = runtime.load_task(task_id)
    if (current["attempts"][composite_id].get("output_validation") or {}).get(
        "status"
    ) is None:
        validation_path = composite_output.parent / "artifact_validation_receipt.yml"
        atomic_write_yaml(
            validation_path,
            {
                "schema_version": "protocol-artifact-validation/v1",
                "status": "pass",
                "task_id": task_id,
                "work_item_id": writer_work_item_id,
                "attempt_id": composite_id,
                "artifact_type": story_artifact_type,
                "context_manifest_sha256": context_manifest_sha256,
                "child_attempt_ids": accepted_children,
                "output_sha256": hashlib.sha256(
                    composite_output.read_bytes()
                ).hexdigest(),
                "issues": [],
            },
        )
        runtime.record_attempt_output_validation(
            task_id,
            attempt_id=composite_id,
            status="pass",
            validation_receipt_path=validation_path,
            issues=[],
            idempotency_key=(
                f"{task_id}-writer-assembly-validation-v{revision}"
            ),
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
