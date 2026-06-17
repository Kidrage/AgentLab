from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))


from skills.metadata import (  # noqa: E402
    VALID_LIFECYCLE_STATUSES,
    SkillInputs,
    SkillOutputs,
    SkillQuality,
    assert_dispatchable_with_lifecycle,
    build_registry_summary,
    default_metadata,
    enrich_skill_dict,
    validate_skill_metadata,
)
from skills.registry import (  # noqa: E402
    ExternalSkill,
    add_or_update_skill,
    default_registry,
    load_skill_registry,
)


def _make_skill(**overrides: object) -> dict:
    base = {
        "skill_id": "test.skill",
        "source": "agentlab_internal",
        "source_type": "internal_skill",
        "display_name": "Test Skill",
        "enabled": True,
        "lifecycle_status": "active",
        "risk": {"level": "low", "requires_approval": False},
        "license": {
            "name": "MIT",
            "source_url": None,
            "compatible_for_internal_distillation": "yes",
        },
        "inputs": {"artifacts": ["text"], "context_required": []},
        "outputs": {"artifacts": ["markdown"]},
        "quality": {"success_count": 0, "failure_count": 0, "last_used_at": None, "quality_score": None},
    }
    base.update(overrides)
    return base


# ── Schema Fields ──────────────────────────────────────────────────


def test_enrich_adds_lifecycle_status() -> None:
    skill: dict = {"skill_id": "x", "source": "ecc"}
    enrich_skill_dict(skill)
    assert skill["lifecycle_status"] == "draft"


def test_enrich_adds_inputs_outputs_quality() -> None:
    skill: dict = {"skill_id": "x"}
    enrich_skill_dict(skill)
    assert "inputs" in skill
    assert "outputs" in skill
    assert "quality" in skill
    assert skill["quality"]["success_count"] == 0


def test_enrich_preserves_existing_values() -> None:
    skill = {"skill_id": "x", "lifecycle_status": "active", "quality": {"success_count": 5}}
    enrich_skill_dict(skill)
    assert skill["lifecycle_status"] == "active"
    assert skill["quality"]["success_count"] == 5


def test_default_metadata_has_all_fields() -> None:
    md = default_metadata()
    assert "lifecycle_status" in md
    assert "inputs" in md
    assert "outputs" in md
    assert "quality" in md


# ── Dataclass Helpers ──────────────────────────────────────────────


def test_skill_inputs_round_trip() -> None:
    inp = SkillInputs(artifacts=["text", "repo"], context_required=["task_id"])
    d = inp.to_dict()
    restored = SkillInputs.from_dict(d)
    assert restored.artifacts == ["text", "repo"]
    assert restored.context_required == ["task_id"]


def test_skill_outputs_round_trip() -> None:
    out = SkillOutputs(artifacts=["markdown", "json"])
    d = out.to_dict()
    restored = SkillOutputs.from_dict(d)
    assert restored.artifacts == ["markdown", "json"]


def test_skill_quality_round_trip() -> None:
    q = SkillQuality(success_count=10, failure_count=2, quality_score=0.83)
    d = q.to_dict()
    restored = SkillQuality.from_dict(d)
    assert restored.success_count == 10
    assert restored.quality_score == 0.83


def test_skill_inputs_from_none() -> None:
    inp = SkillInputs.from_dict(None)
    assert inp.artifacts == []


# ── Validation ─────────────────────────────────────────────────────


def test_valid_skill_passes_validation() -> None:
    skill = _make_skill()
    errors = validate_skill_metadata(skill)
    assert errors == []


def test_invalid_lifecycle_status_rejected() -> None:
    skill = _make_skill(lifecycle_status="invalid_status")
    errors = validate_skill_metadata(skill)
    assert any("invalid lifecycle_status" in e for e in errors)


def test_active_but_disabled_rejected() -> None:
    skill = _make_skill(lifecycle_status="active", enabled=False)
    errors = validate_skill_metadata(skill)
    assert any("active" in e and "enabled" in e for e in errors)


def test_enabled_but_not_active_rejected() -> None:
    skill = _make_skill(lifecycle_status="draft", enabled=True, source="agentlab_internal")
    errors = validate_skill_metadata(skill)
    assert any("enabled=true" in e for e in errors)


def test_external_source_defaults_disabled() -> None:
    skill = _make_skill(source="ecc", enabled=True)
    errors = validate_skill_metadata(skill)
    assert any("external source" in e for e in errors)


def test_unknown_license_requires_review() -> None:
    skill = _make_skill(
        source="agentlab_internal",
        license={"name": "unknown", "compatible_for_internal_distillation": "review_required"},
    )
    errors = validate_skill_metadata(skill)
    assert any("unknown license requires review" in e for e in errors)


def test_duplicate_skill_id_rejected() -> None:
    reg = default_registry()
    skill = ExternalSkill(
        skill_id="dup.test",
        source="agentlab_internal",
        source_type="internal_skill",
        display_name="Dup",
    )
    add_or_update_skill(reg, skill)
    try:
        add_or_update_skill(reg, skill, overwrite=False)
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "Duplicate" in str(exc)


def test_invalid_input_artifact_type() -> None:
    skill = _make_skill(inputs={"artifacts": ["invalid_type"], "context_required": []})
    errors = validate_skill_metadata(skill)
    assert any("invalid input artifact type" in e for e in errors)


def test_invalid_output_artifact_type() -> None:
    skill = _make_skill(outputs={"artifacts": ["invalid_type"]})
    errors = validate_skill_metadata(skill)
    assert any("invalid output artifact type" in e for e in errors)


# ── Lifecycle Dispatch Gate ────────────────────────────────────────


def test_pending_review_cannot_execute() -> None:
    reg = {"external_skills": [_make_skill(lifecycle_status="pending_review", enabled=True)]}
    try:
        assert_dispatchable_with_lifecycle(reg, "test.skill")
        assert False, "Should have raised"
    except PermissionError:
        pass


def test_draft_cannot_execute() -> None:
    reg = {"external_skills": [_make_skill(lifecycle_status="draft", enabled=False)]}
    try:
        assert_dispatchable_with_lifecycle(reg, "test.skill")
        assert False, "Should have raised"
    except PermissionError:
        pass


def test_active_skill_can_dispatch() -> None:
    reg = {"external_skills": [_make_skill(lifecycle_status="active", enabled=True)]}
    result = assert_dispatchable_with_lifecycle(reg, "test.skill")
    assert result["skill_id"] == "test.skill"


def test_unknown_skill_raises() -> None:
    reg = {"external_skills": []}
    try:
        assert_dispatchable_with_lifecycle(reg, "nonexistent")
        assert False, "Should have raised"
    except KeyError:
        pass


# ── Registry Summary API ──────────────────────────────────────────


def test_registry_summary_counts() -> None:
    reg = {
        "external_skills": [
            _make_skill(skill_id="a", lifecycle_status="active", source="agentlab_internal",
                       risk={"level": "low", "requires_approval": False},
                       license={"name": "MIT", "compatible_for_internal_distillation": "yes"}),
            _make_skill(skill_id="b", lifecycle_status="candidate", source="ecc", enabled=False),
            _make_skill(skill_id="c", lifecycle_status="rejected", source="codegraph", enabled=False,
                       license={"name": "unknown", "license_review_required": True,
                               "compatible_for_internal_distillation": "review_required"}),
        ]
    }
    summary = build_registry_summary(reg)
    assert summary.total == 3
    assert summary.by_lifecycle["active"] == 1
    assert summary.by_lifecycle["candidate"] == 1
    assert summary.by_lifecycle["rejected"] == 1
    assert "a" in summary.active_skills
    assert "b" in summary.candidates
    assert "c" in summary.blocked_or_review_required


def test_registry_summary_empty() -> None:
    reg = {"external_skills": []}
    summary = build_registry_summary(reg)
    assert summary.total == 0
    assert summary.active_skills == []


def test_registry_summary_to_dict() -> None:
    reg = {"external_skills": [_make_skill()]}
    summary = build_registry_summary(reg)
    d = summary.to_dict()
    assert "total" in d
    assert "by_lifecycle" in d


# ── Backward Compatibility ─────────────────────────────────────────


def test_old_registry_loads_with_enrichment(tmp_path: Path) -> None:
    old_registry = {
        "schema_version": 1,
        "external_skills": [
            {
                "skill_id": "legacy.skill",
                "source": "ecc",
                "source_type": "external_agent_pack",
                "display_name": "Legacy",
                "enabled": False,
                "risk": {"level": "medium", "requires_approval": True},
                "license": {"name": "unknown"},
            }
        ],
        "metadata": {},
    }
    path = tmp_path / "config" / "external_skill_registry.yml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.dump(old_registry), encoding="utf-8")

    loaded = load_skill_registry(tmp_path, path)
    skill = loaded["external_skills"][0]
    assert "lifecycle_status" in skill
    assert "inputs" in skill
    assert "outputs" in skill
    assert "quality" in skill
    assert skill["skill_id"] == "legacy.skill"


def test_existing_external_skill_dataclass_works() -> None:
    skill = ExternalSkill(
        skill_id="compat.test",
        source="agentlab_internal",
        source_type="internal_skill",
        display_name="Compat Test",
    )
    d = skill.to_dict()
    assert d["skill_id"] == "compat.test"
    assert d["enabled"] is False


# ── Valid Lifecycle Statuses ──────────────────────────────────────


def test_all_valid_lifecycle_statuses() -> None:
    expected = {"draft", "candidate", "pending_review", "staging",
                "active", "disabled", "rejected", "deprecated"}
    assert VALID_LIFECYCLE_STATUSES == expected


def test_valid_lifecycle_statuses_are_frozen() -> None:
    assert isinstance(VALID_LIFECYCLE_STATUSES, frozenset)
