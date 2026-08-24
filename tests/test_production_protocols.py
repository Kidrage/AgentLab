from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from agent_runtime.production_protocols import (
    ProductionProtocolRunner,
    compile_production_protocol,
    prepare_protocol_task_if_present,
)
from agent_runtime.task_runtime_v2 import TaskRuntime


ROOT = Path(__file__).resolve().parents[1]


def test_compiles_large_code_protocol_from_declared_facts() -> None:
    graph = compile_production_protocol(
        ROOT,
        protocol_ref="code.large.v1",
        task_facts={
            "kind": "code_build",
            "scope": "large",
            "repository": "fixture-repository",
        },
    )

    assert graph.protocol_ref == "code.large.v1"
    assert graph.pack_id == "code_factory"
    assert [binding.role for binding in graph.role_bindings] == [
        "Supervisor",
        "RepoScout",
        "InterfaceMapper",
        "Coder",
        "TesterAuditor",
        "Verifier",
    ]
    assert graph.role_bindings[-1].depends_on == ("independent_validation",)
    assert graph.promotion_gates == (
        "tests_pass",
        "independent_review",
        "ci_or_human_acceptance",
    )

    with pytest.raises(ValueError, match="required task facts: repository"):
        compile_production_protocol(
            ROOT,
            protocol_ref="code.large.v1",
            task_facts={"kind": "code_build", "scope": "large"},
        )


def test_compiles_narrative_protocol_with_minimum_risk_selected_team() -> None:
    graph = compile_production_protocol(
        ROOT,
        protocol_ref="narrative.chapter.v1",
        task_facts={
            "kind": "prose_build",
            "scope": "single_chapter",
            "chapter": 1,
            "risk_flags": [],
        },
    )

    assert [binding.profile for binding in graph.role_bindings] == [
        "authorial_director",
        "canon_timeline_steward",
        "arc_scene_planner",
        "writer",
        "senior_editor",
        "state_projector",
    ]
    assert graph.role_bindings[-1].depends_on == ("senior_editor",)
    assert graph.promotion_gates == (
        "candidate_hash_bound",
        "independent_editor_acceptance",
        "deterministic_state_projection",
        "user_acceptance",
    )


def test_compiles_film_protocol_as_locked_staged_dry_run() -> None:
    graph = compile_production_protocol(
        ROOT,
        protocol_ref="film.production.v1",
        task_facts={
            "kind": "film_build",
            "scope": "feature",
            "source_story_artifact": "story/story_bible.yml",
        },
    )

    assert [binding.profile for binding in graph.role_bindings] == [
        "screenplay_adapter",
        "production_designer",
        "previs_director",
        "picture_producer",
        "sound_producer",
        "post_producer",
        "film_qc_reviewer",
        "master_verifier",
    ]
    picture = next(item for item in graph.role_bindings if item.node_id == "picture_generation")
    sound = next(item for item in graph.role_bindings if item.node_id == "sound_generation")
    assert picture.depends_on == sound.depends_on == ("director_previs",)
    assert graph.role_bindings[-1].depends_on == ("independent_qc",)
    assert all(contract.candidate_only for contract in graph.artifact_contracts)
    assert graph.promotion_gates[-1] == "human_master_approval"


def test_protocol_runner_binds_graph_and_materializes_work_items_idempotently(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in ("production_packs.yml", "task_input_tiers.yml"):
        shutil.copy2(ROOT / "config" / name, config / name)
    runtime = TaskRuntime(tmp_path, project="CodeCanary")
    runtime.create_task(
        task_id="task-code-canary",
        title="Repair the fixture repository",
        user_goal="Produce one tested candidate patch.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "repository": "fixture-repository",
        },
        idempotency_key="create-code-canary",
    )

    runner = ProductionProtocolRunner(tmp_path, project="CodeCanary")
    first = runner.prepare("task-code-canary")
    second = runner.prepare("task-code-canary")

    assert second == first
    assert first["task"]["compiled_protocol"]["protocol_ref"] == "code.large.v1"
    assert list(first["work_items"]) == [
        "supervisor_plan",
        "repository_context",
        "interface_contract",
        "implementation",
        "independent_validation",
        "promotion_verification",
    ]
    assert first["work_items"]["supervisor_plan"]["status"] == "ready"
    assert first["work_items"]["repository_context"]["status"] == "pending"
    assert first["last_event_sequence"] == 3
    assert prepare_protocol_task_if_present(
        tmp_path,
        project="CodeCanary",
        task_id="task-code-canary",
    ) == first
    assert not (tmp_path / "projects" / "CodeCanary" / "runs" / "task-code-canary").exists()
