"""Long-form planning contracts and deterministic Crown planning skeletons.

The module creates only range metadata.  It never invents plot, character, or
prose content and therefore can run before any external-model authorization.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import math
from typing import Any


CHAPTER_CONTRACT_SCHEMA = "chapter-contract/v3"
PLAN_BUNDLE_SCHEMA = "longform-plan-bundle/v3"
CHAPTER_POSITIONS = {"series_open", "volume_open", "major_reversal", "regular"}
PLACEHOLDERS = {
    "what_happens_next",
    "what happens next",
    "character_desire_vs_obstacle",
    "character desire vs obstacle",
    "tbd",
    "todo",
    "unknown",
    "placeholder",
}

_DRIVE_FIELDS = (
    "long_horizon_desire",
    "volume_goal",
    "current_goal",
    "self_initiated_move",
    "obstacle",
    "failure_cost",
    "counterfactual_action",
    "desire_delta",
)
_ACTOR_FIELDS = (
    "actor_ref",
    "private_goal",
    "fear_or_constraint",
    "known_information",
    "current_plan",
    "offscreen_action",
    "resource",
    "relationship_stance",
    "state_delta",
)
_HOOK_FIELDS = (
    "disturbance_or_pressure",
    "personal_stakes",
    "next_required_action",
    "reader_question",
)
_FORESHADOW_FIELDS = (
    "foreshadow_id",
    "action",
    "target_window",
    "dependencies",
    "evidence_target",
)
_WORLD_FIELDS = ("axis", "before", "after", "cause", "evidence_target")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _placeholder(value: Any) -> bool:
    return _text(value).casefold() in PLACEHOLDERS


def _require_text_fields(
    value: Any, fields: tuple[str, ...], prefix: str, issues: list[str]
) -> None:
    if not isinstance(value, Mapping):
        issues.append(f"missing:{prefix}")
        return
    for field in fields:
        field_value = value.get(field)
        path = f"{prefix}.{field}"
        if not isinstance(field_value, str) or not field_value.strip():
            issues.append(f"missing:{path}")
        elif _placeholder(field_value):
            issues.append(f"placeholder:{path}")


def validate_chapter_contract(contract: Mapping[str, Any]) -> list[str]:
    """Return deterministic issues for one chapter-contract/v3 document."""

    issues: list[str] = []
    if not isinstance(contract, Mapping):
        return ["contract_root_must_be_mapping"]
    if contract.get("schema_version") != CHAPTER_CONTRACT_SCHEMA:
        issues.append("schema_version_must_be_chapter_contract_v3")
    chapter = contract.get("chapter")
    if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
        issues.append("chapter_must_be_positive_integer")
    position = _text(contract.get("chapter_position"))
    if position not in CHAPTER_POSITIONS:
        issues.append("invalid:chapter_position")
    for field in ("pov", "primary_function", "turn", "cost"):
        value = contract.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"missing:{field}")
        elif _placeholder(value):
            issues.append(f"placeholder:{field}")

    _require_text_fields(
        contract.get("protagonist_drive"),
        _DRIVE_FIELDS,
        "protagonist_drive",
        issues,
    )

    actors = contract.get("supporting_actor_states")
    if not isinstance(actors, list):
        issues.append("missing:supporting_actor_states")
    else:
        seen_actors: set[str] = set()
        for index, actor in enumerate(actors):
            prefix = f"supporting_actor_states[{index}]"
            _require_text_fields(actor, _ACTOR_FIELDS, prefix, issues)
            if isinstance(actor, Mapping):
                actor_ref = _text(actor.get("actor_ref"))
                if actor_ref in seen_actors:
                    issues.append(f"duplicate:{prefix}.actor_ref")
                seen_actors.add(actor_ref)

    _require_text_fields(contract.get("hook_contract"), _HOOK_FIELDS, "hook_contract", issues)

    foreshadows = contract.get("foreshadow_actions")
    if not isinstance(foreshadows, list):
        issues.append("missing:foreshadow_actions")
    else:
        for index, action in enumerate(foreshadows):
            prefix = f"foreshadow_actions[{index}]"
            if not isinstance(action, Mapping):
                issues.append(f"missing:{prefix}")
                continue
            for field in _FORESHADOW_FIELDS:
                value = action.get(field)
                path = f"{prefix}.{field}"
                if field == "target_window":
                    if not (
                        isinstance(value, list)
                        and len(value) == 2
                        and all(
                            isinstance(item, int) and not isinstance(item, bool) and item > 0
                            for item in value
                        )
                        and value[0] <= value[1]
                    ):
                        issues.append(f"invalid:{path}")
                elif field == "dependencies":
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) and item.strip() for item in value
                    ):
                        issues.append(f"invalid:{path}")
                elif not isinstance(value, str) or not value.strip():
                    issues.append(f"missing:{path}")
                elif _placeholder(value):
                    issues.append(f"placeholder:{path}")

    world_delta = contract.get("world_state_delta")
    if "world_state_delta" not in contract:
        issues.append("missing:world_state_delta")
    elif world_delta is not None:
        _require_text_fields(world_delta, _WORLD_FIELDS, "world_state_delta", issues)
        if isinstance(world_delta, Mapping) and _text(world_delta.get("before")) == _text(
            world_delta.get("after")
        ):
            issues.append("invalid:world_state_delta.no_change")
    return sorted(set(issues))


def _macro_arc_ranges(
    *, volume_id: str, chapter_start: int, chapter_end: int, arc_count: int = 15
) -> list[dict[str, Any]]:
    total = chapter_end - chapter_start + 1
    arcs: list[dict[str, Any]] = []
    previous_end = chapter_start - 1
    for index in range(1, arc_count + 1):
        arc_end = chapter_start - 1 + math.floor(index * total / arc_count)
        arc_start = previous_end + 1
        arcs.append(
            {
                "arc_id": f"{volume_id}-arc-{index:02d}",
                "volume_id": volume_id,
                "chapter_range": [arc_start, arc_end],
                "semantic_review_required": True,
                "required_state_changes": [
                    "character_desire_delta",
                    "world_axis_delta",
                    "major_reversal",
                ],
            }
        )
        previous_end = arc_end
    return arcs


def _planning_windows(
    macro_arcs: list[dict[str, Any]], *, max_chapters: int = 10
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for arc in macro_arcs:
        start, end = arc["chapter_range"]
        ordinal = 1
        cursor = start
        while cursor <= end:
            window_end = min(cursor + max_chapters - 1, end)
            windows.append(
                {
                    "window_id": f"{arc['arc_id']}-window-{ordinal:02d}",
                    "arc_id": arc["arc_id"],
                    "volume_id": arc["volume_id"],
                    "chapter_range": [cursor, window_end],
                    "external_model_authorization_required": True,
                    "prose_generation_allowed": False,
                }
            )
            cursor = window_end + 1
            ordinal += 1
    return windows


def build_crown_planning_skeleton() -> dict[str, Any]:
    """Build the authorized deterministic 1980-chapter range skeleton only."""

    volumes = [
        {"volume_id": "part-1", "chapter_range": [1, 650], "supervisor_review_required": True},
        {"volume_id": "part-2", "chapter_range": [651, 1310], "supervisor_review_required": True},
        {"volume_id": "part-3", "chapter_range": [1311, 1980], "supervisor_review_required": True},
    ]
    macro_arcs = [
        arc
        for volume in volumes
        for arc in _macro_arc_ranges(
            volume_id=volume["volume_id"],
            chapter_start=volume["chapter_range"][0],
            chapter_end=volume["chapter_range"][1],
        )
    ]
    return {
        "schema_version": PLAN_BUNDLE_SCHEMA,
        "project": "Crown_of_Ash",
        "planning_stage": "structure_only",
        "status": "candidate",
        "candidate_only": True,
        "production_modified": False,
        "planned_total_chapters": 1980,
        "model_calls_authorized": False,
        "prose_generation_allowed": False,
        "volumes": volumes,
        "macro_arcs": macro_arcs,
        "planning_windows": _planning_windows(macro_arcs),
        "chapter_contracts": [],
        "review_policy": {
            "deterministic_validation_every_chapter": True,
            "independent_macro_arc_reviews": 45,
            "volume_supervisor_reviews": 3,
            "promotion": "single_atomic_after_full_audit_and_user_acceptance",
        },
    }


def _contiguous_ranges(
    records: list[Mapping[str, Any]], expected_start: int, expected_end: int
) -> bool:
    cursor = expected_start
    for record in records:
        chapter_range = record.get("chapter_range")
        if not (
            isinstance(chapter_range, list)
            and len(chapter_range) == 2
            and all(isinstance(item, int) and not isinstance(item, bool) for item in chapter_range)
            and chapter_range[0] == cursor
            and chapter_range[0] <= chapter_range[1]
        ):
            return False
        cursor = chapter_range[1] + 1
    return cursor == expected_end + 1


def validate_longform_plan_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structural scale, review density, and optional full contracts."""

    issues: list[str] = []
    if not isinstance(bundle, Mapping):
        return {"schema_version": 1, "status": "fail", "issues": ["bundle_root_must_be_mapping"]}
    expected_scalars = {
        "schema_version": PLAN_BUNDLE_SCHEMA,
        "status": "candidate",
        "candidate_only": True,
        "production_modified": False,
        "planned_total_chapters": 1980,
        "model_calls_authorized": False,
        "prose_generation_allowed": False,
    }
    for field, expected in expected_scalars.items():
        if bundle.get(field) != expected:
            issues.append(f"invalid:{field}")

    volumes = bundle.get("volumes")
    if not isinstance(volumes, list) or len(volumes) != 3:
        issues.append("invalid:volumes")
        volumes = []
    elif not _contiguous_ranges(volumes, 1, 1980):
        issues.append("invalid:volume_ranges")

    arcs = bundle.get("macro_arcs")
    if not isinstance(arcs, list) or len(arcs) != 45:
        issues.append("invalid:macro_arcs")
        arcs = []
    elif not _contiguous_ranges(arcs, 1, 1980):
        issues.append("invalid:macro_arc_ranges")
    if arcs:
        counts = Counter(_text(arc.get("volume_id")) for arc in arcs)
        if counts != {"part-1": 15, "part-2": 15, "part-3": 15}:
            issues.append("invalid:macro_arcs_per_volume")

    windows = bundle.get("planning_windows")
    if not isinstance(windows, list) or len(windows) != 225:
        issues.append("invalid:planning_windows")
        windows = []
    else:
        by_arc: dict[str, list[Mapping[str, Any]]] = {}
        for window in windows:
            if not isinstance(window, Mapping):
                issues.append("invalid:planning_window_record")
                continue
            by_arc.setdefault(_text(window.get("arc_id")), []).append(window)
            chapter_range = window.get("chapter_range")
            if isinstance(chapter_range, list) and len(chapter_range) == 2:
                if chapter_range[1] - chapter_range[0] + 1 > 10:
                    issues.append(f"invalid:window_too_large:{window.get('window_id')}")
        for arc in arcs:
            start, end = arc["chapter_range"]
            if not _contiguous_ranges(by_arc.get(arc["arc_id"], []), start, end):
                issues.append(f"invalid:window_coverage:{arc['arc_id']}")

    contracts = bundle.get("chapter_contracts")
    if not isinstance(contracts, list):
        issues.append("invalid:chapter_contracts")
    elif bundle.get("planning_stage") == "chapter_contracts_complete":
        chapters = [item.get("chapter") for item in contracts if isinstance(item, Mapping)]
        if chapters != list(range(1, 1981)):
            issues.append("invalid:complete_chapter_contract_range")
        for contract in contracts:
            issues.extend(
                f"chapter:{contract.get('chapter')}:{issue}"
                for issue in validate_chapter_contract(contract)
            )

    review = bundle.get("review_policy")
    if not isinstance(review, Mapping):
        issues.append("invalid:review_policy")
    else:
        expected_review = {
            "deterministic_validation_every_chapter": True,
            "independent_macro_arc_reviews": 45,
            "volume_supervisor_reviews": 3,
            "promotion": "single_atomic_after_full_audit_and_user_acceptance",
        }
        for field, expected in expected_review.items():
            if review.get(field) != expected:
                issues.append(f"invalid:review_policy.{field}")
    return {
        "schema_version": 1,
        "status": "pass" if not issues else "fail",
        "chapter_contract_count": len(contracts) if isinstance(contracts, list) else 0,
        "issues": sorted(set(issues)),
    }


def validate_chapter_state_plan_v3_document(
    data: Mapping[str, Any],
    *,
    path: str,
    expected_project: str,
    expected_chapters: list[int] | None = None,
) -> dict[str, Any]:
    """Validate the v3 document wrapper used by existing delivery entrypoints."""

    issues: list[dict[str, Any]] = []
    expected_boundary = {
        "schema_version": 3,
        "contract_version": CHAPTER_CONTRACT_SCHEMA,
        "project": expected_project,
        "status": "candidate",
        "candidate_only": True,
        "production_modified": False,
    }
    for field, expected in expected_boundary.items():
        if data.get(field) != expected:
            issues.append(
                {
                    "check": "candidate_boundary",
                    "field": field,
                    "message": f"expected {expected!r}",
                }
            )
    entries = data.get("chapter_state_plan")
    if not isinstance(entries, list):
        entries = []
        issues.append(
            {
                "check": "plan_shape",
                "field": "chapter_state_plan",
                "message": "must be a list",
            }
        )
    chapters: list[int] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            issues.append({"check": "entry_shape", "message": "entry must be a mapping"})
            continue
        chapter = entry.get("chapter")
        if isinstance(chapter, int) and not isinstance(chapter, bool):
            chapters.append(chapter)
        for issue in validate_chapter_contract(entry):
            issues.append(
                {
                    "check": "chapter_contract_v3",
                    "chapter": chapter,
                    "message": issue,
                }
            )
    if chapters:
        expected_sequence = list(range(chapters[0], chapters[-1] + 1))
        if chapters != expected_sequence:
            issues.append(
                {
                    "check": "ordered_contiguous_chapters",
                    "message": "chapter entries must be ordered and contiguous",
                }
            )
        if data.get("chapter_range") != [chapters[0], chapters[-1]]:
            issues.append(
                {
                    "check": "chapter_range",
                    "message": f"expected {[chapters[0], chapters[-1]]!r}",
                }
            )
    for chapter in expected_chapters or []:
        if chapter not in chapters:
            issues.append(
                {
                    "check": "selected_chapter_present",
                    "chapter": chapter,
                    "message": "selected chapter is absent from plan",
                }
            )
    return {
        "schema_version": 3,
        "status": "pass" if not issues else "fail",
        "path": path,
        "chapter_count": len(chapters),
        "selected_chapter_count": len(expected_chapters or []),
        "issues": issues,
    }


__all__ = [
    "CHAPTER_CONTRACT_SCHEMA",
    "PLAN_BUNDLE_SCHEMA",
    "build_crown_planning_skeleton",
    "validate_chapter_contract",
    "validate_chapter_state_plan_v3_document",
    "validate_longform_plan_bundle",
]
