"""Tests for the Skill lifecycle closed loop.

Covers: request → approve → stage → validate → promote → active,
reject, invalid transitions, promote-without-validation, retire,
and skill-status/skill-list accuracy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import cost_tracker
from skill_evolution import (
    _assert_transition,
    approve_skill_request,
    build_skill_adoption_request,
    ensure_skill_registry,
    list_skill_requests,
    load_skill_registry,
    promote_skill,
    reject_skill_request,
    retire_skill,
    stage_skill_request,
    summarize_skill_system,
    validate_staged_skill,
    write_skill_adoption_request,
    write_skill_registry,
    skill_staging_dir,
    skill_active_dir,
    skill_retired_dir,
)


def _write_pricing(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "currency": "USD",
            "models": {
                "deepseek/deepseek-v4-pro": {
                    "input_per_1m": 1.0,
                    "output_per_1m": 2.0,
                },
            },
        }, sort_keys=False),
        encoding="utf-8",
    )
    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None


def _create_pending_request(tmp_path: Path) -> dict:
    """Helper: create a skill request and return it along with the request dict."""
    _write_pricing(tmp_path)
    ensure_skill_registry(tmp_path)
    request = build_skill_adoption_request(
        tmp_path,
        project="AgentLab",
        skill_name="demo-skill",
        source="manual://demo",
        purpose="Test skill lifecycle.",
        source_type="manual",
    )
    write_skill_adoption_request(tmp_path, request)
    return request


# ── Full lifecycle: request → approve → stage → validate → promote → active ──

def test_full_lifecycle_approve_stage_validate_promote_active(tmp_path: Path) -> None:
    request = _create_pending_request(tmp_path)
    request_id = request["id"]

    # 1. approve
    approved = approve_skill_request(tmp_path, "AgentLab", request_id)
    assert approved["status"] == "approved"
    assert "approved_at" in approved

    # 2. stage
    staged = stage_skill_request(tmp_path, "AgentLab", request_id)
    assert staged["status"] == "staging"
    skill_id = staged["skill_id"]
    assert skill_id

    # staging directory created
    staging_dir = skill_staging_dir(tmp_path) / skill_id
    assert staging_dir.exists()
    assert (staging_dir / "metadata.yml").exists()
    assert (staging_dir / "adapted_skill.md").exists()
    assert (staging_dir / "validation_plan.yml").exists()

    # 3. validate (fake sandbox)
    validated = validate_staged_skill(tmp_path, skill_id, fake_sandbox=True)
    assert validated["status"] == "validated"
    assert validated["risk_level"] in ("low", "high")
    assert validated["checked_files_count"] >= 2

    # sandbox_report.yml created
    sandbox_path = staging_dir / "sandbox_report.yml"
    assert sandbox_path.exists()
    report = yaml.safe_load(sandbox_path.read_text(encoding="utf-8"))
    assert report["validated"] is True
    assert report["mode"] == "fake_sandbox"

    # 4. promote
    promoted = promote_skill(tmp_path, skill_id)
    assert promoted["status"] == "active"

    # active directory created
    active_dir = skill_active_dir(tmp_path) / skill_id
    assert active_dir.exists()
    assert (active_dir / "SKILL.md").exists()
    assert (active_dir / "metadata.yml").exists()
    assert (active_dir / "validation_report.yml").exists()
    assert not (active_dir / "usage_ledger.yml").exists()

    # registry updated
    registry = load_skill_registry(tmp_path)
    active_skills = [s for s in registry.get("skills", []) if s.get("status") == "active"]
    assert len(active_skills) >= 1
    assert any(s["skill_id"] == skill_id for s in active_skills)


# ── reject request ──

def test_reject_request(tmp_path: Path) -> None:
    request = _create_pending_request(tmp_path)
    request_id = request["id"]

    result = reject_skill_request(tmp_path, "AgentLab", request_id, "Not needed.")
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "Not needed."

    # verify request file updated
    requests = list_skill_requests(tmp_path, "AgentLab")
    assert any(r["id"] == request_id and r["status"] == "rejected" for r in requests)


# ── invalid transition fails ──

def test_invalid_transition_rejected_to_approved(tmp_path: Path) -> None:
    request = _create_pending_request(tmp_path)
    request_id = request["id"]
    reject_skill_request(tmp_path, "AgentLab", request_id, "nope")

    with pytest.raises(ValueError, match="Invalid transition"):
        approve_skill_request(tmp_path, "AgentLab", request_id)


def test_invalid_transition_approved_to_validated_directly(tmp_path: Path) -> None:
    """Approved → validated is not a direct allowed transition."""
    request = _create_pending_request(tmp_path)
    request_id = request["id"]
    approve_skill_request(tmp_path, "AgentLab", request_id)

    # approved → staging is valid
    staged = stage_skill_request(tmp_path, "AgentLab", request_id)
    skill_id = staged["skill_id"]

    # But trying to skip validation (staging → active) should fail
    with pytest.raises(ValueError):
        promote_skill(tmp_path, skill_id)


def test_invalid_transition_pending_to_staging(tmp_path: Path) -> None:
    request = _create_pending_request(tmp_path)
    request_id = request["id"]

    with pytest.raises(ValueError, match="Invalid transition"):
        stage_skill_request(tmp_path, "AgentLab", request_id)


def test_invalid_transition_pending_to_validated(tmp_path: Path) -> None:
    """Validate that _assert_transition itself rejects disallowed transitions."""
    with pytest.raises(ValueError, match="Invalid transition"):
        _assert_transition("pending_user_approval", "validated")

    with pytest.raises(ValueError, match="Invalid transition"):
        _assert_transition("approved", "active")

    with pytest.raises(ValueError, match="Invalid transition"):
        _assert_transition("staging", "active")

    with pytest.raises(ValueError, match="Invalid transition"):
        _assert_transition("retired", "active")


# ── promote without validation fails ──

def test_promote_without_validation_fails(tmp_path: Path) -> None:
    request = _create_pending_request(tmp_path)
    request_id = request["id"]
    approve_skill_request(tmp_path, "AgentLab", request_id)
    staged = stage_skill_request(tmp_path, "AgentLab", request_id)
    skill_id = staged["skill_id"]

    # skip validation, try to promote directly
    with pytest.raises(ValueError, match="validated"):
        promote_skill(tmp_path, skill_id)


# ── retire active skill ──

def test_retire_active_skill(tmp_path: Path) -> None:
    request = _create_pending_request(tmp_path)
    request_id = request["id"]
    approve_skill_request(tmp_path, "AgentLab", request_id)
    staged = stage_skill_request(tmp_path, "AgentLab", request_id)
    skill_id = staged["skill_id"]
    validate_staged_skill(tmp_path, skill_id, fake_sandbox=True)
    promote_skill(tmp_path, skill_id)

    # Now retire
    result = retire_skill(tmp_path, skill_id, "obsolete")
    assert result["status"] == "retired"
    assert result["reason"] == "obsolete"

    # retired dir created
    retired_dir = skill_retired_dir(tmp_path) / skill_id
    assert retired_dir.exists()
    assert (retired_dir / "retired_at.yml").exists()

    # registry updated
    registry = load_skill_registry(tmp_path)
    active_skills = [s for s in registry.get("skills", []) if s.get("status") == "active"]
    retired_skills = registry.get("retired_skills", [])
    assert not any(s["skill_id"] == skill_id for s in active_skills)
    assert any(s["skill_id"] == skill_id for s in retired_skills)


def test_retire_non_existent_skill(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    ensure_skill_registry(tmp_path)
    with pytest.raises((FileNotFoundError, ValueError)):
        retire_skill(tmp_path, "nonexistent_skill", "test")


# ── skill-status / skill-list accurately report counts ──

def test_skill_status_reports_counts(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    ensure_skill_registry(tmp_path)

    summary = summarize_skill_system(tmp_path, "AgentLab")
    assert summary["pending_request_count"] == 0
    assert summary["active_skill_count"] == 0
    assert summary["retired_skill_count"] == 0

    # Create a request
    request = _create_pending_request(tmp_path)
    request_id = request["id"]

    summary = summarize_skill_system(tmp_path, "AgentLab")
    assert summary["pending_request_count"] == 1

    # Reject it
    reject_skill_request(tmp_path, "AgentLab", request_id, "test")
    summary = summarize_skill_system(tmp_path, "AgentLab")
    assert summary["pending_request_count"] == 0


def test_skill_list_shows_statuses(tmp_path: Path) -> None:
    request = _create_pending_request(tmp_path)
    request_id = request["id"]

    all_requests = list_skill_requests(tmp_path, "AgentLab")
    assert len(all_requests) >= 1
    assert any(r["id"] == request_id for r in all_requests)

    # approve
    approve_skill_request(tmp_path, "AgentLab", request_id)
    all_requests = list_skill_requests(tmp_path, "AgentLab")
    assert any(r["id"] == request_id and r["status"] == "approved" for r in all_requests)


def test_staging_and_active_dir_cleanliness(tmp_path: Path) -> None:
    """Ensure staging/active dirs are empty before any lifecycle."""
    _write_pricing(tmp_path)
    ensure_skill_registry(tmp_path)

    staging = skill_staging_dir(tmp_path)
    active = skill_active_dir(tmp_path)
    retired = skill_retired_dir(tmp_path)

    # These dirs may not exist yet
    staging_count = len([d for d in staging.iterdir() if d.is_dir()]) if staging.exists() else 0
    active_count = len([d for d in active.iterdir() if d.is_dir()]) if active.exists() else 0
    retired_count = len([d for d in retired.iterdir() if d.is_dir()]) if retired.exists() else 0

    assert staging_count == 0
    assert active_count == 0
    assert retired_count == 0
