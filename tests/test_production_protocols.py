from __future__ import annotations

from pathlib import Path
import hashlib
import json
import shutil

import pytest
import yaml

from agent_runtime.production_protocols import (
    ProductionProtocolRunner,
    _artifact_output_issues,
    compile_production_protocol,
    prepare_protocol_task_if_present,
)
from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.task_runtime_v2 import InvalidTransition, TaskRuntime


ROOT = Path(__file__).resolve().parents[1]


def _succeed_deterministically(
    runtime: TaskRuntime,
    *,
    task_id: str,
    node_id: str,
    role: str,
    attempt_id: str | None = None,
    source_paths: list[Path] | None = None,
) -> tuple[dict, Path]:
    projection = runtime.load_task(task_id)
    classification = projection["task"]["input_classification"]
    work_item = projection["work_items"][node_id]
    attempt_id = attempt_id or f"attempt-{node_id}"
    deterministic = work_item.get("execution_kind") == "deterministic_tool"
    worker = f"fixture-worker-{node_id}"
    provider = "agentlab-deterministic" if deterministic else "fixture-provider"
    tool = {
        "tool_id": f"agentlab.protocol.{work_item.get('profile') or node_id}",
        "tool_version": "1",
        "node_id": node_id,
    }
    execution_contract = {
        "role": role,
        "executor_type": "deterministic_tool" if deterministic else "cli_agent",
        "input_tier": classification["tier"],
        "route": classification["route"],
        "agent_model_profile": work_item.get("agent_model_profile"),
    }
    if deterministic:
        execution_contract["deterministic_tool"] = tool
    else:
        execution_contract.update(
            {
                "invocation_contract": "test-protocol-fixture",
                "model_key": "fixture",
                "model_id": "fixture-model",
                "runtime_provider": provider,
            }
        )
    runtime.schedule_attempt(
        task_id,
        work_item_id=node_id,
        attempt_id=attempt_id,
        worker=worker,
        provider=provider,
        execution_contract=execution_contract,
        idempotency_key=f"schedule-{node_id}",
    )
    runtime.transition_attempt(
        task_id,
        attempt_id=attempt_id,
        status="running",
        idempotency_key=f"running-{node_id}",
    )
    task_root = runtime._task_dir(task_id)
    attempt_root = task_root / "attempt_logs" / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=True)
    output = attempt_root / "output.md"
    atomic_write_text(output, f"# {node_id}\n")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    model_execution = None
    if not deterministic:
        model_receipt = attempt_root / "model_execution_receipt.yml"
        atomic_write_yaml(
            model_receipt,
            {
                "status": "pass",
                "worker": worker,
                "invocation_contract": "test-protocol-fixture",
                "role": role,
                "selected_provider": provider,
                "selected_model_id": "fixture-model",
                "profile_binding_verified": True,
                "command_binding_verified": True,
                "fallback_detected": False,
                "provider_process_started": True,
                "exit_code": 0,
                "issues": [],
                "provider_model_binding_verified": True,
            },
        )
        model_execution = {
            "path": model_receipt.relative_to(task_root).as_posix(),
            "sha256": hashlib.sha256(model_receipt.read_bytes()).hexdigest(),
            "cli_agent": worker,
            "model_key": "fixture",
            "model_id": "fixture-model",
            "runtime_provider": provider,
            "executor_provider": "agentlab-cli-executor",
        }
    receipt = attempt_root / (
        "deterministic_execution_receipt.yml"
        if deterministic
        else "attempt_receipt.yml"
    )
    receipt_document = {
        "schema_version": (
            "task-runtime-deterministic-attempt-receipt/v1"
            if deterministic
            else "task-runtime-role-attempt-receipt/v1"
        ),
        "project": runtime.project,
        "task_id": task_id,
        "work_item_id": node_id,
        "attempt_id": attempt_id,
        "role": role,
        "worker": worker,
        "provider": provider,
        "status": "pass",
        "output_path": output.relative_to(task_root).as_posix(),
        "output_sha256": output_sha256,
        "sealed_sources": [
            {
                "path": path.resolve(strict=True)
                .relative_to(runtime.agentlab_root)
                .as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in source_paths or []
        ],
        "model_execution": model_execution,
    }
    if deterministic:
        receipt_document["deterministic_tool"] = tool
    atomic_write_yaml(receipt, receipt_document)
    outcome = {
        "execution_origin": (
            "deterministic_tool_executor" if deterministic else "role_attempt_executor"
        ),
        "receipt_path": receipt.relative_to(task_root).as_posix(),
        "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "output_sha256": output_sha256,
    }
    if deterministic:
        projection = runtime._transition_deterministic_attempt(
            task_id,
            attempt_id=attempt_id,
            idempotency_key=f"succeeded-{node_id}",
            outcome=outcome,
        )
    else:
        projection = runtime._transition_executed_attempt(
            task_id,
            attempt_id=attempt_id,
            status="succeeded",
            idempotency_key=f"succeeded-{node_id}",
            outcome=outcome,
        )
    return projection, output


def test_compiles_large_code_protocol_from_declared_facts() -> None:
    graph = compile_production_protocol(
        ROOT,
        protocol_ref="code.large.v1",
        task_facts={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
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
            task_facts={
                "kind": "code_build",
                "scope": "large",
                "target_count": 6,
                "canon_impact": "none",
                "risk_flags": [],
            },
        )

    with pytest.raises(ValueError, match="fact kind"):
        compile_production_protocol(
            ROOT,
            protocol_ref="code.large.v1",
            task_facts={
                "kind": "prose_build",
                "scope": "large",
                "target_count": 6,
                "canon_impact": "none",
                "risk_flags": [],
                "repository": "fixture-repository",
            },
        )

    with pytest.raises(ValueError, match="unknown task facts: typo_repository"):
        compile_production_protocol(
            ROOT,
            protocol_ref="code.large.v1",
            task_facts={
                "kind": "code_build",
                "scope": "large",
                "target_count": 6,
                "canon_impact": "none",
                "risk_flags": [],
                "repository": "fixture-repository",
                "typo_repository": "ignored",
            },
        )


def test_compiles_narrative_protocol_with_minimum_risk_selected_team() -> None:
    graph = compile_production_protocol(
        ROOT,
        protocol_ref="narrative.chapter.v1",
        task_facts={
            "kind": "prose_build",
            "scope": "single_chapter",
            "target_count": 1,
            "canon_impact": "none",
            "chapter": 1,
            "risk_flags": [],
            "source_story_bible": "examples/novel_canary/story_bible.yml",
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


def test_compiles_blueprint_protocol_with_full_professional_team() -> None:
    graph = compile_production_protocol(
        ROOT,
        protocol_ref="narrative.blueprint.v1",
        task_facts={
            "kind": "blueprint_build",
            "scope": "longform",
            "target_count": 600,
            "canon_impact": "new_project",
            "risk_flags": [],
            "project": "ShanHeYouJia",
            "source_creative_brief": "examples/shanhe_youjia/creative_brief.yml",
            "source_creative_brief_sha256": "a" * 64,
        },
    )

    assert graph.pack_id == "narrative_blueprint"
    assert [binding.profile for binding in graph.role_bindings] == [
        "authorial_director",
        "canon_timeline_steward",
        "plot_causality_architect",
        "character_ensemble_director",
        "relationship_director",
        "world_archaeologist",
        "foreshadow_mystery_keeper",
        "arc_scene_planner",
        "research_style_curator",
        "writer",
        "senior_editor",
        "reader_simulation_panel",
        "state_projector",
    ]
    projector = graph.role_bindings[-1]
    assert set(projector.depends_on) == {"senior_editor", "reader_simulation_panel"}
    assert graph.result_artifact_type == "narrative_bootstrap_manifest"
    assert graph.promotion_gates == (
        "candidate_hash_bound",
        "independent_blueprint_review",
        "deterministic_bootstrap_projection",
        "user_blueprint_acceptance",
    )
    foreshadow = next(
        binding
        for binding in graph.role_bindings
        if binding.node_id == "foreshadow_mystery_keeper"
    )
    assert "Evolve promises" in " ".join(
        foreshadow.role_contract["professional_duties"]
    )
    promise_contract = next(
        contract
        for contract in graph.artifact_contracts
        if contract.artifact_type == "promise_registry"
    )
    assert promise_contract.required_markers == (
        "promise_id",
        "due_window",
        "payoff",
    )
    assert promise_contract.unique_content is True


def test_protocol_artifact_validation_rejects_duplicate_role_output() -> None:
    content = "promise_id: p-001\ndue_window: [10, 20]\npayoff: reveal\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    issues = _artifact_output_issues(
        {
            "artifact_type": "promise_registry",
            "required_markers": ["promise_id", "due_window", "payoff"],
            "minimum_bytes": 20,
            "unique_content": True,
        },
        content,
        existing_artifacts={
            "version-causality": {
                "artifact_id": "causality_blueprint",
                "sha256": digest,
            }
        },
    )

    assert issues == [
        "artifact_content_duplicates_existing_type:promise_registry:causality_blueprint"
    ]


def test_compiles_film_protocol_as_locked_staged_dry_run() -> None:
    graph = compile_production_protocol(
        ROOT,
        protocol_ref="film.production.v1",
        task_facts={
            "kind": "film_build",
            "scope": "feature",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
            "source_story_artifact": "story/story_bible.yml",
        },
    )

    assert [binding.profile for binding in graph.role_bindings] == [
        "source_story_locker",
        "screenplay_adapter",
        "production_designer",
        "sound_bible_designer",
        "previs_director",
        "picture_producer",
        "sound_producer",
        "post_producer",
        "film_qc_reviewer",
        "master_verifier",
    ]
    picture = next(
        item for item in graph.role_bindings if item.node_id == "picture_generation"
    )
    sound = next(
        item for item in graph.role_bindings if item.node_id == "sound_generation"
    )
    assert picture.depends_on == sound.depends_on == ("director_previs",)
    assert graph.role_bindings[-1].depends_on == ("independent_qc",)
    assert all(contract.candidate_only for contract in graph.artifact_contracts)
    assert graph.promotion_gates[-1] == "human_master_approval"
    catalog = yaml.safe_load(
        (ROOT / "config" / "production_packs.yml").read_text(encoding="utf-8")
    )
    film_pack = next(
        pack
        for pack in catalog["packs"]
        if pack["pack_id"] == "media_series_production"
    )
    required_output_types = {
        Path(output).stem for output in film_pack["required_outputs"]
    }
    assert required_output_types.issubset(
        {contract.artifact_type for contract in graph.artifact_contracts}
    )


def test_protocol_runner_binds_graph_and_materializes_work_items_idempotently(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
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
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": "fixture-repository",
        },
        idempotency_key="create-code-canary",
    )

    runner = ProductionProtocolRunner(tmp_path, project="CodeCanary")
    first = runner.prepare("task-code-canary")
    catalog_path = config / "production_packs.yml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    code_pack = next(pack for pack in catalog["packs"] if pack["pack_id"] == "code_factory")
    source_patch = next(
        contract
        for contract in code_pack["protocol"]["artifact_contracts"]
        if contract["artifact_type"] == "source_patch"
    )
    source_patch["minimum_bytes"] = 999
    atomic_write_yaml(catalog_path, catalog)
    second = runner.prepare("task-code-canary")

    assert second == first
    bound_source_patch = next(
        contract
        for contract in second["task"]["compiled_protocol"]["artifact_contracts"]
        if contract["artifact_type"] == "source_patch"
    )
    assert bound_source_patch["minimum_bytes"] == 1
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
    assert (
        prepare_protocol_task_if_present(
            tmp_path,
            project="CodeCanary",
            task_id="task-code-canary",
        )
        == first
    )
    assert not (
        tmp_path / "projects" / "CodeCanary" / "runs" / "task-code-canary"
    ).exists()


def test_compiled_protocol_graph_rejects_generic_node_injection(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    runtime = TaskRuntime(tmp_path, project="LockedGraph")
    runtime.create_task(
        task_id="task-locked",
        title="Locked graph",
        user_goal="Keep the compiled graph immutable.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": "fixture-repository",
        },
        idempotency_key="create-locked",
    )
    ProductionProtocolRunner(tmp_path, project="LockedGraph").prepare("task-locked")

    with pytest.raises(InvalidTransition, match="compiled protocol graph"):
        runtime.create_work_item(
            "task-locked",
            job_id="job-main",
            work_item_id="injected",
            kind="implementation",
            title="Injected node",
            idempotency_key="inject-node",
        )

    classification = runtime.load_task("task-locked")["task"]["input_classification"]
    with pytest.raises(InvalidTransition, match="executor type"):
        runtime.schedule_attempt(
            "task-locked",
            work_item_id="supervisor_plan",
            attempt_id="attempt-impersonated-projector",
            worker="fixture-projector",
            provider="agentlab-deterministic",
            execution_contract={
                "role": "Supervisor",
                "executor_type": "deterministic_tool",
                "input_tier": classification["tier"],
                "route": classification["route"],
                "deterministic_tool": {
                    "tool_id": "agentlab.protocol.supervisor_plan",
                    "tool_version": "1",
                },
            },
            idempotency_key="schedule-impersonated-projector",
        )


def test_protocol_acceptance_requires_attempt_artifacts_and_gates(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    runtime = TaskRuntime(tmp_path, project="EnforcedGraph")
    runtime.create_task(
        task_id="task-enforced",
        title="Enforced graph",
        user_goal="Do not accept unevidenced protocol nodes.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": "fixture-repository",
        },
        idempotency_key="create-enforced",
    )
    ProductionProtocolRunner(tmp_path, project="EnforcedGraph").prepare("task-enforced")
    runtime.transition_work_item(
        "task-enforced",
        work_item_id="supervisor_plan",
        status="running",
        idempotency_key="start-supervisor",
    )

    with pytest.raises(InvalidTransition, match="successful Attempt"):
        runtime.transition_work_item(
            "task-enforced",
            work_item_id="supervisor_plan",
            status="accepted",
            idempotency_key="accept-supervisor",
        )

    def succeed(node_id: str, role: str) -> None:
        projection, output = _succeed_deterministically(
            runtime,
            task_id="task-enforced",
            node_id=node_id,
            role=role,
        )
        attempt_id = f"attempt-{node_id}"
        validation_receipt = output.parent / "artifact_validation_receipt.yml"
        atomic_write_yaml(
            validation_receipt,
            {
                "schema_version": "protocol-artifact-validation/v1",
                "status": "pass",
                "task_id": "task-enforced",
                "attempt_id": attempt_id,
                "output_sha256": projection["attempts"][attempt_id]["outcome"][
                    "output_sha256"
                ],
                "issues": [],
            },
        )
        runtime.record_attempt_output_validation(
            "task-enforced",
            attempt_id=attempt_id,
            status="pass",
            validation_receipt_path=validation_receipt,
            issues=[],
            idempotency_key=f"validate-{node_id}",
        )

    succeed("supervisor_plan", "Supervisor")
    runtime.transition_work_item(
        "task-enforced",
        work_item_id="supervisor_plan",
        status="accepted",
        idempotency_key="accept-supervisor-with-attempt",
    )
    for node_id, role in (
        ("repository_context", "RepoScout"),
        ("interface_contract", "InterfaceMapper"),
    ):
        runtime.transition_work_item(
            "task-enforced",
            work_item_id=node_id,
            status="running",
            idempotency_key=f"start-{node_id}",
        )
        succeed(node_id, role)
        runtime.transition_work_item(
            "task-enforced",
            work_item_id=node_id,
            status="accepted",
            idempotency_key=f"accept-{node_id}",
        )
    runtime.transition_work_item(
        "task-enforced",
        work_item_id="implementation",
        status="running",
        idempotency_key="start-implementation",
    )
    succeed("implementation", "Coder")

    with pytest.raises(InvalidTransition, match="coherent Attempt for: source_patch"):
        runtime.transition_work_item(
            "task-enforced",
            work_item_id="implementation",
            status="accepted",
            idempotency_key="accept-implementation-without-artifact",
        )

    artifact_path = (
        runtime._task_dir("task-enforced")
        / "artifacts"
        / "staging"
        / "source_patch.diff"
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("+stable\n", encoding="utf-8")
    runtime.record_artifact_version(
        "task-enforced",
        artifact_id="source_patch",
        version_id="version-source-patch",
        attempt_id="attempt-implementation",
        path=artifact_path,
        media_type="text/x-diff",
        idempotency_key="record-source-patch",
    )
    runtime.transition_work_item(
        "task-enforced",
        work_item_id="implementation",
        status="accepted",
        idempotency_key="accept-implementation",
    )
    runtime.transition_work_item(
        "task-enforced",
        work_item_id="independent_validation",
        status="running",
        idempotency_key="start-validation",
    )
    succeed("independent_validation", "TesterAuditor")
    validation_path = artifact_path.with_name("validation_report.md")
    validation_path.write_text("tests: pass\n", encoding="utf-8")
    runtime.record_artifact_version(
        "task-enforced",
        artifact_id="validation_report",
        version_id="version-validation-report",
        attempt_id="attempt-independent_validation",
        path=validation_path,
        media_type="text/markdown",
        idempotency_key="record-validation-report",
    )

    with pytest.raises(InvalidTransition, match="promotion gates: tests_pass"):
        runtime.transition_work_item(
            "task-enforced",
            work_item_id="independent_validation",
            status="accepted",
            idempotency_key="accept-validation-without-gate",
        )

    validation_sha = hashlib.sha256(validation_path.read_bytes()).hexdigest()
    runtime.record_protocol_gate(
        "task-enforced",
        gate_id="tests_pass",
        work_item_id="independent_validation",
        evidence_kind="automated",
        evidence_sha256=hashlib.sha256(
            json.dumps(
                {"validation_report": validation_sha},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        attempt_id="attempt-independent_validation",
        subject_version_ids=["version-validation-report"],
        actor="fixture-validator",
        idempotency_key="gate-tests-pass",
    )
    runtime.transition_work_item(
        "task-enforced",
        work_item_id="independent_validation",
        status="accepted",
        idempotency_key="accept-validation",
    )
    runtime.transition_work_item(
        "task-enforced",
        work_item_id="promotion_verification",
        status="running",
        idempotency_key="start-promotion",
    )
    succeed("promotion_verification", "Verifier")
    verification_path = artifact_path.with_name("verification_report.md")
    verification_path.write_text("review: pass\n", encoding="utf-8")
    runtime.record_artifact_version(
        "task-enforced",
        artifact_id="verification_report",
        version_id="version-verification-report",
        attempt_id="attempt-promotion_verification",
        path=verification_path,
        media_type="text/markdown",
        idempotency_key="record-verification-report",
    )
    source_patch_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    with pytest.raises(InvalidTransition, match="was not sealed"):
        runtime.record_protocol_gate(
            "task-enforced",
            gate_id="independent_review",
            work_item_id="promotion_verification",
            evidence_kind="independent",
            evidence_sha256=hashlib.sha256(
                json.dumps(
                    {"source_patch": source_patch_sha},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            attempt_id="attempt-promotion_verification",
            subject_version_ids=["version-source-patch"],
            actor="fixture-reviewer",
            idempotency_key="gate-unsealed-review",
        )


def test_protocol_runner_executes_one_bound_node_through_executor_seam(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    runtime = TaskRuntime(tmp_path, project="LiveProtocol")
    runtime.create_task(
        task_id="task-live",
        title="Execute bound node",
        user_goal="Enter the governed executor from the compiled protocol.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": "fixture-repository",
        },
        idempotency_key="create-live",
    )
    calls: list[str] = []
    received_messages: list[dict[str, str]] = []

    class FixtureExecutor:
        def execute(self, **kwargs):
            calls.append(kwargs["role"])
            received_messages.extend(kwargs["messages"])
            projection, output = _succeed_deterministically(
                runtime,
                task_id=kwargs["task_id"],
                node_id=kwargs["work_item_id"],
                role=kwargs["role"],
                attempt_id=kwargs["attempt_id"],
                source_paths=kwargs["source_paths"],
            )
            return {
                "projection": projection,
                "output_path": str(output),
                "receipt_path": None,
            }

    runner = ProductionProtocolRunner(
        tmp_path,
        project="LiveProtocol",
        role_executor_factory=lambda _root, _project: FixtureExecutor(),
    )
    result = runner.execute_node(
        "task-live",
        work_item_id="supervisor_plan",
        messages=[{"role": "user", "content": "Plan the work."}],
        source_paths=[],
        external_context_request={"purpose": "fixture"},
        idempotency_key="execute-supervisor",
    )

    assert result["status"] == "accepted"
    assert result["projection"]["work_items"]["supervisor_plan"]["status"] == "accepted"
    assert calls == ["Supervisor"]
    assert received_messages[0]["content"].startswith("PROTOCOL_ROLE_CONTRACT/v1")
    assert received_messages[1] == {"role": "user", "content": "Plan the work."}


def test_protocol_runner_validates_sources_before_starting_work_item(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    runtime = TaskRuntime(tmp_path, project="SourceAdmission")
    runtime.create_task(
        task_id="task-source-admission",
        title="Validate source before mutation",
        user_goal="Reject missing governed sources without starting work.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": "missing-repository",
        },
        idempotency_key="create-source-admission",
    )

    class FixtureExecutor:
        def execute(self, **kwargs):
            projection, output = _succeed_deterministically(
                runtime,
                task_id=kwargs["task_id"],
                node_id=kwargs["work_item_id"],
                role=kwargs["role"],
                attempt_id=kwargs["attempt_id"],
                source_paths=kwargs["source_paths"],
            )
            return {"projection": projection, "output_path": str(output)}

    runner = ProductionProtocolRunner(
        tmp_path,
        project="SourceAdmission",
        role_executor_factory=lambda _root, _project: FixtureExecutor(),
    )
    runner.execute_node(
        "task-source-admission",
        work_item_id="supervisor_plan",
        messages=[{"role": "user", "content": "Plan."}],
        source_paths=[],
        external_context_request={"purpose": "fixture"},
        idempotency_key="execute-source-plan",
    )

    with pytest.raises(InvalidTransition, match="source fact is unavailable"):
        runner.execute_node(
            "task-source-admission",
            work_item_id="repository_context",
            messages=[{"role": "user", "content": "Read source."}],
            source_paths=[],
            external_context_request={"purpose": "fixture"},
            idempotency_key="execute-missing-source",
        )

    projection = runtime.load_task("task-source-admission")
    assert projection["work_items"]["repository_context"]["status"] == "ready"
    assert projection["work_items"]["repository_context"]["active_attempt_id"] is None


def test_protocol_runner_rejects_absolute_source_before_reading_outside_root(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    runtime = TaskRuntime(tmp_path, project="OutsideSource")
    runtime.create_task(
        task_id="task-outside-source",
        title="Reject outside source",
        user_goal="Never inspect an absolute source outside AgentLab.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": "/etc/passwd",
        },
        idempotency_key="create-outside-source",
    )

    with pytest.raises(InvalidTransition, match="outside the AgentLab root"):
        ProductionProtocolRunner(tmp_path, project="OutsideSource").execute_node(
            "task-outside-source",
            work_item_id="repository_context",
            messages=[{"role": "user", "content": "Do not read it."}],
            source_paths=[Path("/etc/passwd")],
            external_context_request={"purpose": "fixture"},
            idempotency_key="execute-outside-source",
        )

    projection = runtime.load_task("task-outside-source")
    assert projection["work_items"]["repository_context"]["status"] == "pending"
    assert projection["attempts"] == {}


def test_protocol_runner_rejects_sensitive_source_before_reading(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    sensitive = tmp_path / ".env"
    sensitive.write_text("PRIVATE_FIXTURE=never-read\n", encoding="utf-8")
    expected_hash = hashlib.sha256(sensitive.read_bytes()).hexdigest()
    runtime = TaskRuntime(tmp_path, project="SensitiveSource")
    runtime.create_task(
        task_id="task-sensitive-source",
        title="Reject sensitive source",
        user_goal="Never inspect sensitive sources even with a matching hash.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": str(sensitive),
            "repository_sha256": expected_hash,
        },
        idempotency_key="create-sensitive-source",
    )

    with pytest.raises(InvalidTransition, match="source fact is sensitive"):
        ProductionProtocolRunner(tmp_path, project="SensitiveSource").execute_node(
            "task-sensitive-source",
            work_item_id="repository_context",
            messages=[{"role": "user", "content": "Do not read it."}],
            source_paths=[sensitive],
            external_context_request={"purpose": "fixture"},
            idempotency_key="execute-sensitive-source",
        )

    projection = runtime.load_task("task-sensitive-source")
    assert projection["attempts"] == {}


def test_compiled_protocol_binding_is_compiler_authoritative_and_repeat_safe(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    runtime = TaskRuntime(tmp_path, project="CompilerAuthority")
    facts = {
        "kind": "code_build",
        "scope": "large",
        "target_count": 6,
        "canon_impact": "none",
        "risk_flags": [],
        "repository": "fixture-repository",
    }
    runtime.create_task(
        task_id="task-authority",
        title="Compiler authority",
        user_goal="Bind only the configured graph.",
        protocol_ref="code.large.v1",
        input_profile=facts,
        idempotency_key="create-authority",
    )
    graph = compile_production_protocol(
        tmp_path, protocol_ref="code.large.v1", task_facts=facts
    ).as_dict()
    first = runtime.bind_compiled_protocol(
        "task-authority",
        compiled_graph=graph,
        idempotency_key="bind-authority",
    )
    repeated = runtime.bind_compiled_protocol(
        "task-authority",
        compiled_graph=graph,
        idempotency_key="bind-authority-again",
    )
    assert repeated == first
    assert repeated["last_event_sequence"] == 2

    forged = dict(graph)
    forged["artifact_contracts"] = []
    with pytest.raises(InvalidTransition, match="compiler authority"):
        other = TaskRuntime(tmp_path, project="ForgedAuthority")
        other.create_task(
            task_id="task-forged",
            title="Forged authority",
            user_goal="Reject a reduced production policy.",
            protocol_ref="code.large.v1",
            input_profile=facts,
            idempotency_key="create-forged",
        )
        other.bind_compiled_protocol(
            "task-forged",
            compiled_graph=forged,
            idempotency_key="bind-forged",
        )


def test_protocol_task_cannot_disable_strict_receipts(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    shutil.copy2(
        ROOT / "config" / "task_input_tiers.yml",
        tmp_path / "config" / "task_input_tiers.yml",
    )
    runtime = TaskRuntime(tmp_path, project="NoLegacyProtocol")
    with pytest.raises(ValueError, match="cannot use legacy_source"):
        runtime.create_task(
            task_id="task-no-legacy",
            title="No legacy protocol",
            user_goal="Never downgrade strict receipt enforcement.",
            protocol_ref="code.large.v1",
            input_profile={
                "kind": "code_build",
                "scope": "large",
                "target_count": 6,
                "canon_impact": "none",
                "risk_flags": [],
                "repository": "fixture-repository",
            },
            legacy_source={},
            idempotency_key="create-no-legacy",
        )


def test_large_code_runner_passes_declared_repository_and_predecessor_sources(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    repository = tmp_path / "projects" / "GovernedSources" / "production" / "repo"
    repository.mkdir(parents=True)
    source = repository / "README.md"
    atomic_write_text(source, "# governed repository\n")
    runtime = TaskRuntime(tmp_path, project="GovernedSources")
    runtime.create_task(
        task_id="task-sources",
        title="Governed sources",
        user_goal="Carry immutable context through the compiled graph.",
        protocol_ref="code.large.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": str(repository),
        },
        idempotency_key="create-sources",
    )
    observed_sources: dict[str, list[Path]] = {}

    class FixtureExecutor:
        def execute(self, **kwargs):
            observed_sources[kwargs["work_item_id"]] = list(kwargs["source_paths"])
            projection, output = _succeed_deterministically(
                runtime,
                task_id=kwargs["task_id"],
                node_id=kwargs["work_item_id"],
                role=kwargs["role"],
                attempt_id=kwargs["attempt_id"],
                source_paths=kwargs["source_paths"],
            )
            return {"projection": projection, "output_path": str(output)}

    runner = ProductionProtocolRunner(
        tmp_path,
        project="GovernedSources",
        role_executor_factory=lambda _root, _project: FixtureExecutor(),
    )
    runner.execute_node(
        "task-sources",
        work_item_id="supervisor_plan",
        messages=[{"role": "user", "content": "Plan."}],
        source_paths=[],
        external_context_request={"purpose": "fixture"},
        idempotency_key="execute-plan",
    )
    second = runner.execute_node(
        "task-sources",
        work_item_id="repository_context",
        messages=[{"role": "user", "content": "Read governed source."}],
        source_paths=[source],
        external_context_request={"purpose": "fixture"},
        idempotency_key="execute-context",
    )

    assert second["status"] == "accepted"
    assert source.resolve() in observed_sources["repository_context"]
    assert any(
        path.name == "output.md" and "attempt-supervisor_plan" in path.as_posix()
        for path in observed_sources["repository_context"]
    )


def test_runner_executes_deterministic_protocol_profile_without_cli(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    catalog_path = config / "production_packs.yml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["packs"].append(
        {
            "pack_id": "deterministic_fixture",
            "protocol": {
                "ref": "test.deterministic.v1",
                "required_facts": [
                    "kind",
                    "scope",
                    "target_count",
                    "canon_impact",
                    "risk_flags",
                ],
                "fact_constraints": {
                    "kind": ["prose_build"],
                    "scope": ["single_chapter"],
                },
                "role_selection": "static",
                "role_bindings": [
                    {
                        "node_id": "state_projection",
                        "role": "Scribe",
                        "profile": "state_projector",
                        "depends_on": [],
                    }
                ],
                "source_fact_bindings": {},
                "artifact_contracts": [
                    {
                        "artifact_type": "state_delta",
                        "producer_node": "state_projection",
                        "candidate_only": True,
                        "required_markers": [
                            "source_artifacts",
                            "progress_cursor",
                        ],
                    }
                ],
                "result_artifact_type": "state_delta",
                "promotion_gates": ["projection_verified"],
                "promotion_gate_bindings": {
                    "projection_verified": {
                        "work_item_id": "state_projection",
                        "evidence_kind": "deterministic",
                        "subject_artifact_types": ["state_delta"],
                    }
                },
            },
        }
    )
    atomic_write_yaml(catalog_path, catalog)
    runtime = TaskRuntime(tmp_path, project="DeterministicRunner")
    runtime.create_task(
        task_id="task-deterministic",
        title="Deterministic projection",
        user_goal="Run the deterministic profile without a CLI agent.",
        protocol_ref="test.deterministic.v1",
        input_profile={
            "kind": "prose_build",
            "scope": "single_chapter",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
        },
        idempotency_key="create-deterministic",
    )

    result = ProductionProtocolRunner(
        tmp_path, project="DeterministicRunner"
    ).execute_node(
        "task-deterministic",
        work_item_id="state_projection",
        messages=[{"role": "user", "content": "Project state."}],
        source_paths=[],
        external_context_request={"purpose": "not-used"},
        idempotency_key="execute-deterministic",
    )

    assert result["status"] == "waiting_review"
    attempt = result["projection"]["attempts"]["attempt-state_projection-001"]
    assert attempt["status"] == "succeeded"
    assert attempt["output_validation"]["status"] == "pass"
    assert attempt["execution_contract"]["executor_type"] == "deterministic_tool"
    assert any(
        artifact["artifact_id"] == "state_delta"
        for artifact in result["projection"]["artifacts"].values()
    )


def test_protocol_artifact_rejection_is_recorded_in_authoritative_ledger(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    catalog_path = config / "production_packs.yml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["packs"].append(
        {
            "pack_id": "validation_fixture",
            "protocol": {
                "ref": "test.validation.v1",
                "required_facts": [
                    "kind",
                    "scope",
                    "target_count",
                    "canon_impact",
                    "risk_flags",
                ],
                "role_selection": "static",
                "role_bindings": [
                    {
                        "node_id": "producer",
                        "role": "Reviewer",
                        "profile": "source_story_locker",
                        "depends_on": [],
                    }
                ],
                "source_fact_bindings": {},
                "artifact_contracts": [
                    {
                        "artifact_type": "validated_output",
                        "producer_node": "producer",
                        "candidate_only": True,
                        "required_markers": ["REQUIRED_MARKER"],
                    }
                ],
                "result_artifact_type": "validated_output",
                "promotion_gates": ["validated"],
                "promotion_gate_bindings": {
                    "validated": {
                        "work_item_id": "producer",
                        "evidence_kind": "automated",
                        "subject_artifact_types": ["validated_output"],
                    }
                },
            },
        }
    )
    atomic_write_yaml(catalog_path, catalog)
    runtime = TaskRuntime(tmp_path, project="ValidationLedger")
    runtime.create_task(
        task_id="task-validation-ledger",
        title="Reject invalid artifact",
        user_goal="Record output validation in the event ledger.",
        protocol_ref="test.validation.v1",
        input_profile={
            "kind": "code_build",
            "scope": "large",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
        },
        idempotency_key="create-validation-ledger",
    )

    class FixtureExecutor:
        def execute(self, **kwargs):
            projection, output = _succeed_deterministically(
                runtime,
                task_id=kwargs["task_id"],
                node_id=kwargs["work_item_id"],
                role=kwargs["role"],
                attempt_id=kwargs["attempt_id"],
                source_paths=kwargs["source_paths"],
            )
            return {"projection": projection, "output_path": str(output)}

    result = ProductionProtocolRunner(
        tmp_path,
        project="ValidationLedger",
        role_executor_factory=lambda _root, _project: FixtureExecutor(),
    ).execute_node(
        "task-validation-ledger",
        work_item_id="producer",
        messages=[{"role": "user", "content": "Produce."}],
        source_paths=[],
        external_context_request={"purpose": "fixture"},
        idempotency_key="execute-validation-ledger",
    )

    assert result["status"] == "artifact_rejected"
    attempt = result["projection"]["attempts"]["attempt-producer-001"]
    assert attempt["status"] == "succeeded"
    assert attempt["output_validation"]["status"] == "fail"
    assert attempt["output_validation"]["issues"] == [
        "artifact_required_marker_missing:validated_output:REQUIRED_MARKER"
    ]
    rebuilt = TaskRuntime(tmp_path, project="ValidationLedger").load_task(
        "task-validation-ledger"
    )
    assert rebuilt["attempts"]["attempt-producer-001"]["output_validation"] == (
        attempt["output_validation"]
    )
    manual_source = (
        tmp_path
        / "projects"
        / "ValidationLedger"
        / "runtime"
        / "tasks"
        / "task-validation-ledger"
        / "artifacts"
        / "manual.md"
    )
    manual_source.parent.mkdir(parents=True, exist_ok=True)
    manual_source.write_text("REQUIRED_MARKER\n", encoding="utf-8")
    with pytest.raises(InvalidTransition, match="passed output validation"):
        runtime.record_artifact_version(
            "task-validation-ledger",
            artifact_id="validated_output",
            version_id="validated-output-manual-v1",
            attempt_id="attempt-producer-001",
            path=manual_source,
            media_type="text/markdown",
            idempotency_key="manual-bypass",
        )
