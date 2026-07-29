from __future__ import annotations

from pathlib import Path

from agent_runtime.narrative.preferences import (
    CROWN_AUTHORIAL_PRIOR,
    PreferenceStore,
    classify_feedback,
    update_preference_weights,
)


def test_crown_prior_is_exact_hundred_point_matrix() -> None:
    assert sum(CROWN_AUTHORIAL_PRIOR.values()) == 100
    assert CROWN_AUTHORIAL_PRIOR["causal_foreshadowing"] == 12
    assert CROWN_AUTHORIAL_PRIOR["character_arcs"] == 11
    assert CROWN_AUTHORIAL_PRIOR["voice_humor"] == 1
    assert len(CROWN_AUTHORIAL_PRIOR) == 16


def test_formula_updates_weights_and_caps_each_relative_change() -> None:
    updated = update_preference_weights(
        CROWN_AUTHORIAL_PRIOR,
        classifications=[
            {
                "dimension": "pacing",
                "polarity": -1,
                "confidence": 1.0,
                "recurrence": 3,
            }
        ],
        scope_level="chapter",
    )

    assert abs(sum(updated.values()) - 100.0) < 1e-9
    assert updated["pacing"] < CROWN_AUTHORIAL_PRIOR["pacing"]
    for dimension, before in CROWN_AUTHORIAL_PRIOR.items():
        relative = abs(updated[dimension] - before) / before
        assert relative <= 0.100000001


def test_store_appends_idempotent_feedback_with_before_after_snapshot(
    tmp_path: Path,
) -> None:
    store = PreferenceStore(tmp_path, project="Crown_of_Ash")
    store.initialize(CROWN_AUTHORIAL_PRIOR)
    event = store.intake(
        source="user",
        scope_level="window",
        scope_id="window_1_25",
        classifications=[
            {
                "dimension": "relationships",
                "polarity": 1,
                "confidence": 0.9,
                "recurrence": 2,
            }
        ],
        idempotency_key="feedback-001",
        expires_after_chapter=25,
    )
    repeated = store.intake(
        source="user",
        scope_level="window",
        scope_id="window_1_25",
        classifications=[
            {
                "dimension": "relationships",
                "polarity": 1,
                "confidence": 0.9,
                "recurrence": 2,
            }
        ],
        idempotency_key="feedback-001",
        expires_after_chapter=25,
    )

    assert event == repeated
    assert event["before_weights"]["relationships"] == 6
    assert event["after_weights"]["relationships"] > 6
    assert len(store.events_path.read_text(encoding="utf-8").splitlines()) == 2
    profile = store.profile(chapter=20, window="window_1_25")
    assert profile["effective_weights"]["relationships"] > 6
    assert profile["effective_profile_sha256"]


def test_expired_local_overlay_retires_automatically(tmp_path: Path) -> None:
    store = PreferenceStore(tmp_path, project="Crown_of_Ash")
    store.initialize(CROWN_AUTHORIAL_PRIOR)
    store.intake(
        source="user",
        scope_level="chapter",
        scope_id="chapter_12",
        classifications=[
            {
                "dimension": "atmosphere",
                "polarity": 1,
                "confidence": 1,
                "recurrence": 1,
            }
        ],
        idempotency_key="feedback-expiring",
        expires_after_chapter=12,
    )

    active = store.profile(chapter=12, chapter_scope="chapter_12")
    expired = store.profile(chapter=13, chapter_scope="chapter_12")

    assert active["effective_weights"]["atmosphere"] > 4
    assert expired["effective_weights"]["atmosphere"] == 4
    assert expired["retired_overlays"] == ["chapter:chapter_12"]


def test_reviewer_cannot_change_book_prior_or_canon_dimension(
    tmp_path: Path,
) -> None:
    store = PreferenceStore(tmp_path, project="Crown_of_Ash")
    store.initialize(CROWN_AUTHORIAL_PRIOR)

    try:
        store.intake(
            source="reviewer",
            scope_level="book",
            scope_id="book",
            classifications=[
                {
                    "dimension": "pacing",
                    "polarity": 1,
                    "confidence": 1,
                    "recurrence": 1,
                }
            ],
            idempotency_key="reviewer-book",
        )
    except ValueError as exc:
        assert "reviewer" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("reviewer changed book prior")

    try:
        store.intake(
            source="user",
            scope_level="chapter",
            scope_id="chapter_1",
            classifications=[
                {
                    "dimension": "canon",
                    "polarity": 1,
                    "confidence": 1,
                    "recurrence": 1,
                }
            ],
            idempotency_key="canon-weight",
            expires_after_chapter=1,
        )
    except ValueError as exc:
        assert "dimension" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("canon entered soft preference weights")


def test_rollback_is_append_only_and_restores_latest_scope_snapshot(
    tmp_path: Path,
) -> None:
    store = PreferenceStore(tmp_path, project="Crown_of_Ash")
    store.initialize(CROWN_AUTHORIAL_PRIOR)
    event = store.intake(
        source="user",
        scope_level="book",
        scope_id="book",
        classifications=[
            {
                "dimension": "mystery",
                "polarity": 1,
                "confidence": 1,
                "recurrence": 1,
            }
        ],
        idempotency_key="book-mystery",
    )
    rollback = store.rollback(
        event_id=event["event_id"],
        idempotency_key="rollback-book-mystery",
    )

    assert rollback["event_type"] == "PREFERENCE_ROLLED_BACK"
    assert store.profile()["effective_weights"] == {
        key: float(value) for key, value in CROWN_AUTHORIAL_PRIOR.items()
    }
    assert len(store.events_path.read_text(encoding="utf-8").splitlines()) == 3


def test_rule_classifier_returns_structured_candidate_or_supervisor_review() -> None:
    classified = classify_feedback("这一章节奏太慢，伏笔很好", polarity=None)
    assert {item["dimension"] for item in classified["classifications"]} == {
        "pacing",
        "causal_foreshadowing",
    }
    assert classified["supervisor_review_required"] is False

    ambiguous = classify_feedback("我觉得哪里不太对", polarity=None)
    assert ambiguous["classifications"] == []
    assert ambiguous["supervisor_review_required"] is True
