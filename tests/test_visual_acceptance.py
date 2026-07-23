from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_runtime.visual_acceptance import evaluate_visual_candidate


DIMENSIONS = ("aesthetic", "continuity", "technical", "factual_safety")
VERIFICATION_CHECKS = (
    "asset_integrity",
    "evidence_chain",
    "reviewer_independence",
    "promotion_boundary",
)


def _review(*, role: str, reviewer_id: str, backend: str, model: str) -> dict:
    review = {
        "reviewer": {
            "role": role,
            "id": reviewer_id,
            "backend": backend,
            "model": model,
        },
        "status": "complete",
    }
    key = "dimensions" if role == "Reviewer" else "checks"
    names = DIMENSIONS if role == "Reviewer" else VERIFICATION_CHECKS
    review[key] = {
            dimension: {
                "verdict": "pass",
                "evidence": [f"{role} checked {dimension}"],
            }
            for dimension in names
    }
    return review


def _candidate(workspace: Path, *, media_type: str = "image") -> dict:
    asset_path = workspace / f"candidate.{media_type}"
    asset_path.write_bytes(f"deterministic-{media_type}-candidate".encode())
    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    size_bytes = asset_path.stat().st_size

    observer: dict = {
        "status": "complete",
        "observer": {
            "role": "Observer",
            "id": "agy-observer-session",
            "backend": "agy_oauth",
            "model": "gemini-3.5-flash",
        },
        "asset": {
            "path": asset_path.name,
            "sha256": digest,
            "size_bytes": size_bytes,
        },
    }
    if media_type == "image":
        observer["keyframes"] = [{"label": "full_frame", "sha256": digest}]
    elif media_type == "video":
        observer["keyframes"] = [{"timestamp_seconds": 0, "sha256": digest}]
        observer["timestamps"] = [{"start_seconds": 0, "end_seconds": 1}]
    elif media_type == "audio":
        observer["timestamps"] = [{"start_seconds": 0, "end_seconds": 1}]
    elif media_type == "pdf":
        observer["pages"] = [{"page": 1, "sha256": digest}]

    asset_descriptor = {
        "path": asset_path.name,
        "sha256": digest,
        "size_bytes": size_bytes,
    }
    reviews = [
        _review(
            role="Reviewer",
            reviewer_id="claude-reviewer",
            backend="claude_shell",
            model="deepseek-v4-pro",
        ),
        _review(
            role="Verifier",
            reviewer_id="codex-verifier",
            backend="hermes_codex_oauth",
            model="gpt-5.6-sol",
        ),
    ]
    for review in reviews:
        review["asset"] = dict(asset_descriptor)

    return {
        "candidate_id": "visual-001",
        "candidate_only": True,
        "status": "complete",
        "asset": {
            "path": asset_path.name,
            "media_type": media_type,
            "sha256": digest,
            "size_bytes": size_bytes,
        },
        "generation_receipt": {
            "status": "complete",
            "producer": {"role": "ArtifactProducer", "id": "grok-producer"},
            "backend": "grok_imagine",
            "model": "grok-imagine-image",
            "prompt_parameters": {
                "prompt_sha256": hashlib.sha256(b"fixture prompt").hexdigest(),
                "aspect_ratio": "1:1",
            },
            "reference_assets": [],
        },
        "observer_evidence": observer,
        "reviews": reviews,
    }


def _codes(decision: dict) -> set[str]:
    return {reason["code"] for reason in decision["blocking_reasons"]}


def test_rejects_producer_self_review(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    candidate["reviews"][0]["reviewer"].update(
        {
            "id": "grok-producer",
            "backend": "grok_imagine",
            "model": "grok-imagine-image",
        }
    )

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "blocked"
    assert decision["candidate_only"] is True
    assert decision["promotion"] == {
        "eligible": False,
        "performed": False,
        "requires_external_gate": True,
    }
    assert "review.independence.producer_self_review" in _codes(decision)


def test_rejects_missing_observer_session_id(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    candidate["observer_evidence"]["observer"].pop("id")

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "blocked"
    assert decision["promotion"]["eligible"] is False
    assert "observer.identity_field_missing" in _codes(decision)


@pytest.mark.parametrize("review_index", [0, 1])
def test_rejects_review_without_exact_asset_hash_binding(
    tmp_path: Path, review_index: int
) -> None:
    candidate = _candidate(tmp_path)
    candidate["reviews"][review_index]["asset"]["sha256"] = "0" * 64

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "blocked"
    assert decision["promotion"]["eligible"] is False
    assert "review.asset_hash_mismatch" in _codes(decision)


def test_rejects_observer_reusing_producer_session_id(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    candidate["observer_evidence"]["observer"]["id"] = "grok-producer"

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "blocked"
    assert decision["promotion"]["eligible"] is False
    assert "review.independence.observer_session_reused" in _codes(decision)
    review_check = next(
        check for check in decision["checks"] if check["id"] == "review_independence"
    )
    assert review_check["status"] == "blocked"


@pytest.mark.parametrize("review_index", [0, 1])
def test_rejects_reviewer_or_verifier_reusing_observer_session_id(
    tmp_path: Path, review_index: int
) -> None:
    candidate = _candidate(tmp_path)
    candidate["reviews"][review_index]["reviewer"]["id"] = "agy-observer-session"

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "blocked"
    assert decision["promotion"]["eligible"] is False
    assert "review.independence.observer_session_reused" in _codes(decision)


def test_allows_observer_and_reviewer_to_share_backend_model_across_sessions(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    candidate["reviews"][0]["reviewer"].update(
        {"backend": "agy_oauth", "model": "gemini-3.5-flash"}
    )

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "accepted_candidate"
    assert decision["promotion"]["eligible"] is True


def test_rejects_asset_hash_mismatch(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    candidate["asset"]["sha256"] = "0" * 64
    candidate["observer_evidence"]["asset"]["sha256"] = "0" * 64

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "blocked"
    assert decision["promotion"]["eligible"] is False
    assert "asset.sha256_mismatch" in _codes(decision)


def test_rejects_missing_asset_and_declared_size_mismatch(tmp_path: Path) -> None:
    missing = _candidate(tmp_path)
    (tmp_path / missing["asset"]["path"]).unlink()
    assert "asset.missing" in _codes(evaluate_visual_candidate(missing, workspace=tmp_path))

    wrong_size = _candidate(tmp_path)
    wrong_size["asset"]["size_bytes"] += 1
    decision = evaluate_visual_candidate(wrong_size, workspace=tmp_path)
    assert decision["promotion"]["eligible"] is False
    assert "asset.size_mismatch" in _codes(decision)


@pytest.mark.parametrize("unresolved", ["pending", "unknown", "missing_auth"])
def test_unresolved_status_never_allows_promotion(tmp_path: Path, unresolved: str) -> None:
    candidate = _candidate(tmp_path)
    candidate["reviews"][1]["checks"]["asset_integrity"]["verdict"] = unresolved

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["status"] == "blocked"
    assert decision["promotion"]["eligible"] is False
    assert decision["dimensions"]["technical"]["status"] == "pass"
    assert f"verification.asset_integrity.{unresolved}" in _codes(decision)


def test_requires_configured_media_locator_evidence(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, media_type="pdf")
    candidate["observer_evidence"].pop("pages")

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["promotion"]["eligible"] is False
    assert "observer.locator_missing" in _codes(decision)


@pytest.mark.parametrize("media_type", ["image", "video", "audio", "pdf"])
def test_complete_independent_multi_review_is_candidate_only_and_eligible(
    tmp_path: Path, media_type: str
) -> None:
    candidate = _candidate(tmp_path, media_type=media_type)

    decision = evaluate_visual_candidate(candidate, workspace=tmp_path)

    assert decision["schema_version"] == "visual-acceptance-decision/v1"
    assert decision["candidate_id"] == "visual-001"
    assert decision["status"] == "accepted_candidate"
    assert decision["candidate_only"] is True
    assert decision["promotion"] == {
        "eligible": True,
        "performed": False,
        "requires_external_gate": True,
    }
    assert decision["blocking_reasons"] == []
    assert decision["asset"]["verified"] is True
    assert set(decision["review_roles"]) == {"Reviewer", "Verifier"}
    assert all(
        dimension["status"] == "pass" for dimension in decision["dimensions"].values()
    )
