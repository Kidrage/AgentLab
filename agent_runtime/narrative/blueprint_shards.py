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


def validate_blueprint_shard(
    shard: BlueprintShard,
    text: str,
    *,
    required_fields: Sequence[str] = _REQUIRED_CARD_FIELDS,
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
        text = outputs[shard.volume_id].strip()
        issues = validate_blueprint_shard(
            shard, text, required_fields=required_fields
        )
        if issues:
            raise ValueError(f"invalid blueprint shard {shard.volume_id}: {'; '.join(issues)}")
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
    semantic_text = "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith("- forbidden_early_payoffs:")
    )
    for phrase in contract.get("required_phrases") or []:
        normalized = str(phrase).strip()
        if normalized and normalized not in semantic_text:
            issues.append(f"{shard.volume_id} missing required phrase: {normalized}")
    for phrase in contract.get("forbidden_phrases") or []:
        normalized = str(phrase).strip()
        if normalized and normalized in semantic_text:
            issues.append(f"{shard.volume_id} contains forbidden phrase: {normalized}")
    chapter_rules = contract.get("chapter_rules") or {}
    if not isinstance(chapter_rules, Mapping):
        return (*issues, f"{shard.volume_id} chapter_rules must be a mapping")
    matches = list(_CHAPTER_HEADING.finditer(text))
    cards: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        cards[f"C{int(match.group(1)):03d}"] = "\n".join(
            line
            for line in text[match.start() : end].splitlines()
            if not line.startswith("- forbidden_early_payoffs:")
        )
    for raw_chapter_id, raw_rule in chapter_rules.items():
        chapter_id = str(raw_chapter_id).strip()
        if chapter_id not in cards:
            issues.append(f"{shard.volume_id} chapter rule target missing: {chapter_id}")
            continue
        if not isinstance(raw_rule, Mapping):
            issues.append(f"{chapter_id} semantic rule must be a mapping")
            continue
        card_text = cards[chapter_id]
        for phrase in raw_rule.get("required_phrases") or []:
            normalized = str(phrase).strip()
            if normalized and normalized not in card_text:
                issues.append(f"{chapter_id} missing required phrase: {normalized}")
        for phrase in raw_rule.get("forbidden_phrases") or []:
            normalized = str(phrase).strip()
            if normalized and normalized in card_text:
                issues.append(f"{chapter_id} contains forbidden phrase: {normalized}")
    return tuple(issues)


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

    pattern = re.compile(
        rf"^attempt-writer-rev(\d+)-{re.escape(shard.volume_id.lower())}-r\d+$"
    )
    candidates: list[tuple[int, str]] = []
    for item in attempts:
        match = pattern.match(str(item))
        if match and int(match.group(1)) <= baseline_revision:
            candidates.append((int(match.group(1)), str(item)))
    for _, attempt_id in sorted(candidates, key=lambda item: (-item[0], item[1])):
        attempt = attempts[attempt_id]
        if not isinstance(attempt, Mapping):
            continue
        output_path = task_root / "attempt_logs" / str(attempt_id) / "output.md"
        output_text = (
            output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
        )
        if (
            attempt.get("status") == "succeeded"
            and (attempt.get("output_validation") or {}).get("status") == "pass"
            and output_text
            and not validate_blueprint_shard(
                shard,
                output_text,
                required_fields=required_fields,
            )
            and not validate_blueprint_shard_semantics(
                shard,
                output_text,
                semantic_contract or {},
            )
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
    revision: int = 1,
    revision_guidance_path: Path | None = None,
    volume_ids: Sequence[str] = (),
    baseline_revision: int | None = None,
    semantic_contract_path: Path | None = None,
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
    if expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
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
    known_volume_ids = {item.volume_id for item in plan}
    requested_volume_ids = {str(item).upper() for item in volume_ids}
    unknown_volume_ids = sorted(requested_volume_ids - known_volume_ids)
    if unknown_volume_ids:
        raise ValueError("unknown blueprint volume ids: " + ", ".join(unknown_volume_ids))
    if requested_volume_ids:
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
        "regenerated_volume_ids": sorted(requested_volume_ids or known_volume_ids),
        "reused_volume_ids": sorted(known_volume_ids - requested_volume_ids)
        if requested_volume_ids
        else [],
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
    for shard in plan:
        accepted_attempt: str | None = None
        semantic_contract = semantic_contracts.get(shard.volume_id, {})
        if requested_volume_ids and shard.volume_id not in requested_volume_ids:
            accepted_attempt = find_reusable_blueprint_shard_attempt(
                task_root=task_root,
                attempts=(runtime.load_task(task_id).get("attempts") or {}),
                shard=shard,
                baseline_revision=int(baseline_revision),
                required_fields=required_fields,
                semantic_contract=semantic_contract,
            )
            if accepted_attempt is None:
                raise ValueError(
                    f"no reusable validated baseline output for {shard.volume_id}"
                )
        for retry in range(1, retries_per_volume + 1):
            if accepted_attempt is not None:
                break
            prefix = "" if revision == 1 else f"rev{revision}-"
            child_id = (
                f"attempt-writer-{prefix}{shard.volume_id.lower()}-r{retry:02d}"
            )
            current = runtime.load_task(task_id)
            existing = (current.get("attempts") or {}).get(child_id)
            output_path = task_root / "attempt_logs" / child_id / "output.md"
            if existing is not None:
                if (
                    existing.get("status") == "succeeded"
                    and (existing.get("output_validation") or {}).get("status") == "pass"
                    and output_path.is_file()
                    and not validate_blueprint_shard(
                        shard,
                        output_path.read_text(encoding="utf-8"),
                        required_fields=required_fields,
                    )
                    and not validate_blueprint_shard_semantics(
                        shard,
                        output_path.read_text(encoding="utf-8"),
                        semantic_contract,
                    )
                ):
                    accepted_attempt = child_id
                    break
                continue
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"你是《{blueprint_title}》{total_chapters}章蓝本的 Writer。"
                        f"只生成本卷恰好{chapters_per_volume}张章节卡。"
                        "以下本卷确定性语义门优先于所有其他上下文；必含词至少在实质叙事字段出现一次，"
                        "禁含词不得出现在 forbidden_early_payoffs 之外的字段：\n"
                        f"{yaml.safe_dump(dict(semantic_contract), allow_unicode=True, sort_keys=True)}"
                        "每章标题严格为 ## Cnnn 章名，随后严格写这些非空字段且每字段独占一行："
                        + "、".join(f"- {field}:" for field in required_fields)
                        + "。"
                        "每个字段写具体人物、行动、资源或代价，禁止空泛概括；不得生成范围外章节。"
                        "题材、节奏、人物和叙事要求只服从哈希密封的 writer instruction。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"context_manifest_sha256={context_manifest_sha256}\n"
                        f"生成 {shard.volume_id}，范围 C{shard.start_chapter:03d}-"
                        f"C{shard.end_chapter:03d}。严格执行密封的写作指令与语义合同。\n"
                        "候选上下文、修订合同与前卷连续性交接均在哈希密封来源中；"
                        "只取与本卷相关的信息，不要复述原文。"
                        "\n\n本卷确定性语义门（违反任何一项都会拒绝本分片）：\n"
                        f"{yaml.safe_dump(dict(semantic_contract), allow_unicode=True, sort_keys=True)}"
                    ),
                },
            ]
            shard_source_paths = [*context_source_paths, instruction_path]
            if guidance_path is not None:
                shard_source_paths.append(guidance_path)
            if semantic_contract_path is not None:
                shard_source_paths.append(resolved_contract_path)
            if previous_handoff_path is not None:
                shard_source_paths.append(previous_handoff_path)
            governed_source_manifest_path = (
                task_root
                / "inputs"
                / (
                    f"writer-governed-sources-v{revision:03d}-"
                    f"{shard.volume_id.lower()}.yml"
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
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
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
                    f"{task_id}-rev{revision}-{shard.volume_id.lower()}-r{retry:02d}"
                ),
                timeout=timeout,
            )
            current = result["projection"]
            attempt = current["attempts"][child_id]
            if attempt.get("status") != "succeeded" or result.get("output_path") is None:
                continue
            output_path = Path(str(result["output_path"])).resolve(strict=True)
            text = output_path.read_text(encoding="utf-8")
            issues = list(
                validate_blueprint_shard(
                    shard, text, required_fields=required_fields
                )
            )
            issues.extend(
                validate_blueprint_shard_semantics(shard, text, semantic_contract)
            )
            validation_path = output_path.parent / "artifact_validation_receipt.yml"
            atomic_write_yaml(
                validation_path,
                {
                    "schema_version": "protocol-artifact-validation/v1",
                    "status": "fail" if issues else "pass",
                    "task_id": task_id,
                    "work_item_id": writer_work_item_id,
                    "attempt_id": child_id,
                    "artifact_type": f"{story_artifact_type}_shard",
                    "volume_id": shard.volume_id,
                    "chapter_range": [shard.start_chapter, shard.end_chapter],
                    "context_manifest_sha256": context_manifest_sha256,
                    "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
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
                    f"{task_id}-rev{revision}-{shard.volume_id.lower()}-"
                    f"r{retry:02d}-validate"
                ),
            )
            if not issues:
                accepted_attempt = child_id
                break
        if accepted_attempt is None:
            raise ValueError(f"no valid Writer output for {shard.volume_id}")
        accepted_children.append(accepted_attempt)
        shard_text = (task_root / "attempt_logs" / accepted_attempt / "output.md").read_text(
            encoding="utf-8"
        )
        outputs[shard.volume_id] = shard_text
        matches = list(_CHAPTER_HEADING.finditer(shard_text))
        handoff_start = matches[-3].start() if len(matches) >= 3 else 0
        previous_handoff_path = (
            task_root
            / "inputs"
            / f"writer-shard-handoff-v{revision:03d}-{shard.volume_id.lower()}.md"
        )
        atomic_write_text(
            previous_handoff_path, shard_text[handoff_start:].strip() + "\n"
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
        "regenerated_volume_ids": sorted(requested_volume_ids or known_volume_ids),
        "reused_volume_ids": sorted(known_volume_ids - requested_volume_ids)
        if requested_volume_ids
        else [],
        "child_attempt_ids": accepted_children,
        "composite_attempt_id": composite_id,
        "blueprint_version_id": story_version_id,
        "blueprint_sha256": story_artifact["sha256"],
        "context_manifest_sha256": context_manifest_sha256,
        "projection": current,
    }
