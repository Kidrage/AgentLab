"""Deterministic delivery protocol for longform narrative tasks."""

from __future__ import annotations

from datetime import datetime, timezone
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
                "constraints": ["do not invent an unsupported phase payoff"],
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
        },
        "chapter_intent": _build_chapter_intent(project_root, outline_refs, chapter),
        "must_read": [
            "project_brain/project_fact_snapshot.yml",
            "project_artifact_index.yml",
            *bible_refs,
            *outline_refs,
            *([candidate_fact_ledger] if candidate_fact_ledger else []),
            *resolved_previous_chapters[-3:],
        ],
        "story_authority": {
            "bible_refs": bible_refs,
            "outline_refs": outline_refs,
            "previous_chapters": resolved_previous_chapters[-3:],
            "candidate_fact_ledger": candidate_fact_ledger,
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


def write_narrative_delivery_receipt(run_dir: Path) -> dict[str, Any]:
    result = validate_narrative_delivery(run_dir, include_receipt=False)
    external_required_files = _delivery_files_for_run(Path(run_dir), include_receipt=True)
    receipt = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if result.get("valid") else "blocked",
        "delivery_check": result,
        "preflight_required_files": result.get("required_files", []),
        "external_required_files": external_required_files,
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
