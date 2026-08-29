"""Deterministic long-term narrative state validation and projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
import re

PROMISE_STATES = (
    "latent",
    "seeded",
    "reinforced",
    "misinterpreted",
    "activated",
    "partially_revealed",
    "paid_off",
    "transformed",
    "retired",
)

PROMISE_TRANSITIONS = {
    "latent": {"seeded", "retired"},
    "seeded": {"reinforced", "misinterpreted", "activated", "retired"},
    "reinforced": {
        "misinterpreted",
        "activated",
        "partially_revealed",
        "retired",
    },
    "misinterpreted": {"reinforced", "activated", "partially_revealed"},
    "activated": {"partially_revealed", "paid_off", "transformed"},
    "partially_revealed": {
        "reinforced",
        "activated",
        "paid_off",
        "transformed",
    },
    "paid_off": {"transformed", "retired"},
    "transformed": {"seeded", "retired"},
    "retired": set(),
}

CHARACTER_LIST_FIELDS = (
    "goals",
    "needs",
    "plans",
    "known_facts",
    "false_beliefs",
    "secrets",
    "fears",
    "resources",
    "moral_boundaries",
    "offstage_actions",
)

RELATIONSHIP_AXES = (
    "attraction",
    "trust",
    "respect",
    "dependency",
    "fear",
    "resentment",
    "gratitude",
    "sexual_tension",
    "power_gap",
    "sacrifice_willingness",
    "leave_willingness",
)

RELATIONSHIP_LIST_FIELDS = (
    "shared_secrets",
    "unhealed_injuries",
    "exclusive_expectations",
)

ENTITY_STRING_FIELDS = (
    "id",
    "entity_type",
    "surface_function",
    "historical_origin",
    "public_explanation",
    "hidden_explanation",
)

ENTITY_LIST_FIELDS = ("symbols", "causal_links", "promise_links")
TRUTH_LAYERS = {
    "system_truth",
    "character_knowledge",
    "character_misbelief",
    "reader_hypothesis",
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _is_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(_is_string(item) for item in value)


def _updates(
    delta: Mapping[str, Any],
    field: str,
    issues: list[str],
) -> list[Mapping[str, Any]]:
    raw = delta.get(field, [])
    if not isinstance(raw, list):
        issues.append(f"{field}_must_be_list")
        return []
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            issues.append(f"{field}:{index}:mapping_required")
            continue
        result.append(item)
    return result


def _require_evidence(
    field: str,
    updates: list[Mapping[str, Any]],
    issues: list[str],
) -> None:
    for index, update in enumerate(updates):
        if not _is_string(update.get("evidence_location")):
            issues.append(f"{field}:{index}:evidence_location_required")


def _validate_characters(
    updates: list[Mapping[str, Any]],
    issues: list[str],
) -> None:
    for index, update in enumerate(updates):
        if not _is_string(update.get("id")):
            issues.append(f"character_mind_updates:{index}:id_required")
        for field in CHARACTER_LIST_FIELDS:
            if not _is_string_list(update.get(field)):
                issues.append(
                    f"character_mind_updates:{index}:{field}_must_be_strings"
                )
        if not _is_string(update.get("next_decision_threshold")):
            issues.append(
                "character_mind_updates:"
                f"{index}:next_decision_threshold_required"
            )


def _validate_relationships(
    updates: list[Mapping[str, Any]],
    issues: list[str],
) -> None:
    for index, update in enumerate(updates):
        for field in ("id", "source_id", "target_id"):
            if not _is_string(update.get(field)):
                issues.append(
                    f"relationship_edge_updates:{index}:{field}_required"
                )
        if (
            _is_string(update.get("source_id"))
            and update.get("source_id") == update.get("target_id")
        ):
            issues.append(
                f"relationship_edge_updates:{index}:endpoints_must_be_distinct"
            )
        for field in RELATIONSHIP_AXES:
            value = update.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not -1.0 <= float(value) <= 1.0
            ):
                issues.append(
                    "relationship_edge_updates:"
                    f"{index}:{field}_must_be_between_minus_one_and_one"
                )
        for field in RELATIONSHIP_LIST_FIELDS:
            if not _is_string_list(update.get(field)):
                issues.append(
                    f"relationship_edge_updates:{index}:{field}_must_be_strings"
                )


def _validate_entities(
    updates: list[Mapping[str, Any]],
    issues: list[str],
) -> None:
    for index, update in enumerate(updates):
        for field in ENTITY_STRING_FIELDS:
            if not _is_string(update.get(field)):
                issues.append(
                    f"narrative_entity_updates:{index}:{field}_required"
                )
        for field in ENTITY_LIST_FIELDS:
            if not _is_string_list(update.get(field)):
                issues.append(
                    f"narrative_entity_updates:{index}:{field}_must_be_strings"
                )


def _validate_promises(
    updates: list[Mapping[str, Any]],
    current_state: Mapping[str, Any],
    issues: list[str],
) -> None:
    graph = current_state.get("promise_graph")
    graph = graph if isinstance(graph, Mapping) else {}
    for index, update in enumerate(updates):
        promise_id = str(update.get("id") or "")
        next_state = str(update.get("state") or "")
        if not promise_id:
            issues.append(f"promise_updates:{index}:id_required")
        if next_state not in PROMISE_STATES:
            issues.append(f"promise_updates:{index}:state_invalid")
        due = update.get("due_window")
        if (
            not isinstance(due, list)
            or len(due) != 2
            or any(
                isinstance(item, bool)
                or not isinstance(item, int)
                or item < 1
                for item in due
            )
            or (len(due) == 2 and due[0] > due[1])
        ):
            issues.append(f"promise_updates:{index}:due_window_invalid")
        if not _is_string(update.get("truth_ref")):
            issues.append(f"promise_updates:{index}:truth_ref_required")
        if not _is_string_list(update.get("reader_hypotheses")):
            issues.append(
                f"promise_updates:{index}:reader_hypotheses_must_be_strings"
            )
        previous = graph.get(promise_id)
        previous = previous if isinstance(previous, Mapping) else None
        if previous is None:
            if next_state not in {"latent", "seeded"}:
                issues.append(
                    f"promise_updates:{index}:new_promise_must_be_latent_or_seeded"
                )
        else:
            previous_state = str(previous.get("state") or "")
            if (
                next_state != previous_state
                and next_state not in PROMISE_TRANSITIONS.get(
                    previous_state, set()
                )
            ):
                issues.append(
                    "promise_updates:"
                    f"{index}:invalid_transition:{previous_state}->{next_state}"
                )


def _validate_truth(
    updates: list[Mapping[str, Any]],
    issues: list[str],
) -> None:
    identities: set[tuple[str, str]] = set()
    for index, update in enumerate(updates):
        identity = str(update.get("id") or "")
        layer = str(update.get("layer") or "")
        if not identity:
            issues.append(f"truth_updates:{index}:id_required")
        if layer not in TRUTH_LAYERS:
            issues.append(f"truth_updates:{index}:layer_invalid")
        if not _is_string(update.get("proposition")):
            issues.append(f"truth_updates:{index}:proposition_required")
        if layer in {"character_knowledge", "character_misbelief"} and not (
            _is_string(update.get("character_id"))
        ):
            issues.append(
                "truth_updates:"
                f"{index}:character_id_required_for_private_layer"
            )
        key = (layer, identity)
        if key in identities:
            issues.append(f"truth_updates:{index}:duplicate_layer_identity")
        identities.add(key)


def _validate_offstage(
    delta: Mapping[str, Any],
    updates: list[Mapping[str, Any]],
    issues: list[str],
) -> None:
    active = delta.get("active_supporting_characters", [])
    if not _is_string_list(active):
        issues.append("active_supporting_characters_must_be_strings")
        active = []
    projected: set[str] = set()
    for index, update in enumerate(updates):
        for field in ("character_id", "action", "world_effect"):
            if not _is_string(update.get(field)):
                issues.append(
                    f"offstage_action_updates:{index}:{field}_required"
                )
        if _is_string(update.get("character_id")):
            projected.add(str(update["character_id"]))
    for character_id in active:
        if character_id not in projected:
            issues.append(f"offstage_projection_missing:{character_id}")


def _validate_outline(
    value: object,
    issues: list[str],
) -> None:
    if not isinstance(value, Mapping):
        issues.append("outline_update_mapping_required")
        return
    for field in ("book", "part", "volume", "arc", "window"):
        if not _is_string(value.get(field)):
            issues.append(f"outline_update:{field}_required")
    chapter = value.get("chapter")
    if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
        issues.append("outline_update:chapter_must_be_positive")
    if not _is_string_list(value.get("scenes")) or not value.get("scenes"):
        issues.append("outline_update:scenes_required")


def _validate_content_boundary(
    value: object,
    issues: list[str],
) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        issues.append("content_boundary_mapping_required")
        return
    mature = value.get("mature_content")
    if not isinstance(mature, bool):
        issues.append("content_boundary:mature_content_boolean_required")
        return
    if not mature:
        return
    if value.get("explicitness") != "mature_sensory_non_explicit":
        issues.append("content_boundary:explicit_content_forbidden")
    for field in (
        "all_participants_adults",
        "agency_preserved",
        "contextual_consent",
        "exit_right_preserved",
        "consequences_tracked",
    ):
        if value.get(field) is not True:
            issues.append(f"content_boundary:{field}_required")


def validate_long_term_delta(
    delta: Mapping[str, Any],
    *,
    current_state: Mapping[str, Any],
) -> list[str]:
    """Return deterministic issues for one optional v1 long-term delta."""

    if "long_term_schema" not in delta:
        return []
    issues: list[str] = []
    if delta.get("long_term_schema") != "narrative-long-term-delta/v1":
        issues.append("long_term_schema_invalid")
    fields = (
        "character_mind_updates",
        "relationship_edge_updates",
        "narrative_entity_updates",
        "promise_updates",
        "truth_updates",
        "offstage_action_updates",
        "summary_updates",
        "exact_name_updates",
    )
    parsed = {field: _updates(delta, field, issues) for field in fields}
    for field, updates in parsed.items():
        _require_evidence(field, updates, issues)
    _validate_characters(parsed["character_mind_updates"], issues)
    _validate_relationships(parsed["relationship_edge_updates"], issues)
    _validate_entities(parsed["narrative_entity_updates"], issues)
    _validate_promises(parsed["promise_updates"], current_state, issues)
    _validate_truth(parsed["truth_updates"], issues)
    _validate_offstage(delta, parsed["offstage_action_updates"], issues)
    _validate_outline(delta.get("outline_update"), issues)
    _validate_content_boundary(delta.get("content_boundary"), issues)
    for index, update in enumerate(parsed["summary_updates"]):
        for field in ("scale", "node_id", "summary"):
            if not _is_string(update.get(field)):
                issues.append(f"summary_updates:{index}:{field}_required")
        if not _is_string_list(update.get("source_ids")):
            issues.append(
                f"summary_updates:{index}:source_ids_must_be_strings"
            )
    for index, update in enumerate(parsed["exact_name_updates"]):
        for field in ("canonical_name", "entity_id"):
            if not _is_string(update.get(field)):
                issues.append(f"exact_name_updates:{index}:{field}_required")
        if not _is_string_list(update.get("aliases")):
            issues.append(
                f"exact_name_updates:{index}:aliases_must_be_strings"
            )
    return sorted(set(issues))


def _upsert(
    target: dict[str, Any],
    updates: list[Mapping[str, Any]],
    *,
    identity_field: str = "id",
    chapter: int,
) -> None:
    for update in updates:
        identity = str(update[identity_field])
        target[identity] = {
            **deepcopy(dict(update)),
            "last_updated_chapter": chapter,
        }


def apply_long_term_delta(
    current_state: Mapping[str, Any],
    delta: Mapping[str, Any],
    *,
    chapter: int,
    prose_sha256: str,
) -> dict[str, Any]:
    """Project a validated delta without mutating its input state."""

    if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
        raise ValueError("chapter must be positive")
    if not _SHA256.fullmatch(prose_sha256):
        raise ValueError("prose_sha256 must be lowercase 64-hex")
    issues = validate_long_term_delta(delta, current_state=current_state)
    if issues:
        raise ValueError("invalid long-term delta: " + ",".join(issues))
    projected = deepcopy(dict(current_state))
    for field in (
        "character_minds",
        "relationship_edges",
        "narrative_entities",
        "promise_graph",
        "offstage_actions",
        "truth_layers",
        "outline_tree",
        "summary_tree",
        "exact_name_index",
    ):
        if not isinstance(projected.get(field), dict):
            projected[field] = {}
    _upsert(
        projected["character_minds"],
        list(delta.get("character_mind_updates") or []),
        chapter=chapter,
    )
    _upsert(
        projected["relationship_edges"],
        list(delta.get("relationship_edge_updates") or []),
        chapter=chapter,
    )
    _upsert(
        projected["narrative_entities"],
        list(delta.get("narrative_entity_updates") or []),
        chapter=chapter,
    )
    _upsert(
        projected["promise_graph"],
        list(delta.get("promise_updates") or []),
        chapter=chapter,
    )
    layers = projected["truth_layers"]
    for layer in TRUTH_LAYERS:
        if not isinstance(layers.get(layer), dict):
            layers[layer] = {}
    for update in delta.get("truth_updates") or []:
        layers[str(update["layer"])][str(update["id"])] = {
            **deepcopy(dict(update)),
            "last_updated_chapter": chapter,
        }
    for update in delta.get("offstage_action_updates") or []:
        character_id = str(update["character_id"])
        history = projected["offstage_actions"].setdefault(character_id, [])
        history.append({**deepcopy(dict(update)), "chapter": chapter})
    projected["outline_tree"]["current"] = deepcopy(
        dict(delta["outline_update"])
    )
    for update in delta.get("summary_updates") or []:
        scale = str(update["scale"])
        scale_tree = projected["summary_tree"].setdefault(scale, {})
        scale_tree[str(update["node_id"])] = {
            **deepcopy(dict(update)),
            "last_updated_chapter": chapter,
        }
    for update in delta.get("exact_name_updates") or []:
        entity_id = str(update["entity_id"])
        names = [str(update["canonical_name"]), *update.get("aliases", [])]
        for name in names:
            projected["exact_name_index"][str(name)] = entity_id
    projected["last_projection"] = {
        "chapter": chapter,
        "prose_sha256": prose_sha256,
        "schema_version": "narrative-long-term-delta/v1",
    }
    return projected
