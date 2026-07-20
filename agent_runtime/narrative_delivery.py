"""Deterministic delivery protocol for longform narrative tasks."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
import re

import yaml


REQUIRED_REVIEW_GATES = [
    "continuity",
    "character_state",
    "timeline",
    "pov",
    "style",
    "scene_goal",
    "chapter_hook",
    "word_count",
]

LIGHT_CHAPTER_DELIVERY_FILES = [
    "chapter_packet.yml",
    "fiction_draft.md",
    "continuity_ledger.yml",
    "state_transition_proposal.yml",
]

LIGHT_CHAPTER_RECEIPT_FILES = [
    *LIGHT_CHAPTER_DELIVERY_FILES,
    "narrative_delivery_receipt.yml",
]

HEAVY_CHAPTER_PREFLIGHT_FILES = [
    *LIGHT_CHAPTER_DELIVERY_FILES,
    "fiction_review.yml",
    "artifact_lineage.yml",
]

HEAVY_CHAPTER_DELIVERY_FILES = [
    *LIGHT_CHAPTER_RECEIPT_FILES,
    "fiction_review.yml",
    "artifact_lineage.yml",
]

REQUIRED_DELIVERY_FILES = LIGHT_CHAPTER_DELIVERY_FILES

CORE_CHAPTER_OUTLINE_KEYWORDS = (
    "00_世界史诗编年史",
    "00_重构总纲",
    "01_完整故事蓝图",
    "02_卷纲与章节路线",
    "03_感情戏执行准则",
)
VOLUME_OUTLINE_KEYWORDS = (
    (1, 60, "卷纲_第一卷"),
    (61, 130, "卷纲_第二卷"),
    (131, 200, "卷纲_第三卷"),
)
PHASE_PROGRESS_ROLES = ("setup", "escalation", "complication", "reversal", "payoff")
FORESHADOWING_TARGET_BY_ROLE = {
    "setup": "introduce",
    "escalation": "touch",
    "complication": "escalate",
    "reversal": "touch_or_reframe",
    "payoff": "payoff_or_explicitly_defer",
}
PHASE_HEADING_PATTERN = re.compile(
    r"^###\s*0*(\d+)\s*[-–—]\s*0*(\d+)\s*章?\s*[：:]\s*(.+)$"
)
CHAPTER_BEAT_PATTERN = re.compile(r"^-\s*0*(\d+)\s*[：:]\s*(.+)$")
CHAPTER_STATE_PLAN_REQUIRED_FIELDS = (
    "chapter",
    "title",
    "volume",
    "phase",
    "timeline_slot",
    "pov",
    "opening_state",
    "scene_goal",
    "irreversible_plot_change",
    "character_state_change",
    "relationship_or_worldline_change",
    "foreshadowing_action",
    "closing_state",
    "must_not_repeat",
)


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or default
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _project_root(root: Path, project: str) -> Path:
    return Path(root) / "projects" / project


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _collect(project_root: Path, patterns: list[str], limit: int = 50) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        for path in sorted(project_root.glob(pattern)):
            if len(found) >= limit:
                return found
            if path.is_file():
                found.append(_rel(path, project_root))
    return found


def _chapter_number(path: Path) -> int | None:
    text = path.name
    patterns = [
        r"第\s*0*(\d+)\s*章",
        r"chapter[_\s-]*0*(\d+)",
        r"ch[_\s-]*0*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def _select_outline_refs(outline_refs: list[str], chapter: int) -> list[str]:
    volume_keyword = next(
        (keyword for start, end, keyword in VOLUME_OUTLINE_KEYWORDS if start <= chapter <= end),
        None,
    )
    selected = [
        ref
        for ref in outline_refs
        if any(keyword in Path(ref).name for keyword in CORE_CHAPTER_OUTLINE_KEYWORDS)
        or (volume_keyword is not None and volume_keyword in Path(ref).name)
        or (chapter >= 181 and "04_续作钩子与未完结属性" in Path(ref).name)
    ]
    return selected or outline_refs[:8]


def _clean_outline_text(value: str) -> str:
    return value.replace("**", "").strip()


def _resolve_chapter_state_plan(project_root: Path, plan_ref: str) -> tuple[Path, dict[str, Any]]:
    ref = str(plan_ref or "").strip()
    if not ref or Path(ref).is_absolute():
        raise ValueError("chapter state plan must be a project-relative path")
    project_root = project_root.resolve()
    path = (project_root / ref).resolve()
    if not path.is_relative_to(project_root):
        raise ValueError("chapter state plan must stay inside the project root")
    if not path.is_file():
        raise ValueError(f"chapter state plan does not exist: {ref}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"chapter state plan is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("chapter state plan root must be a mapping")
    return path, data


def _state_plan_story_authority_refs(project_root: Path, plan_ref: str | None) -> list[str]:
    if not plan_ref:
        return []
    _, data = _resolve_chapter_state_plan(project_root, plan_ref)
    refs = data.get("story_authority_refs") or []
    if not isinstance(refs, list):
        raise ValueError("story_authority_refs must be a list")
    resolved_refs: list[str] = []
    project_root = project_root.resolve()
    for item in refs:
        if not isinstance(item, dict):
            raise ValueError("story authority refs must contain path and sha256 mappings")
        ref = str(item.get("path") or "").strip()
        expected_sha256 = str(item.get("sha256") or "").strip().lower()
        if not ref or Path(ref).is_absolute():
            raise ValueError("story authority refs must be project-relative paths")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError(f"story authority ref has invalid sha256: {ref}")
        path = (project_root / ref).resolve()
        if not path.is_relative_to(project_root) or not path.is_file():
            raise ValueError(f"story authority ref is missing or outside the project: {ref}")
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"story authority ref sha256 mismatch: {ref}")
        if ref not in resolved_refs:
            resolved_refs.append(ref)
    return resolved_refs


def _nonempty_plan_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    return value is not None


def _normalized_plan_text(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def validate_chapter_state_plan(
    project_root: Path,
    plan_ref: str,
    *,
    expected_chapters: list[int] | None = None,
) -> dict[str, Any]:
    """Validate a candidate chapter-state plan before any Writer call."""

    issues: list[dict[str, Any]] = []
    try:
        path, data = _resolve_chapter_state_plan(project_root, plan_ref)
    except ValueError as exc:
        return {
            "schema_version": 1,
            "status": "fail",
            "path": str(plan_ref or ""),
            "chapter_count": 0,
            "issues": [{"check": "plan_source", "message": str(exc)}],
        }

    for key, expected in (
        ("schema_version", 1),
        ("project", project_root.name),
        ("status", "candidate"),
        ("candidate_only", True),
        ("production_modified", False),
    ):
        if data.get(key) != expected:
            issues.append(
                {
                    "check": "candidate_boundary",
                    "field": key,
                    "message": f"expected {expected!r}",
                }
            )
    character_ranges: dict[str, list[int]] = {}
    for field in ("target_character_range", "hard_character_range"):
        value = data.get(field)
        valid = (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(item, int) and item > 0 for item in value)
            and value[0] <= value[1]
        )
        if valid:
            character_ranges[field] = value
        else:
            issues.append(
                {
                    "check": "character_range",
                    "field": field,
                    "message": "must be two ascending positive integers",
                }
            )
    target_range = character_ranges.get("target_character_range")
    hard_range = character_ranges.get("hard_character_range")
    if target_range and hard_range and not (
        hard_range[0] <= target_range[0] <= target_range[1] <= hard_range[1]
    ):
        issues.append(
            {
                "check": "character_range",
                "field": "target_character_range",
                "message": "target range must stay inside hard range",
            }
        )

    entries = data.get("chapter_state_plan")
    if not isinstance(entries, list):
        issues.append(
            {
                "check": "plan_shape",
                "field": "chapter_state_plan",
                "message": "must be a list",
            }
        )
        entries = []

    by_chapter: dict[int, dict[str, Any]] = {}
    chapter_sequence: list[int] = []
    seen_scene_goals: dict[str, int] = {}
    seen_plot_changes: dict[str, int] = {}
    seen_timeline_slots: dict[str, int] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            issues.append(
                {
                    "check": "entry_shape",
                    "entry_index": index,
                    "message": "entry must be a mapping",
                }
            )
            continue
        chapter = entry.get("chapter")
        if not isinstance(chapter, int) or chapter < 1:
            issues.append(
                {
                    "check": "chapter_number",
                    "entry_index": index,
                    "message": "chapter must be a positive integer",
                }
            )
            continue
        chapter_sequence.append(chapter)
        if chapter in by_chapter:
            issues.append(
                {
                    "check": "unique_chapter",
                    "chapter": chapter,
                    "message": "duplicate chapter entry",
                }
            )
            continue
        by_chapter[chapter] = entry
        for field in CHAPTER_STATE_PLAN_REQUIRED_FIELDS:
            value = entry.get(field)
            field_type_valid = (
                isinstance(value, int)
                if field == "chapter"
                else isinstance(value, (str, list))
                if field == "must_not_repeat"
                else isinstance(value, str)
            )
            if not field_type_valid or not _nonempty_plan_value(value):
                issues.append(
                    {
                        "check": "required_field",
                        "chapter": chapter,
                        "field": field,
                        "message": "missing or empty",
                    }
                )
        for field, seen in (
            ("scene_goal", seen_scene_goals),
            ("irreversible_plot_change", seen_plot_changes),
        ):
            normalized = _normalized_plan_text(entry.get(field))
            if not normalized:
                continue
            if normalized in seen:
                issues.append(
                    {
                        "check": f"unique_{field}",
                        "chapter": chapter,
                        "source_chapter": seen[normalized],
                        "message": f"duplicate {field}",
                    }
                )
            else:
                seen[normalized] = chapter

        normalized_timeline = _normalized_plan_text(entry.get("timeline_slot"))
        if normalized_timeline:
            if normalized_timeline in seen_timeline_slots:
                issues.append(
                    {
                        "check": "unique_timeline_slot",
                        "chapter": chapter,
                        "source_chapter": seen_timeline_slots[normalized_timeline],
                        "message": "duplicate timeline_slot",
                    }
                )
            else:
                seen_timeline_slots[normalized_timeline] = chapter
        opening_state = _normalized_plan_text(entry.get("opening_state"))
        closing_state = _normalized_plan_text(entry.get("closing_state"))
        if opening_state and opening_state == closing_state:
            issues.append(
                {
                    "check": "state_transition",
                    "chapter": chapter,
                    "message": "opening_state and closing_state must differ",
                }
            )

    if by_chapter:
        first_chapter = min(by_chapter)
        last_chapter = max(by_chapter)
        expected_sequence = list(range(first_chapter, last_chapter + 1))
        if chapter_sequence != expected_sequence:
            issues.append(
                {
                    "check": "ordered_contiguous_chapters",
                    "message": (
                        f"chapter entries must be ordered exactly {first_chapter}-"
                        f"{last_chapter} with no gaps or extras"
                    ),
                }
            )
        if data.get("chapter_range") != [first_chapter, last_chapter]:
            issues.append(
                {
                    "check": "chapter_range",
                    "field": "chapter_range",
                    "message": f"expected [{first_chapter}, {last_chapter}]",
                }
            )

    validation_contract = data.get("validation_contract")
    if not isinstance(validation_contract, dict):
        issues.append(
            {
                "check": "validation_contract",
                "message": "must be a mapping",
            }
        )
    else:
        expected_contract = {
            "exact_chapter_count": len(by_chapter),
            "ordered_unique_chapters": True,
            "unique_scene_goals": True,
            "unique_irreversible_plot_changes": True,
            "monotonic_story_state": True,
        }
        for field, expected in expected_contract.items():
            if validation_contract.get(field) != expected:
                issues.append(
                    {
                        "check": "validation_contract",
                        "field": field,
                        "message": f"expected {expected!r}",
                    }
                )

    selected = list(expected_chapters or [])
    for chapter in selected:
        if chapter not in by_chapter:
            issues.append(
                {
                    "check": "selected_chapter_present",
                    "chapter": chapter,
                    "message": "selected chapter is absent from plan",
                }
            )

    return {
        "schema_version": 1,
        "status": "pass" if not issues else "fail",
        "path": _rel(path, project_root),
        "chapter_count": len(by_chapter),
        "selected_chapter_count": len(selected),
        "issues": issues,
    }


def write_narrative_planner_validation(
    project_root: Path,
    run_dir: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a planner result against its run-local rewrite contract."""

    project_root = Path(project_root).resolve()
    run_dir = Path(run_dir).resolve()
    output_path = Path(output_path or run_dir / "chapter_state_plan.yml").resolve()
    contract_path = run_dir / "narrative_rewrite_contract.yml"
    contract_issue: dict[str, Any] | None = None
    try:
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        contract = {}
    chapter_range = contract.get("chapter_range") if isinstance(contract, dict) else None
    if (
        isinstance(chapter_range, list)
        and len(chapter_range) == 2
        and all(type(item) is int and item > 0 for item in chapter_range)
        and chapter_range[0] <= chapter_range[1]
    ):
        expected_chapters = list(range(chapter_range[0], chapter_range[1] + 1))
    else:
        expected_chapters = []
        contract_issue = {
            "check": "narrative_rewrite_contract",
            "message": "missing or invalid chapter_range",
        }
    try:
        plan_ref = output_path.relative_to(project_root).as_posix()
    except ValueError:
        plan_ref = ""
        contract_issue = {
            "check": "planner_output_path",
            "message": "chapter_state_plan.yml must stay inside the project root",
        }

    validation = validate_chapter_state_plan(
        project_root,
        plan_ref,
        expected_chapters=expected_chapters,
    )
    if contract_issue is not None:
        validation["status"] = "fail"
        validation.setdefault("issues", []).append(contract_issue)
    _write_yaml(run_dir / "narrative_planner_validation.yml", validation)
    return validation


def narrative_planner_validation_issues(validation: dict[str, Any]) -> list[str]:
    """Render bounded gate issues from a planner validation receipt."""

    if validation.get("status") == "pass":
        return []
    rendered = [
        "NarrativePlanner validation failed: "
        f"{issue.get('check', 'unknown')}: {issue.get('message', 'invalid chapter state plan')}"
        for issue in (validation.get("issues") or [])[:20]
        if isinstance(issue, dict)
    ]
    return rendered or ["NarrativePlanner validation failed"]


def _chapter_intent_from_state_plan(
    project_root: Path,
    plan_ref: str,
    chapter: int,
) -> dict[str, Any]:
    validation = validate_chapter_state_plan(
        project_root,
        plan_ref,
        expected_chapters=[chapter],
    )
    if validation["status"] != "pass":
        first = validation["issues"][0] if validation["issues"] else {}
        raise ValueError(
            "chapter state plan failed validation: "
            f"{first.get('check', 'unknown')}: {first.get('message', 'unknown issue')}"
        )
    _path, data = _resolve_chapter_state_plan(project_root, plan_ref)
    entry = next(
        item
        for item in data["chapter_state_plan"]
        if isinstance(item, dict) and item.get("chapter") == chapter
    )
    must_not_repeat = entry["must_not_repeat"]
    if isinstance(must_not_repeat, str):
        must_not_repeat = [must_not_repeat]
    return {
        "status": "planned",
        "chapter": chapter,
        "source": validation["path"],
        "source_kind": "candidate_chapter_state_plan",
        "volume": entry["volume"],
        "phase": entry["phase"],
        "title": entry["title"],
        "emotional_target": entry["scene_goal"],
        "plot_state_change": entry["irreversible_plot_change"],
        "character_state_change": entry["character_state_change"],
        "relationship_or_worldline_progress": entry["relationship_or_worldline_change"],
        "foreshadowing_to_introduce_or_payoff": entry["foreshadowing_action"],
        "timeline_position": entry["timeline_slot"],
        "beat_plan": {
            "required_chapter_beat": entry["scene_goal"],
            "opening_state": entry["opening_state"],
            "closing_state": entry["closing_state"],
            "pov": entry["pov"],
            "must_not_repeat": must_not_repeat,
            "progression_role": "chapter_specific",
            "constraints": [
                "deliver the declared irreversible plot change",
                "open from the declared opening state and end in the declared closing state",
                "do not repeat any event or scene named in must_not_repeat",
                "do not copy substantive prose from previous candidate chapters",
                "preserve monotonic timeline, injury, knowledge, location, death, and possession state",
            ],
        },
        "target_character_range": data.get("target_character_range", [4500, 5500]),
        "hard_character_range": data.get("hard_character_range", [3000, 8000]),
    }


def _outline_phase_for_chapter(path: Path, chapter: int) -> dict[str, Any] | None:
    current_volume = "unspecified volume"
    phase: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("## ") and not line.startswith("### "):
            if phase is not None:
                break
            current_volume = _clean_outline_text(line[3:])
            continue

        phase_match = PHASE_HEADING_PATTERN.match(line)
        if phase_match:
            if phase is not None:
                break
            start, end = int(phase_match.group(1)), int(phase_match.group(2))
            if start <= chapter <= end:
                phase = {
                    "start": start,
                    "end": end,
                    "title": _clean_outline_text(phase_match.group(3)),
                    "volume": current_volume,
                    "chapter_beats": {},
                    "phase_outcomes": [],
                }
            continue

        if phase is None:
            continue
        beat_match = CHAPTER_BEAT_PATTERN.match(line)
        if beat_match:
            beat_chapter = int(beat_match.group(1))
            beat = _clean_outline_text(beat_match.group(2))
            phase["chapter_beats"][beat_chapter] = beat
            phase["phase_outcomes"].append(f"Chapter {beat_chapter}: {beat}")
        elif line.startswith("- "):
            phase["phase_outcomes"].append(_clean_outline_text(line[2:]))
    return phase


def _build_chapter_intent(project_root: Path, outline_refs: list[str], chapter: int) -> dict[str, Any]:
    ordered_refs = sorted(
        outline_refs,
        key=lambda ref: (0 if "章节路线" in Path(ref).name else 1, ref),
    )
    phase = None
    source = None
    for ref in ordered_refs:
        candidate = _outline_phase_for_chapter(project_root / ref, chapter)
        if candidate is not None:
            phase = candidate
            source = ref
            break

    if phase is None:
        return {
            "status": "generic_fallback",
            "chapter": chapter,
            "source": ordered_refs[0] if ordered_refs else None,
            "source_kind": "outline_without_parseable_chapter_range",
            "emotional_target": "Create one chapter-specific emotional turn with a changed pressure state.",
            "plot_state_change": "Advance one concrete and irreversible plot state.",
            "character_state_change": "Show one observable choice, cost, or capability change.",
            "relationship_or_worldline_progress": "Advance one relationship, faction, or worldline state.",
            "foreshadowing_to_introduce_or_payoff": "touch_only_supported_seed",
            "timeline_position": f"chapter {chapter}; preserve monotonic continuity",
            "beat_plan": {
                "required_chapter_beat": "derive from the selected authoritative outline",
                "phase_outcomes": [],
                "progression_role": "chapter_specific",
                "constraints": [
                    "do not invent an unsupported phase payoff",
                    "do not copy substantive prose from the previous candidate chapter",
                ],
            },
            "target_character_range": [4500, 5500],
            "hard_character_range": [3000, 8000],
        }

    start = int(phase["start"])
    end = int(phase["end"])
    position = chapter - start + 1
    total = end - start + 1
    role_index = min(len(PHASE_PROGRESS_ROLES) - 1, ((position - 1) * len(PHASE_PROGRESS_ROLES)) // total)
    progression_role = PHASE_PROGRESS_ROLES[role_index]
    chapter_beat = phase["chapter_beats"].get(chapter)
    outcomes = list(phase["phase_outcomes"])
    anchor_index = min(len(outcomes) - 1, ((position - 1) * len(outcomes)) // total) if outcomes else 0
    phase_anchor = chapter_beat or (outcomes[anchor_index] if outcomes else phase["title"])
    source_kind = "exact_chapter_beat" if chapter_beat else "chapter_range_phase"
    return {
        "status": "planned",
        "chapter": chapter,
        "source": source,
        "source_kind": source_kind,
        "volume": phase["volume"],
        "phase": phase["title"],
        "phase_range": [start, end],
        "phase_position": {
            "index": position,
            "total": total,
            "progression_role": progression_role,
        },
        "emotional_target": (
            f"Make '{phase['title']}' feel like a {progression_role} turn and end with changed pressure."
        ),
        "plot_state_change": (
            chapter_beat
            or f"Advance one distinct {progression_role} step toward this phase anchor: {phase_anchor}"
        ),
        "character_state_change": (
            "Show an observable choice, cost, belief shift, or capability change caused by the plot turn."
        ),
        "relationship_or_worldline_progress": (
            "Advance one relationship, faction, or worldline state without resolving a later phase beat early."
        ),
        "foreshadowing_to_introduce_or_payoff": FORESHADOWING_TARGET_BY_ROLE[progression_role],
        "timeline_position": (
            f"{phase['volume']}; {phase['title']}; chapter {chapter} of range {start}-{end}; slot {position}/{total}"
        ),
        "beat_plan": {
            "required_chapter_beat": phase_anchor,
            "phase_outcomes": outcomes,
            "progression_role": progression_role,
            "constraints": [
                "deliver one distinct state transition",
                "do not repeat the previous candidate chapter's resolved beat",
                "do not copy substantive prose from the previous candidate chapter",
                "do not resolve later phase outcomes early",
            ],
        },
        "target_character_range": [4500, 5500],
        "hard_character_range": [3000, 8000],
    }


def _is_fiction_route(route: dict[str, Any]) -> bool:
    route_data = route.get("route") if isinstance(route.get("route"), dict) else route
    if route_data.get("route_key") in {"narrative_light_chapter", "fiction_chapter_pipeline"}:
        return True
    agents = route_data.get("agents") or []
    return all(agent in agents for agent in ("Writer", "Reviewer", "Scribe"))


def _delivery_files_for_run(run_dir: Path, *, include_receipt: bool = True) -> list[str]:
    workflow = _read_yaml(run_dir / "workflow_plan.yml", {}) or {}
    route_data = workflow.get("route") if isinstance(workflow.get("route"), dict) else workflow
    if isinstance(route_data, dict) and route_data.get("route_key") == "fiction_chapter_pipeline":
        return HEAVY_CHAPTER_DELIVERY_FILES if include_receipt else HEAVY_CHAPTER_PREFLIGHT_FILES
    agents = route_data.get("agents") if isinstance(route_data, dict) else []
    if isinstance(agents, list) and all(agent in agents for agent in ("Writer", "Reviewer", "Scribe")):
        return HEAVY_CHAPTER_DELIVERY_FILES if include_receipt else HEAVY_CHAPTER_PREFLIGHT_FILES
    return LIGHT_CHAPTER_RECEIPT_FILES if include_receipt else LIGHT_CHAPTER_DELIVERY_FILES


def _is_revision_like(text: str) -> bool:
    return bool(re.search(r"(write|chapter|fiction|novel|revise|rewrite|撰写|章节|小说|重写|修改)", text or "", re.I))


def is_narrative_run(run_dir: Path) -> bool:
    workflow = _read_yaml(run_dir / "workflow_plan.yml", {}) or {}
    if isinstance(workflow, dict):
        route_data = workflow.get("route") if isinstance(workflow.get("route"), dict) else workflow
        if isinstance(route_data, dict) and route_data.get("route_key"):
            return _is_fiction_route(workflow)
    prompt_path = run_dir / "user_request.md"
    prompt = prompt_path.read_text(encoding="utf-8", errors="replace") if prompt_path.exists() else ""
    return _is_revision_like(prompt)


def build_chapter_packet(
    root: Path,
    project: str,
    task_id: str,
    chapter: int,
    *,
    baseline_mode: str = "current",
    previous_chapters: list[str] | None = None,
    deprecated_sources: list[str] | None = None,
    candidate_fact_ledger: str | None = None,
    chapter_state_plan: str | None = None,
) -> dict[str, Any]:
    project_root = _project_root(root, project)
    run_rel = f"runs/{task_id}"
    bible_refs = _collect(project_root, ["production/bible/**/*.md"], limit=20)
    outline_refs = _select_outline_refs(_collect(project_root, ["production/outlines/**/*.md"], limit=20), chapter)
    manuscript_refs = _collect(project_root, ["production/manuscript/**/*.md"], limit=200)
    if baseline_mode in {"reset", "continuation", "candidate_continuation"}:
        resolved_previous_chapters = list(previous_chapters or [])
    else:
        resolved_previous_chapters = [
            ref
            for ref in manuscript_refs
            if (num := _chapter_number(project_root / ref)) is not None and num < chapter
        ]
        resolved_previous_chapters = sorted(resolved_previous_chapters, key=lambda ref: _chapter_number(project_root / ref) or 0)
    chapter_intent = (
        _chapter_intent_from_state_plan(project_root, chapter_state_plan, chapter)
        if chapter_state_plan
        else _build_chapter_intent(project_root, outline_refs, chapter)
    )
    candidate_story_authority_refs = _state_plan_story_authority_refs(project_root, chapter_state_plan)
    packet = {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "chapter": chapter,
        "baseline_mode": baseline_mode,
        "continuity_source_kind": (
            "reset_snapshot"
            if baseline_mode == "reset"
            else "candidate_run"
            if baseline_mode in {"continuation", "candidate_continuation"}
            else "production_manuscript"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_of_truth": {
            "fact_snapshot": "project_brain/project_fact_snapshot.yml",
            "artifact_index": "project_artifact_index.yml",
            "production_root": "production/",
            "candidate_chapter_state_plan": chapter_state_plan,
        },
        "chapter_intent": chapter_intent,
        "must_read": [
            "project_brain/project_fact_snapshot.yml",
            "project_artifact_index.yml",
            *bible_refs,
            *outline_refs,
            *([chapter_state_plan] if chapter_state_plan else []),
            *candidate_story_authority_refs,
            *([candidate_fact_ledger] if candidate_fact_ledger else []),
            *resolved_previous_chapters[-3:],
        ],
        "story_authority": {
            "bible_refs": bible_refs,
            "outline_refs": outline_refs,
            "candidate_refs": candidate_story_authority_refs,
            "previous_chapters": resolved_previous_chapters[-3:],
            "candidate_fact_ledger": candidate_fact_ledger,
            "candidate_chapter_state_plan": chapter_state_plan,
        },
        "previous_chapters": resolved_previous_chapters[-3:],
        "previous_candidate_sources": resolved_previous_chapters[-3:],
        "deprecated_sources": list(deprecated_sources or []),
        "required_outputs": list(LIGHT_CHAPTER_DELIVERY_FILES) + ["narrative_delivery_receipt.yml"],
        "quality_gates": list(REQUIRED_REVIEW_GATES),
        "allowed_output_files": [
            f"{run_rel}/fiction_draft.md",
            f"{run_rel}/continuity_ledger.yml",
            f"{run_rel}/state_transition_proposal.yml",
            f"{run_rel}/narrative_delivery_receipt.yml",
        ],
    }
    return packet


def write_chapter_packet(
    root: Path,
    project: str,
    task_id: str,
    chapter: int,
    *,
    baseline_mode: str = "current",
    previous_chapters: list[str] | None = None,
    deprecated_sources: list[str] | None = None,
    candidate_fact_ledger: str | None = None,
    chapter_state_plan: str | None = None,
) -> dict[str, Any]:
    packet = build_chapter_packet(
        root,
        project,
        task_id,
        chapter,
        baseline_mode=baseline_mode,
        previous_chapters=previous_chapters,
        deprecated_sources=deprecated_sources,
        candidate_fact_ledger=candidate_fact_ledger,
        chapter_state_plan=chapter_state_plan,
    )
    path = _project_root(root, project) / "runs" / task_id / "chapter_packet.yml"
    _write_yaml(path, packet)
    return {"status": "written", "path": f"projects/{project}/runs/{task_id}/chapter_packet.yml", "packet": packet}


def validate_narrative_delivery(run_dir: Path, *, include_receipt: bool = True) -> dict[str, Any]:
    run_dir = Path(run_dir)
    if not is_narrative_run(run_dir):
        return {"valid": True, "skipped": True, "reason": "not a narrative run", "issues": []}

    issues: list[dict[str, str]] = []
    required_files = _delivery_files_for_run(run_dir, include_receipt=include_receipt)
    for filename in required_files:
        if not (run_dir / filename).exists():
            issues.append({"severity": "error", "check": "delivery_file_present", "file": filename, "message": f"missing {filename}"})

    review_path = run_dir / "fiction_review.yml"
    review = _read_yaml(review_path, {}) or {}
    if review_path.exists() and isinstance(review, dict):
        verdict = str(review.get("verdict") or "").lower()
        if bool(review.get("blocking")) or verdict in {"fail", "failed", "rejected", "needs_revision"}:
            issues.append({
                "severity": "error",
                "check": "fiction_review_blocking",
                "file": "fiction_review.yml",
                "message": "fiction review blocks archive/promotion",
            })
        gates = review.get("gates") or {}
        if not isinstance(gates, dict):
            issues.append({"severity": "error", "check": "fiction_review_gates", "file": "fiction_review.yml", "message": "gates must be a mapping"})
        else:
            for gate in REQUIRED_REVIEW_GATES:
                if gate not in gates:
                    issues.append({
                        "severity": "warning",
                        "check": "fiction_review_gate_present",
                        "file": "fiction_review.yml",
                        "message": f"missing review gate: {gate}",
                    })

    return {
        "valid": not any(issue["severity"] == "error" for issue in issues),
        "skipped": False,
        "issues": issues,
        "required_files": required_files,
    }


def narrative_delivery_integrity_issues(run_dir: Path) -> list[str]:
    """Fail closed when a delivery receipt is not bound to its chapter artifacts."""
    run_dir = Path(run_dir)
    receipt = _read_yaml(run_dir / "narrative_delivery_receipt.yml", {}) or {}
    artifact_sha256 = receipt.get("artifact_sha256") if isinstance(receipt, dict) else None
    if not isinstance(artifact_sha256, dict):
        return ["predecessor_artifact_hashes_missing"]
    issues: list[str] = []
    for filename in LIGHT_CHAPTER_DELIVERY_FILES:
        path = run_dir / filename
        expected = str(artifact_sha256.get(filename) or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            issues.append(f"predecessor_artifact_hash_missing:{filename}")
        elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            issues.append(f"predecessor_artifact_hash_mismatch:{filename}")
    return issues


def write_narrative_delivery_receipt(run_dir: Path) -> dict[str, Any]:
    result = validate_narrative_delivery(run_dir, include_receipt=False)
    external_required_files = _delivery_files_for_run(Path(run_dir), include_receipt=True)
    artifact_sha256 = {
        filename: hashlib.sha256((Path(run_dir) / filename).read_bytes()).hexdigest()
        for filename in LIGHT_CHAPTER_DELIVERY_FILES
        if (Path(run_dir) / filename).is_file()
    }
    receipt = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if result.get("valid") else "blocked",
        "delivery_check": result,
        "preflight_required_files": result.get("required_files", []),
        "external_required_files": external_required_files,
        "artifact_sha256": artifact_sha256,
    }
    _write_yaml(Path(run_dir) / "narrative_delivery_receipt.yml", receipt)
    return receipt


def run_narrative_doctor(root: Path, project: str) -> dict[str, Any]:
    project_root = _project_root(root, project)
    issues: list[dict[str, str]] = []
    if not project_root.exists():
        return {
            "status": "fail",
            "project": project,
            "issue_count": 1,
            "issues": [{"severity": "error", "check": "project_exists", "message": f"project does not exist: {project}"}],
        }

    for path, check in [
        (project_root / "project_artifact_index.yml", "artifact_index_present"),
        (project_root / "project_brain" / "project_fact_snapshot.yml", "fact_snapshot_present"),
    ]:
        if not path.exists():
            issues.append({"severity": "error", "check": check, "message": f"missing {_rel(path, project_root)}"})

    for pattern, check in [
        ("production/bible/**/*.md", "bible_present"),
        ("production/outlines/**/*.md", "outline_present"),
        ("production/manuscript/**/*.md", "manuscript_present"),
    ]:
        if not _collect(project_root, [pattern], limit=1):
            issues.append({"severity": "error", "check": check, "message": f"missing {pattern}"})

    runs_dir = project_root / "runs"
    if runs_dir.exists():
        for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir())[-30:]:
            if not is_narrative_run(run_dir):
                continue
            if not (run_dir / "chapter_packet.yml").exists():
                issues.append({
                    "severity": "error",
                    "check": "chapter_packet_present",
                    "path": f"projects/{project}/runs/{run_dir.name}",
                    "message": "narrative run is missing chapter_packet.yml",
                })
            if not (run_dir / "narrative_delivery_receipt.yml").exists():
                issues.append({
                    "severity": "error",
                    "check": "narrative_delivery_receipt",
                    "path": f"projects/{project}/runs/{run_dir.name}",
                    "message": "narrative run is missing narrative_delivery_receipt.yml",
                })

    return {
        "status": "fail" if any(issue["severity"] == "error" for issue in issues) else "pass",
        "project": project,
        "issue_count": len(issues),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# v2 thin adapter — creative brief compilation
# ---------------------------------------------------------------------------


def compile_chapter_creative_brief_v2(
    state_plan: dict[str, Any],
    *,
    chapter_id: int | None = None,
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Thin v2 adapter: convert a legacy v1 chapter state plan into a v2
    creative brief.

    Delegates to ``agent_runtime.narrative.production.brief_compiler``.
    Returns a dict with the compiled brief data or ``status: blocked``.
    """
    from agent_runtime.narrative.production.brief_compiler import (
        compile_creative_brief,
        validate_creative_brief,
    )

    try:
        brief = compile_creative_brief(
            state_plan,
            chapter_id=chapter_id,
            source_paths=source_paths,
        )
    except ValueError as exc:
        return {"status": "blocked", "issues": [str(exc)]}

    data = brief.to_dict()
    issues = validate_creative_brief(data)
    return {
        "status": "pass" if not issues else "blocked",
        "creative_brief": data if not issues else None,
        "issues": issues,
    }
