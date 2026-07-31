from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
import pytest

from agent_runtime.narrative.author_team import (
    REQUIRED_AUTHOR_ROLES,
    build_author_team_manifests,
    load_author_team_contract,
    materialize_author_team_contract,
    register_author_team_proposal,
    select_author_team,
    validate_author_team_contract,
)
from agent_runtime.narrative.task_packet import _work_items
from agent_runtime.knowledge_system.storage import KnowledgeStore
from agent_runtime.project_agents import AgentRegistryError, ProjectAgentRegistry
from agent_runtime.project_agents.models import AgentManifest
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


def test_professional_team_uses_the_governed_alter_tier() -> None:
    profiles = yaml.safe_load(
        (ROOT / "config" / "agent_model_profiles.yml").read_text(
            encoding="utf-8"
        )
    )
    capacity = yaml.safe_load(
        (ROOT / "config" / "model_capacity.yml").read_text(encoding="utf-8")
    )
    professional = profiles["professional_role_profiles"]
    assert {
        profile["execution_tier"]
        for name, profile in professional.items()
        if name != "state_projector"
    } == {"alter"}
    routes = profiles["modes"]["full_cli"]["tiers"]["alter"]
    expected_workers = {
        "supervisor": "hermes",
        "researcher": "hermes",
        "narrative_planner": "agy",
        "writer": "agy",
        "reviewer": "agy",
    }
    for role, worker in expected_workers.items():
        route = routes[role]
        assert route["cli_agent"] == worker
        capacity_route = capacity["routes"][route["capacity_route"]]
        assert capacity_route["worker"] == worker
    for profile in professional.values():
        if profile["execution_kind"] != "cli_agent":
            continue
        strict_route = capacity["routes"][profile["capacity_route"]]
        assert strict_route["approved_fallbacks"] == []
        assert strict_route["fallback_on"] == []


def test_author_team_contract_declares_every_professional_role() -> None:
    result = validate_author_team_contract(_contract())

    assert result["status"] == "pass"
    assert set(result["roles"]) == set(REQUIRED_AUTHOR_ROLES)
    assert result["role_count"] == 13
    assert result["writer_boundary"]["self_review_forbidden"] is True
    assert result["writer_boundary"]["state_commit_forbidden"] is True
    assert result["state_projector"]["deterministic"] is True


def test_professional_task_packet_uses_only_professional_roles() -> None:
    items = _work_items(
        {
            "producer_id": "writer",
            "producer_kind": "prose",
            "producer_title": "Write",
        },
        professional_team=True,
        active_professional_roles=list(REQUIRED_AUTHOR_ROLES),
    )

    assert {item["work_item_id"] for item in items} == {
        "authorial-director",
        "brain-plan",
        "canon-timeline-steward",
        "world-archaeologist",
        "plot-causality-architect",
        "character-ensemble-director",
        "relationship-director",
        "foreshadow-mystery-keeper",
        "research-style-curator",
        "arc-scene-planner",
        "writer",
        "senior-editor",
        "reader-simulation-panel",
        "state-projector",
    }
    by_id = {item["work_item_id"]: item for item in items}
    assert by_id["brain-plan"]["depends_on"] == ["authorial-director"]
    assert by_id["canon-timeline-steward"]["depends_on"] == ["brain-plan"]
    assert by_id["writer"]["depends_on"] == ["arc-scene-planner"]
    assert by_id["state-projector"]["depends_on"] == [
        "senior-editor",
        "reader-simulation-panel",
    ]
    assert by_id["state-projector"]["requires_user_acceptance"] is True


def test_professional_task_packet_uses_selected_minimum_subgraph() -> None:
    contract = _contract()
    selected = select_author_team(contract, risk_flags=[])
    items = _work_items(
        {
            "producer_id": "writer",
            "producer_kind": "prose",
            "producer_title": "Write",
        },
        professional_team=True,
        active_professional_roles=selected["active_roles"],
    )

    assert {item["work_item_id"] for item in items} == {
        "authorial-director",
        "brain-plan",
        "canon-timeline-steward",
        "arc-scene-planner",
        "writer",
        "senior-editor",
        "state-projector",
    }
    by_id = {item["work_item_id"]: item for item in items}
    assert by_id["arc-scene-planner"]["depends_on"] == [
        "canon-timeline-steward"
    ]


def test_missing_professional_contract_field_blocks_team() -> None:
    contract = _contract()
    del contract["roles"]["relationship_director"]["knowledge_namespaces"]

    result = validate_author_team_contract(contract)

    assert result["status"] == "blocked"
    assert (
        "relationship_director:knowledge_namespaces_required"
        in result["issues"]
    )


def test_author_team_dependency_graph_rejects_unknown_and_cyclic_roles() -> None:
    unknown = _contract()
    unknown["roles"]["writer"]["dependencies"] = ["invented_role"]
    unknown_result = validate_author_team_contract(unknown)
    assert unknown_result["status"] == "blocked"
    assert "writer:unknown_dependency:invented_role" in unknown_result["issues"]
    assert unknown_result["dependency_dag"]["status"] == "blocked"

    cyclic = _contract()
    cyclic["roles"]["authorial_director"]["dependencies"] = ["writer"]
    cyclic_result = validate_author_team_contract(cyclic)
    assert cyclic_result["status"] == "blocked"
    assert any(
        issue.startswith("dependency_cycle:")
        for issue in cyclic_result["issues"]
    )
    assert cyclic_result["dependency_dag"]["status"] == "blocked"


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
    assert registered["dependency_dag_audit"]["status"] == "pass"
    assert registered["project_truth_audit"]["status"] == "pass"
    assert len(registered["knowledge_spaces"]) == 13
    assert len(
        {item["namespace"] for item in registered["knowledge_spaces"]}
    ) == 13
    knowledge_store = KnowledgeStore(tmp_path)
    for item in registered["knowledge_spaces"]:
        assert item["namespace"] == (
            f"agent.Example_Novel.{item['role_id']}"
        )
        assert knowledge_store.space_exists(item["namespace"])


def test_approved_proposal_migrates_only_the_v1_bootstrap_writer(
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
    registry = ProjectAgentRegistry(truth)
    registry.register(
        AgentManifest(
            id="writer",
            name="Writer Agent",
            version="1.0.0",
            role="writer",
            description="Project-scoped writer.",
            responsibilities=("Own writer decisions.",),
            runtime_role="Writer",
            read_scope=("*",),
            write_scope=("manuscript.*",),
            approval_scope=("manuscript.*",),
            knowledge_binding={"namespace": "agent.Example_Novel.writer"},
            model_profile="balanced",
            tool_permission=("knowledge.read",),
            budget_profile="standard",
            status="active",
            acceptance_rules=("scope_contract_satisfied",),
            collaboration={"reviewed_by": ["reviewer"]},
        ),
        expected_snapshot_id=pointer.current_snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )
    proposed = materialize_author_team_contract(
        tmp_path,
        project="Example_Novel",
        task_id="task_author_team",
        template_path=template,
    )

    registered = register_author_team_proposal(
        tmp_path,
        project="Example_Novel",
        proposal_path=tmp_path / proposed["proposal_path"],
        expected_proposal_sha256=proposed["proposal_sha256"],
        expected_snapshot_id=truth.current().snapshot_id,
        actor_id="user",
        approved=True,
    )

    assert registered["registration_mode"] == "migrated_legacy_writer"
    assert registry.get("writer").manifest_revision == 2
    assert {manifest.id for manifest in registry.list()} == set(
        REQUIRED_AUTHOR_ROLES
    )
    assert truth.audit()["status"] == "pass"


def test_approved_proposal_does_not_overwrite_a_custom_v1_writer(
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
    registry = ProjectAgentRegistry(truth)
    registry.register(
        AgentManifest(
            id="writer",
            name="Writer Agent",
            version="1.0.0",
            role="writer",
            description="Project-scoped writer.",
            responsibilities=("Own writer decisions.",),
            runtime_role="Writer",
            read_scope=("*", "private.notes.*"),
            write_scope=("manuscript.*",),
            approval_scope=("manuscript.*",),
            knowledge_binding={"namespace": "agent.Example_Novel.writer"},
            model_profile="balanced",
            tool_permission=("knowledge.read",),
            budget_profile="standard",
            status="active",
            acceptance_rules=("scope_contract_satisfied",),
            collaboration={"reviewed_by": ["reviewer"]},
        ),
        expected_snapshot_id=pointer.current_snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )
    proposed = materialize_author_team_contract(
        tmp_path,
        project="Example_Novel",
        task_id="task_author_team",
        template_path=template,
    )

    with pytest.raises(ValueError, match="partial existing team"):
        register_author_team_proposal(
            tmp_path,
            project="Example_Novel",
            proposal_path=tmp_path / proposed["proposal_path"],
            expected_proposal_sha256=proposed["proposal_sha256"],
            expected_snapshot_id=truth.current().snapshot_id,
            actor_id="user",
            approved=True,
        )

    assert registry.get("writer").read_scope == ("*", "private.notes.*")


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


def test_registration_cas_failure_retires_new_private_spaces(
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
    truth.initialize("Example_Novel")
    proposed = materialize_author_team_contract(
        tmp_path,
        project="Example_Novel",
        task_id="task_author_team",
        template_path=template,
    )
    proposal_path = tmp_path / proposed["proposal_path"]

    try:
        register_author_team_proposal(
            tmp_path,
            project="Example_Novel",
            proposal_path=proposal_path,
            expected_proposal_sha256=proposed["proposal_sha256"],
            expected_snapshot_id="stale-snapshot",
            actor_id="user",
            approved=True,
        )
    except AgentRegistryError:
        pass
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("stale CAS unexpectedly registered author team")

    knowledge_store = KnowledgeStore(tmp_path)
    assert all(
        not knowledge_store.space_exists(
            f"agent.Example_Novel.{role_id}"
        )
        for role_id in REQUIRED_AUTHOR_ROLES
    )
    assert ProjectAgentRegistry(truth).list() == []


def test_concurrent_registration_cannot_retire_active_team_spaces(
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

    def register_once() -> str:
        try:
            receipt = register_author_team_proposal(
                tmp_path,
                project="Example_Novel",
                proposal_path=tmp_path / proposed["proposal_path"],
                expected_proposal_sha256=proposed["proposal_sha256"],
                expected_snapshot_id=pointer.current_snapshot_id,
                actor_id="user",
                approved=True,
            )
        except (RuntimeError, ValueError):
            return "stale"
        return str(receipt["status"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: register_once(), range(2)))

    assert outcomes == ["registered", "registered"]
    assert {
        manifest.status for manifest in ProjectAgentRegistry(truth).list()
    } == {"active"}
    knowledge_store = KnowledgeStore(tmp_path)
    assert all(
        knowledge_store.space_exists(f"agent.Example_Novel.{role_id}")
        for role_id in REQUIRED_AUTHOR_ROLES
    )
    assert knowledge_store.inactive_spaces(
        [
            f"agent.Example_Novel.{role_id}"
            for role_id in REQUIRED_AUTHOR_ROLES
        ]
    ) == ()


def test_partial_knowledge_space_creation_is_rolled_back(
    tmp_path: Path,
    monkeypatch,
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
    original_ensure = KnowledgeStore.ensure_space
    calls = 0

    def fail_third_space(store: KnowledgeStore, namespace: str) -> Path:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated knowledge storage failure")
        return original_ensure(store, namespace)

    monkeypatch.setattr(KnowledgeStore, "ensure_space", fail_third_space)
    try:
        register_author_team_proposal(
            tmp_path,
            project="Example_Novel",
            proposal_path=tmp_path / proposed["proposal_path"],
            expected_proposal_sha256=proposed["proposal_sha256"],
            expected_snapshot_id=pointer.current_snapshot_id,
            actor_id="user",
            approved=True,
        )
    except OSError as exc:
        assert "knowledge storage failure" in str(exc)
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("partial knowledge creation was accepted")

    knowledge_store = KnowledgeStore(tmp_path)
    assert all(
        not knowledge_store.space_exists(
            f"agent.Example_Novel.{role_id}"
        )
        for role_id in REQUIRED_AUTHOR_ROLES
    )
    assert ProjectAgentRegistry(truth).list() == []


def test_failed_post_registration_audit_archives_team_and_retires_spaces(
    tmp_path: Path,
    monkeypatch,
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
    original_audit = ProjectTruthStore.audit
    calls = 0

    def fail_second_audit(store: ProjectTruthStore) -> dict:
        nonlocal calls
        calls += 1
        if calls == 2:
            return {"status": "fail"}
        return original_audit(store)

    monkeypatch.setattr(ProjectTruthStore, "audit", fail_second_audit)
    try:
        register_author_team_proposal(
            tmp_path,
            project="Example_Novel",
            proposal_path=proposal_path,
            expected_proposal_sha256=proposed["proposal_sha256"],
            expected_snapshot_id=pointer.current_snapshot_id,
            actor_id="user",
            approved=True,
        )
    except ValueError as exc:
        assert "compensated" in str(exc)
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("failed post-registration audit was accepted")

    manifests = ProjectAgentRegistry(truth).list()
    assert len(manifests) == 13
    assert {manifest.status for manifest in manifests} == {"archived"}
    knowledge_store = KnowledgeStore(tmp_path)
    assert all(
        not knowledge_store.space_exists(
            f"agent.Example_Novel.{role_id}"
        )
        for role_id in REQUIRED_AUTHOR_ROLES
    )

    monkeypatch.setattr(ProjectTruthStore, "audit", original_audit)
    retried = register_author_team_proposal(
        tmp_path,
        project="Example_Novel",
        proposal_path=proposal_path,
        expected_proposal_sha256=proposed["proposal_sha256"],
        expected_snapshot_id=truth.current().snapshot_id,
        actor_id="user",
        approved=True,
    )

    assert retried["status"] == "registered"
    assert retried["registration_mode"] == "reactivated_compensated_team"
    assert {manifest.status for manifest in ProjectAgentRegistry(truth).list()} == {
        "active"
    }
    assert all(
        knowledge_store.space_exists(f"agent.Example_Novel.{role_id}")
        for role_id in REQUIRED_AUTHOR_ROLES
    )


def test_failed_compensation_keeps_active_team_recoverable(
    tmp_path: Path,
    monkeypatch,
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
    original_audit = ProjectTruthStore.audit
    original_commit = ProjectTruthStore.commit
    audit_calls = 0

    def fail_second_audit(store: ProjectTruthStore) -> dict:
        nonlocal audit_calls
        audit_calls += 1
        if audit_calls == 2:
            return {"status": "fail"}
        return original_audit(store)

    def fail_compensation(store: ProjectTruthStore, change_set):
        if str(change_set.idempotency_key).startswith(
            "author-team-audit-compensation:"
        ):
            raise RuntimeError("simulated compensation storage failure")
        return original_commit(store, change_set)

    monkeypatch.setattr(ProjectTruthStore, "audit", fail_second_audit)
    monkeypatch.setattr(ProjectTruthStore, "commit", fail_compensation)
    try:
        register_author_team_proposal(
            tmp_path,
            project="Example_Novel",
            proposal_path=proposal_path,
            expected_proposal_sha256=proposed["proposal_sha256"],
            expected_snapshot_id=pointer.current_snapshot_id,
            actor_id="user",
            approved=True,
        )
    except RuntimeError as exc:
        assert "compensation storage failure" in str(exc)
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("failed compensation was silently accepted")

    knowledge_store = KnowledgeStore(tmp_path)
    assert all(
        knowledge_store.space_exists(f"agent.Example_Novel.{role_id}")
        for role_id in REQUIRED_AUTHOR_ROLES
    )
    assert {
        manifest.status for manifest in ProjectAgentRegistry(truth).list()
    } == {"active"}

    recovered = register_author_team_proposal(
        tmp_path,
        project="Example_Novel",
        proposal_path=proposal_path,
        expected_proposal_sha256=proposed["proposal_sha256"],
        expected_snapshot_id=truth.current().snapshot_id,
        actor_id="user",
        approved=True,
    )
    assert recovered["registration_mode"] == "existing_active_team"
    assert recovered["project_truth_audit"]["status"] == "pass"
