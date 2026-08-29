from __future__ import annotations

from copy import deepcopy

from agent_runtime.narrative.long_term_state import (
    PROMISE_STATES,
    apply_long_term_delta,
    validate_long_term_delta,
)


def _delta() -> dict:
    return {
        "long_term_schema": "narrative-long-term-delta/v1",
        "character_mind_updates": [
            {
                "id": "char_arya",
                "goals": ["protect the archive"],
                "needs": ["accept help"],
                "plans": ["enter through the cistern"],
                "known_facts": ["fact_gate_locked"],
                "false_beliefs": ["belief_guard_bribed"],
                "secrets": ["secret_map"],
                "fears": ["flooded tunnels"],
                "resources": ["bronze key"],
                "moral_boundaries": ["will not abandon a child"],
                "offstage_actions": ["sent the decoy west"],
                "next_decision_threshold": "the bell rings twice",
                "evidence_location": "chapter:12:lines:10-18",
            }
        ],
        "relationship_edge_updates": [
            {
                "id": "rel_arya_bran",
                "source_id": "char_arya",
                "target_id": "char_bran",
                "attraction": 0.2,
                "trust": 0.4,
                "respect": 0.7,
                "dependency": 0.1,
                "fear": 0.0,
                "resentment": 0.3,
                "gratitude": 0.5,
                "sexual_tension": 0.0,
                "power_gap": -0.2,
                "shared_secrets": ["secret_map"],
                "unhealed_injuries": ["the abandoned watch"],
                "exclusive_expectations": [],
                "sacrifice_willingness": 0.3,
                "leave_willingness": 0.6,
                "evidence_location": "chapter:12:lines:20-28",
            }
        ],
        "narrative_entity_updates": [
            {
                "id": "place_archive",
                "entity_type": "building",
                "surface_function": "royal records hall",
                "historical_origin": "a converted flood shrine",
                "public_explanation": "the cistern is decorative",
                "hidden_explanation": "it is an escape route",
                "symbols": ["buried memory"],
                "causal_links": ["event_archive_escape"],
                "promise_links": ["promise_cistern"],
                "evidence_location": "chapter:12:lines:30-39",
            }
        ],
        "promise_updates": [
            {
                "id": "promise_cistern",
                "state": "seeded",
                "due_window": [18, 24],
                "truth_ref": "truth_cistern_exit",
                "reader_hypotheses": ["the cistern hides treasure"],
                "evidence_location": "chapter:12:lines:30-39",
            }
        ],
        "truth_updates": [
            {
                "id": "truth_cistern_exit",
                "layer": "system_truth",
                "proposition": "the cistern opens beyond the wall",
                "evidence_location": "chapter:12:lines:30-39",
            },
            {
                "id": "knowledge_arya_gate",
                "layer": "character_knowledge",
                "character_id": "char_arya",
                "proposition": "the main gate is locked",
                "truth_ref": "fact_gate_locked",
                "evidence_location": "chapter:12:lines:10-18",
            },
            {
                "id": "hypothesis_cistern_treasure",
                "layer": "reader_hypothesis",
                "proposition": "the cistern hides treasure",
                "evidence_location": "chapter:12:lines:30-39",
            },
        ],
        "active_supporting_characters": ["char_bran"],
        "offstage_action_updates": [
            {
                "character_id": "char_bran",
                "action": "redirected the night patrol",
                "world_effect": "the western gate is briefly unguarded",
                "evidence_location": "chapter:12:lines:40-44",
            }
        ],
        "outline_update": {
            "book": "book_1",
            "part": "part_1",
            "volume": "volume_2",
            "arc": "arc_archive",
            "window": "window_11_35",
            "chapter": 12,
            "scenes": ["scene_cistern", "scene_bell"],
        },
        "summary_updates": [
            {
                "scale": "chapter",
                "node_id": "chapter_12",
                "summary": "Arya discovers the cistern's real purpose.",
                "source_ids": ["truth_cistern_exit", "promise_cistern"],
                "evidence_location": "chapter:12",
            }
        ],
        "exact_name_updates": [
            {
                "canonical_name": "Royal Archive",
                "entity_id": "place_archive",
                "aliases": ["Records Hall"],
                "evidence_location": "chapter:12:lines:30-39",
            }
        ],
        "content_boundary": {
            "mature_content": True,
            "explicitness": "mature_sensory_non_explicit",
            "all_participants_adults": True,
            "agency_preserved": True,
            "contextual_consent": True,
            "exit_right_preserved": True,
            "consequences_tracked": True,
        },
    }


def test_complete_long_term_delta_validates_and_projects() -> None:
    delta = _delta()
    assert validate_long_term_delta(delta, current_state={}) == []

    projected = apply_long_term_delta(
        {},
        delta,
        chapter=12,
        prose_sha256="a" * 64,
    )

    assert projected["character_minds"]["char_arya"]["goals"] == [
        "protect the archive"
    ]
    assert projected["relationship_edges"]["rel_arya_bran"]["trust"] == 0.4
    assert projected["narrative_entities"]["place_archive"]["entity_type"] == (
        "building"
    )
    assert projected["promise_graph"]["promise_cistern"]["state"] == "seeded"
    assert (
        projected["truth_layers"]["system_truth"]["truth_cistern_exit"][
            "proposition"
        ]
        == "the cistern opens beyond the wall"
    )
    assert projected["offstage_actions"]["char_bran"][-1]["chapter"] == 12
    assert projected["outline_tree"]["current"]["chapter"] == 12
    assert projected["exact_name_index"]["Records Hall"] == "place_archive"
    assert projected["last_projection"]["prose_sha256"] == "a" * 64


def test_every_active_supporting_character_requires_offstage_projection() -> None:
    delta = _delta()
    delta["active_supporting_characters"].append("char_cora")

    issues = validate_long_term_delta(delta, current_state={})

    assert "offstage_projection_missing:char_cora" in issues


def test_truth_layers_reject_character_knowledge_without_character() -> None:
    delta = _delta()
    update = delta["truth_updates"][1]
    update.pop("character_id")

    issues = validate_long_term_delta(delta, current_state={})

    assert (
        "truth_updates:1:character_id_required_for_private_layer" in issues
    )


def test_relationship_axes_are_bounded_and_endpoints_are_distinct() -> None:
    delta = _delta()
    edge = delta["relationship_edge_updates"][0]
    edge["trust"] = 1.2
    edge["target_id"] = edge["source_id"]

    issues = validate_long_term_delta(delta, current_state={})

    assert "relationship_edge_updates:0:trust_must_be_between_minus_one_and_one" in issues
    assert "relationship_edge_updates:0:endpoints_must_be_distinct" in issues


def test_promise_graph_enforces_declared_state_machine() -> None:
    current = {
        "promise_graph": {
            "promise_cistern": {
                "state": "seeded",
            }
        }
    }
    delta = _delta()
    delta["promise_updates"][0]["state"] = "paid_off"

    issues = validate_long_term_delta(delta, current_state=current)

    assert "promise_updates:0:invalid_transition:seeded->paid_off" in issues
    assert set(PROMISE_STATES) == {
        "latent",
        "seeded",
        "reinforced",
        "misinterpreted",
        "activated",
        "partially_revealed",
        "paid_off",
        "transformed",
        "retired",
    }


def test_every_update_requires_exact_evidence() -> None:
    delta = _delta()
    del delta["narrative_entity_updates"][0]["evidence_location"]
    del delta["summary_updates"][0]["evidence_location"]

    issues = validate_long_term_delta(delta, current_state={})

    assert "narrative_entity_updates:0:evidence_location_required" in issues
    assert "summary_updates:0:evidence_location_required" in issues


def test_projection_refuses_invalid_delta_without_mutating_previous() -> None:
    previous = {"promise_graph": {"p": {"state": "retired"}}}
    before = deepcopy(previous)
    delta = _delta()
    delta["promise_updates"][0] = {
        "id": "p",
        "state": "seeded",
        "due_window": [20, 25],
        "truth_ref": "t",
        "reader_hypotheses": [],
        "evidence_location": "chapter:12",
    }

    try:
        apply_long_term_delta(
            previous,
            delta,
            chapter=12,
            prose_sha256="a" * 64,
        )
    except ValueError as exc:
        assert "invalid_transition" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid delta projected")
    assert previous == before


def test_mature_content_hard_gate_requires_adults_consent_and_exit_right() -> None:
    delta = _delta()
    boundary = delta["content_boundary"]
    boundary["all_participants_adults"] = False
    boundary["contextual_consent"] = False
    boundary["explicitness"] = "explicit"

    issues = validate_long_term_delta(delta, current_state={})

    assert "content_boundary:all_participants_adults_required" in issues
    assert "content_boundary:contextual_consent_required" in issues
    assert "content_boundary:explicit_content_forbidden" in issues
