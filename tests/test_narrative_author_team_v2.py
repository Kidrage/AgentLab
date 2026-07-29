from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from agent_runtime.narrative.author_team import (
    REQUIRED_AUTHOR_ROLES,
    build_author_team_manifests,
    load_author_team_contract,
    materialize_author_team_contract,
    register_author_team_proposal,
    select_author_team,
    validate_author_team_contract,
)
from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_truth import ProjectTruthStore

ROOT = Path(__file__).resolve().parents[1]


def _contract() -> dict:
    return load_author_team_contract(ROOT)


def _copy_authority_configs(root: Path) -> Path:
    config = root / "config"
    config.mkdir()
    for name in (
        "narrative_author_team.yml",
        "agent_registry.yml",
        "agent_model_profiles.yml",
    ):
        (config / name).write_bytes((ROOT / "config" / name).read_bytes())
    return config / "narrative_author_team.yml"


def test_composition_contains_references_not_duplicate_role_or_model_authority() -> None:
    composition = yaml.safe_load(
        (ROOT / "config" / "narrative_author_team.yml").read_text(
            encoding="utf-8"
        )
    )
    registry = yaml.safe_load(
        (ROOT / "config" / "agent_registry.yml").read_text(encoding="utf-8")
    )

    assert composition["roles"] == list(REQUIRED_AUTHOR_ROLES)
    assert set(registry["professional_profiles"]) == set(REQUIRED_AUTHOR_ROLES)
    assert "model_tier" not in yaml.safe_dump(registry["professional_profiles"])


def test_author_team_contract_declares_every_professional_role() -> None:
    result = validate_author_team_contract(_contract())

    assert result["status"] == "pass"
    assert set(result["roles"]) == set(REQUIRED_AUTHOR_ROLES)
    assert result["role_count"] == 13
    assert result["writer_boundary"]["self_review_forbidden"] is True
    assert result["writer_boundary"]["state_commit_forbidden"] is True
    assert result["state_projector"]["deterministic"] is True


def test_missing_professional_contract_field_blocks_team() -> None:
    contract = _contract()
    del contract["roles"]["relationship_director"]["knowledge_namespaces"]

    result = validate_author_team_contract(contract)

    assert result["status"] == "blocked"
    assert (
        "relationship_director:knowledge_namespaces_required"
        in result["issues"]
    )


def test_writer_cannot_self_review_approve_or_commit_state() -> None:
    contract = _contract()
    writer = contract["roles"]["writer"]
    writer["forbidden_actions"].remove("commit_narrative_state")
    writer["authority"]["write"].append("project_brain/**")

    result = validate_author_team_contract(contract)

    assert result["status"] == "blocked"
    assert "writer:commit_narrative_state_must_be_forbidden" in result["issues"]
    assert "writer:project_state_write_forbidden" in result["issues"]


def test_state_projector_must_be_deterministic_and_non_generative() -> None:
    contract = _contract()
    projector = contract["roles"]["state_projector"]
    projector["runtime"]["deterministic"] = False
    projector["runtime"]["execution_kind"] = "cli_agent"

    result = validate_author_team_contract(contract)

    assert result["status"] == "blocked"
    assert "state_projector:deterministic_runtime_required" in result["issues"]
    assert "state_projector:generative_model_forbidden" in result["issues"]


def test_ordinary_chapter_activates_minimum_bounded_subgraph() -> None:
    result = select_author_team(_contract(), risk_flags=[])

    assert result["status"] == "pass"
    assert result["full_team"] is False
    assert result["active_roles"] == [
        "authorial_director",
        "canon_timeline_steward",
        "arc_scene_planner",
        "writer",
        "senior_editor",
        "state_projector",
    ]
    assert set(result["inactive_roles"]) == set(REQUIRED_AUTHOR_ROLES) - set(
        result["active_roles"]
    )


def test_specific_risks_activate_only_relevant_reviewers() -> None:
    result = select_author_team(
        _contract(),
        risk_flags=["relationship_progression", "foreshadow_payoff"],
    )

    assert result["full_team"] is False
    assert "relationship_director" in result["active_roles"]
    assert "foreshadow_mystery_keeper" in result["active_roles"]
    assert "reader_simulation_panel" in result["active_roles"]
    assert "world_archaeologist" not in result["active_roles"]


def test_major_event_activates_full_literary_team() -> None:
    for flag in (
        "battle",
        "death",
        "relationship_turn",
        "major_reveal",
        "volume_finale",
    ):
        result = select_author_team(_contract(), risk_flags=[flag])
        assert result["status"] == "pass"
        assert result["full_team"] is True
        assert set(result["active_roles"]) == set(REQUIRED_AUTHOR_ROLES)


def test_selection_refuses_invalid_or_unknown_risk_contracts() -> None:
    invalid = deepcopy(_contract())
    invalid["roles"].pop("writer")
    result = select_author_team(invalid, risk_flags=[])
    assert result["status"] == "blocked"

    unknown = select_author_team(_contract(), risk_flags=["invented_risk"])
    assert unknown["status"] == "blocked"
    assert unknown["issues"] == ["unknown_risk_flag:invented_risk"]


def test_materialized_project_contract_is_hash_bound_and_idempotent(
    tmp_path: Path,
) -> None:
    template = _copy_authority_configs(tmp_path)
    first = materialize_author_team_contract(
        tmp_path,
        project="Example_Novel",
        task_id="task_author_team",
        template_path=template,
    )
    second = materialize_author_team_contract(
        tmp_path,
        project="Example_Novel",
        task_id="task_author_team",
        template_path=template,
    )

    assert first["status"] == "proposed"
    assert second["status"] == "current"
    path = (
        tmp_path
        / "projects"
        / "Example_Novel"
        / "runs"
        / "task_author_team"
        / "artifacts"
        / "author_team_registration_proposal.yml"
    )
    proposal = yaml.safe_load(path.read_text(encoding="utf-8"))
    contract = proposal["contract"]
    assert contract["project_id"] == "Example_Novel"
    assert len(contract["template_binding"]["sha256"]) == 64
    assert validate_author_team_contract(contract)["status"] == "pass"
    assert first["production_modified"] is False
    assert not (
        tmp_path
        / "projects"
        / "Example_Novel"
        / "production"
        / "author_team_contract.yml"
    ).exists()


def test_approved_proposal_atomically_registers_canonical_project_agents(
    tmp_path: Path,
) -> None:
    template = _copy_authority_configs(tmp_path)
    project = tmp_path / "projects" / "Example_Novel"
    project.mkdir(parents=True)
    (project / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Example_Novel",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project)
    pointer = truth.initialize("Example_Novel")
    proposed = materialize_author_team_contract(
        tmp_path,
        project="Example_Novel",
        task_id="task_author_team",
        template_path=template,
    )
    proposal_path = tmp_path / proposed["proposal_path"]

    registered = register_author_team_proposal(
        tmp_path,
        project="Example_Novel",
        proposal_path=proposal_path,
        expected_proposal_sha256=proposed["proposal_sha256"],
        expected_snapshot_id=pointer.current_snapshot_id,
        actor_id="user",
        approved=True,
    )

    registry = ProjectAgentRegistry(truth)
    assert registered["status"] == "registered"
    assert {manifest.id for manifest in registry.list()} == set(
        REQUIRED_AUTHOR_ROLES
    )
    assert len(build_author_team_manifests(_contract())) == 13
    assert truth.audit()["status"] == "pass"


def test_materialization_rejects_project_path_escape(tmp_path: Path) -> None:
    template = _copy_authority_configs(tmp_path)
    try:
        materialize_author_team_contract(
            tmp_path,
            project="../escape",
            task_id="task_author_team",
            template_path=template,
        )
    except ValueError as exc:
        assert "project" in str(exc)
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("path escape was accepted")
