from __future__ import annotations

from pathlib import Path
import hashlib
import shutil

import pytest
import yaml

from agent_runtime.artifact_digest import artifact_sha256
from agent_runtime.narrative.blueprint_lifecycle import (
    publish_blueprint_change,
    seal_project_blueprint,
    validate_project_blueprint,
)
from agent_runtime.narrative.task_packet import (
    append_narrative_instruction,
    compile_narrative_task_packet,
)
from agent_runtime.project_agents import (
    AgentContractViolation,
    AgentLifecycle,
    ProjectAgentFactory,
    ProjectAgentRegistry,
)
from agent_runtime.project_truth import (
    ChangeSet,
    ProjectTruthStore,
    ResourceChange,
)
from agent_runtime.task_runtime_v2 import TaskRuntime
from task_runtime_v2_support import execute_role_with_output


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _generic_project(root: Path, *, project: str = "Novel") -> Path:
    _write_yaml(
        root / "config" / "knowledge_system.yml",
        {"indexing": {"project_allowlist": [project]}},
    )
    project_root = root / "projects" / project
    for relative, text in (
        ("production/bible/world.md", "one world\n"),
        ("production/outlines/volume.md", "one outline\n"),
        ("production/manuscript/chapter_001.md", "one chapter\n"),
    ):
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _write_yaml(
        project_root / "production" / "agent_team.yml",
        {
            "schema_version": "project-agent-team/v1",
            "project": project,
            "status": "current",
            "agents": {
                "world_architect": {"role": "World Architect"},
                "writer": {"role": "Writer"},
                "verifier": {"role": "Verifier"},
            },
        },
    )
    _write_yaml(
        project_root / "production" / "narrative_modification_contract.yml",
        {
            "schema_version": "narrative-modification-contract/v1",
            "project": project,
            "status": "current",
            "prompt_injection": {
                "append_only_task_events": True,
                "overwrite_old_prompt_forbidden": True,
                "required_fields": [
                    "requested_delta",
                    "target_scope",
                    "preserve_invariants",
                    "allowed_retcons",
                    "acceptance_rules",
                    "idempotency_key",
                ],
            },
        },
    )
    _write_yaml(
        project_root / "project_brain" / "project_fact_snapshot.yml",
        {
            "schema_version": 1,
            "project": project,
            "status": {"lifecycle": "active"},
            "facts": {},
        },
    )
    _write_yaml(
        project_root / "project_brain" / "knowledge_index_snapshot.yml",
        {
            "schema_version": 1,
            "status": "sealed",
            "namespace": f"project.{project}",
            "index_snapshot": "idx_fixture",
            "indexed_paths": [],
            "indexed_source_hashes": {},
        },
    )
    authority = {
        "schema_version": "narrative-blueprint-authority/v1",
        "project": project,
        "status": "registered_pending_generic_validation",
        "authority_kind": "project_specific",
        "source_artifacts": {
            "project_bible": {
                "artifact_id": "project_bible",
                "version": "v1",
                "path": "production/bible/",
                "sha256": artifact_sha256(project_root / "production" / "bible"),
            },
            "outline_set": {
                "artifact_id": "outline_set",
                "version": "v1",
                "path": "production/outlines/",
                "sha256": artifact_sha256(project_root / "production" / "outlines"),
            },
            "manuscript_series": {
                "artifact_id": "manuscript_series",
                "version": "v1",
                "path": "production/manuscript/",
                "sha256": artifact_sha256(project_root / "production" / "manuscript"),
            },
        },
        "story_contract": {
            "target_total_chapters": 100,
            "accepted_chapters": 1,
            "next_production_chapter": 2,
        },
        "authority_rules": {
            "direct_production_edit_forbidden": True,
            "one_current_version_per_artifact_id": True,
            "archive_and_runtime_are_not_current_truth": True,
            "rag_is_derived_not_authoritative": True,
        },
        "production_gate": {
            "runtime_standard": "task-runtime-v2",
            "generic_blueprint_cli_profile_status": "pending_implementation",
        },
    }
    authority_path = project_root / "production" / "blueprint_authority.yml"
    _write_yaml(authority_path, authority)
    artifacts = [
        {
            "artifact_id": item["artifact_id"],
            "status": "current",
            "current_version": item["version"],
            "production_path": item["path"],
            "production_sha256": item["sha256"],
            "source_task": "normalization",
            "source_run_artifact": item["path"],
            "evidence_only": False,
        }
        for item in authority["source_artifacts"].values()
    ]
    artifacts.append(
        {
            "artifact_id": "narrative_blueprint_authority",
            "status": "current",
            "current_version": "blueprint-v1",
            "production_path": "production/blueprint_authority.yml",
            "production_sha256": artifact_sha256(authority_path),
            "source_task": "normalization",
            "source_run_artifact": "production/blueprint_authority.yml",
            "evidence_only": False,
        }
    )
    for artifact_id, relative in (
        ("project_agent_team", "production/agent_team.yml"),
        (
            "narrative_modification_contract",
            "production/narrative_modification_contract.yml",
        ),
        ("project_fact_snapshot", "project_brain/project_fact_snapshot.yml"),
    ):
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "status": "current",
                "current_version": "v1",
                "production_path": relative,
                "production_sha256": artifact_sha256(project_root / relative),
                "source_task": "normalization",
                "source_run_artifact": relative,
                "evidence_only": False,
            }
        )
    _write_yaml(
        project_root / "project_artifact_index.yml",
        {
            "version": 2,
            "project": project,
            "source_of_truth": "production",
            "artifacts": artifacts,
            "current": {
                item["artifact_id"]: item["production_path"] for item in artifacts
            },
        },
    )
    return project_root


def test_validate_project_specific_blueprint_through_generic_interface(
    tmp_path: Path,
) -> None:
    _generic_project(tmp_path)

    result = validate_project_blueprint(tmp_path, project="Novel")

    assert result["status"] == "pass"
    assert result["profile"] == "project_specific"
    assert result["sealed"] is False
    assert result["issues"] == []


def test_seal_project_blueprint_registers_one_hash_bound_current_authority(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)

    sealed = seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )

    assert sealed["status"] == "sealed"
    assert sealed["project"] == "Novel"
    assert sealed["idempotent_replay"] is False
    validation = validate_project_blueprint(tmp_path, project="Novel")
    assert validation["status"] == "pass"
    assert validation["sealed"] is True
    authority = yaml.safe_load(
        (project_root / "production" / "blueprint_authority.yml").read_text(
            encoding="utf-8"
        )
    )
    assert authority["status"] == "validated_sealed"
    assert (
        authority["production_gate"]["generic_blueprint_cli_profile_status"]
        == "implemented"
    )
    index = yaml.safe_load(
        (project_root / "project_artifact_index.yml").read_text(encoding="utf-8")
    )
    current = [
        item
        for item in index["artifacts"]
        if item["artifact_id"] == "narrative_blueprint_authority"
        and item["status"] == "current"
    ]
    assert len(current) == 1
    assert current[0]["production_sha256"] == artifact_sha256(
        project_root / "production" / "blueprint_authority.yml"
    )
    assert current[0]["source_run_artifact"] == (
        "production/blueprint_authority.yml"
    )
    assert current[0]["provenance_kind"] == "bootstrap_in_place_validation"
    assert index["current"]["narrative_blueprint_authority"] == (
        "production/blueprint_authority.yml"
    )
    receipt = project_root / "project_brain" / "blueprint_validation_receipt.yml"
    assert receipt.is_file()

    replay = seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    assert replay["idempotent_replay"] is True


def test_seal_registers_valid_but_previously_unbound_fact_snapshot(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    index_path = project_root / "project_artifact_index.yml"
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    index["artifacts"] = [
        item
        for item in index["artifacts"]
        if item["artifact_id"] != "project_fact_snapshot"
    ]
    index["current"].pop("project_fact_snapshot")
    _write_yaml(index_path, index)
    assert validate_project_blueprint(tmp_path, project="Novel")["status"] == "blocked"

    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )

    assert validate_project_blueprint(tmp_path, project="Novel")["status"] == "pass"
    sealed_index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    assert sealed_index["current"]["project_fact_snapshot"] == (
        "project_brain/project_fact_snapshot.yml"
    )


def _blueprint_change(
    root: Path,
    project_root: Path,
    *,
    task_id: str = "task-change-world",
    record_evidence: bool = True,
    change_kind: str = "blueprint_change",
) -> tuple[Path, Path]:
    knowledge_snapshot_path = (
        project_root / "project_brain" / "knowledge_index_snapshot.yml"
    )
    knowledge_snapshot = yaml.safe_load(
        knowledge_snapshot_path.read_text(encoding="utf-8")
    )
    knowledge_snapshot["indexed_source_hashes"] = {
        "projects/Novel/production/blueprint_authority.yml": artifact_sha256(
            project_root / "production" / "blueprint_authority.yml"
        ),
        (
            "projects/Novel/production/narrative_modification_contract.yml"
        ): artifact_sha256(
            project_root / "production" / "narrative_modification_contract.yml"
        ),
        (
            "projects/Novel/project_brain/project_fact_snapshot.yml"
        ): artifact_sha256(
            project_root / "project_brain" / "project_fact_snapshot.yml"
        ),
    }
    _write_yaml(knowledge_snapshot_path, knowledge_snapshot)
    compile_narrative_task_packet(
        root,
        project="Novel",
        task_id=task_id,
        request={
            "change_kind": change_kind,
            "requested_delta": "Change one world rule.",
            "target_scope": {"artifacts": ["production/bible"]},
            "preserve_invariants": ["The accepted manuscript remains unchanged."],
            "allowed_retcons": [],
            "acceptance_rules": ["All expert and verifier checks pass."],
            "idempotency_key": "change-world-v2",
        },
    )
    task_root = project_root / "runtime" / "tasks" / task_id
    candidate_bible = task_root / "artifacts" / "bible"
    candidate_bible.mkdir(parents=True)
    (candidate_bible / "world.md").write_text("changed world\n", encoding="utf-8")
    authority = yaml.safe_load(
        (project_root / "production" / "blueprint_authority.yml").read_text(
            encoding="utf-8"
        )
    )
    authority["status"] = "registered_pending_generic_validation"
    authority.pop("sealed_from_sha256", None)
    authority.pop("sealed_by_task", None)
    authority["production_gate"][
        "generic_blueprint_cli_profile_status"
    ] = "pending_implementation"
    authority["source_artifacts"]["project_bible"]["version"] = "v2"
    authority["source_artifacts"]["project_bible"]["sha256"] = artifact_sha256(
        candidate_bible
    )
    candidate_authority = task_root / "artifacts" / "blueprint_authority.yml"
    _write_yaml(candidate_authority, authority)
    manifest = task_root / "artifacts" / "blueprint_change_set.yml"
    current_authority = project_root / "production" / "blueprint_authority.yml"
    current_index = project_root / "project_artifact_index.yml"
    _write_yaml(
        manifest,
        {
            "schema_version": "narrative-blueprint-change-set/v1",
            "project": "Novel",
            "task_id": task_id,
            "idempotency_key": "change-world-v2",
            "reason": "Change one world rule.",
            "expected_current": {
                "authority_sha256": artifact_sha256(current_authority),
                "artifact_index_sha256": artifact_sha256(current_index),
            },
            "required_reviews": [
                "world-architect",
                "character-keeper",
                "timeline-keeper",
                "plot-mystery-keeper",
                "reviewer",
                "verifier",
            ],
            "changes": [
                {
                    "artifact_id": "project_bible",
                    "source_path": "artifacts/bible",
                    "production_path": "production/bible",
                    "sha256": artifact_sha256(candidate_bible),
                },
                {
                    "artifact_id": "narrative_blueprint_authority",
                    "source_path": "artifacts/blueprint_authority.yml",
                    "production_path": "production/blueprint_authority.yml",
                    "sha256": artifact_sha256(candidate_authority),
                },
            ],
        },
    )
    approval = task_root / "artifacts" / "blueprint_acceptance_receipt.yml"
    _write_yaml(
        approval,
        {
            "schema_version": "narrative-blueprint-acceptance/v1",
            "status": "accepted",
            "project": "Novel",
            "task_id": task_id,
            "change_set_sha256": artifact_sha256(manifest),
            "accepted_by": "user",
            "reviews": [
                {
                    "role": "World Architect",
                    "work_item_id": "world-architect",
                    "attempt_id": "attempt-world-architect",
                    "status": "pass",
                },
                {
                    "role": "Character Keeper",
                    "work_item_id": "character-keeper",
                    "attempt_id": "attempt-character-keeper",
                    "status": "pass",
                },
                {
                    "role": "Timeline Keeper",
                    "work_item_id": "timeline-keeper",
                    "attempt_id": "attempt-timeline-keeper",
                    "status": "pass",
                },
                {
                    "role": "Plot and Mystery Keeper",
                    "work_item_id": "plot-mystery-keeper",
                    "attempt_id": "attempt-plot-mystery-keeper",
                    "status": "pass",
                },
                {
                    "role": "Reviewer",
                    "work_item_id": "reviewer",
                    "attempt_id": "attempt-reviewer",
                    "status": "pass",
                },
                {
                    "role": "Verifier",
                    "work_item_id": "verifier",
                    "attempt_id": "attempt-verifier",
                    "status": "pass",
                },
            ],
        },
    )
    if record_evidence:
        _record_blueprint_runtime_evidence(
            root,
            project_root,
            task_id=task_id,
            manifest=manifest,
            approval=approval,
        )
    return manifest, approval


def _record_blueprint_runtime_evidence(
    root: Path,
    project_root: Path,
    *,
    task_id: str,
    manifest: Path,
    approval: Path,
) -> None:
    runtime = TaskRuntime(root, project="Novel")
    task_root = project_root / "runtime" / "tasks" / task_id
    scope = {
        "schema_version": "brain-scope-decision/v1",
        "approved": True,
        "chapter_start": 1,
        "chapter_end": 1,
        "target_cjk_chars": 1000,
        "quality_thresholds": {"all_reviews_pass": True},
    }
    plan = {
        "schema_version": "task-execution-plan/v1",
        "status": "approved",
        "route": "governed_pipeline",
        "work_items": [
            "world-architect",
            "character-keeper",
            "timeline-keeper",
            "plot-mystery-keeper",
            "artifact-producer",
            "reviewer",
            "verifier",
        ],
    }
    runtime.transition_work_item(
        task_id,
        work_item_id="brain-plan",
        status="running",
        idempotency_key="start-brain-plan",
    )
    brain_outcome = execute_role_with_output(
        runtime,
        root,
        task_id=task_id,
        work_item_id="brain-plan",
        attempt_id="attempt-brain-plan",
        role="Supervisor",
        output={"brain_scope_decision": scope, "execution_plan": plan},
        project="Novel",
    )
    staging = task_root / "records" / "staging"
    for record_type, value in (
        ("brain_scope_decision", scope),
        ("execution_plan", plan),
    ):
        payload = dict(value)
        payload["producer_attempt_id"] = "attempt-brain-plan"
        payload["source_output_sha256"] = brain_outcome["output_sha256"]
        path = staging / f"{record_type}.yml"
        _write_yaml(path, payload)
        runtime.record_trace(
            task_id,
            record_id=f"record-{record_type}",
            record_type=record_type,
            producer="codex",
            producer_role="Supervisor",
            path=path,
            idempotency_key=f"record-{record_type}",
        )
    runtime.transition_work_item(
        task_id,
        work_item_id="brain-plan",
        status="accepted",
        idempotency_key="accept-brain-plan",
    )

    for work_item_id in (
        "world-architect",
        "character-keeper",
        "timeline-keeper",
        "plot-mystery-keeper",
    ):
        runtime.transition_work_item(
            task_id,
            work_item_id=work_item_id,
            status="running",
            idempotency_key=f"start-{work_item_id}",
        )
        execute_role_with_output(
            runtime,
            root,
            task_id=task_id,
            work_item_id=work_item_id,
            attempt_id=f"attempt-{work_item_id}",
            role="Writer",
            output={"status": "pass", "work_item_id": work_item_id},
            project="Novel",
        )
        runtime.transition_work_item(
            task_id,
            work_item_id=work_item_id,
            status="accepted",
            idempotency_key=f"accept-{work_item_id}",
        )

    runtime.transition_work_item(
        task_id,
        work_item_id="artifact-producer",
        status="running",
        idempotency_key="start-artifact-producer",
    )
    execute_role_with_output(
        runtime,
        root,
        task_id=task_id,
        work_item_id="artifact-producer",
        attempt_id="attempt-artifact-producer",
        role="Writer",
        output=yaml.safe_load(manifest.read_text(encoding="utf-8")),
        project="Novel",
    )
    manifest_projection = runtime.record_artifact_version(
        task_id,
        artifact_id="blueprint_change_set",
        version_id="blueprint-change-set-v1",
        attempt_id="attempt-artifact-producer",
        path=manifest,
        media_type="application/yaml",
        idempotency_key="record-blueprint-change-set",
    )
    runtime.bind_evidence(
        task_id,
        binding_id="evidence-blueprint-change-set",
        version_id="blueprint-change-set-v1",
        input_manifest_hash=artifact_sha256(
            project_root / "project_artifact_index.yml"
        ),
        index_snapshot_id="idx_fixture",
        source_hashes={
            "blueprint-authority": artifact_sha256(
                project_root / "production" / "blueprint_authority.yml"
            )
        },
        audit={"verdict": "pass"},
        idempotency_key="bind-blueprint-change-set",
    )
    assert manifest_projection["artifacts"]["blueprint-change-set-v1"]["sha256"]
    runtime.transition_work_item(
        task_id,
        work_item_id="artifact-producer",
        status="accepted",
        idempotency_key="accept-artifact-producer",
    )

    runtime.transition_work_item(
        task_id,
        work_item_id="reviewer",
        status="running",
        idempotency_key="start-reviewer",
    )
    execute_role_with_output(
        runtime,
        root,
        task_id=task_id,
        work_item_id="reviewer",
        attempt_id="attempt-reviewer",
        role="Reviewer",
        output={"status": "pass", "blocking_findings": []},
        project="Novel",
    )
    runtime.transition_work_item(
        task_id,
        work_item_id="reviewer",
        status="accepted",
        idempotency_key="accept-reviewer",
    )

    runtime.transition_work_item(
        task_id,
        work_item_id="verifier",
        status="running",
        idempotency_key="start-verifier",
    )
    execute_role_with_output(
        runtime,
        root,
        task_id=task_id,
        work_item_id="verifier",
        attempt_id="attempt-verifier",
        role="Verifier",
        output=yaml.safe_load(approval.read_text(encoding="utf-8")),
        project="Novel",
    )
    runtime.record_artifact_version(
        task_id,
        artifact_id="blueprint_acceptance_receipt",
        version_id="blueprint-acceptance-v1",
        attempt_id="attempt-verifier",
        path=approval,
        media_type="application/yaml",
        idempotency_key="record-blueprint-acceptance",
    )
    runtime.bind_evidence(
        task_id,
        binding_id="evidence-blueprint-acceptance",
        version_id="blueprint-acceptance-v1",
        input_manifest_hash=artifact_sha256(manifest),
        index_snapshot_id="idx_fixture",
        source_hashes={"blueprint-change-set": artifact_sha256(manifest)},
        audit={"verdict": "pass"},
        idempotency_key="bind-blueprint-acceptance",
    )
    runtime.transition_work_item(
        task_id,
        work_item_id="verifier",
        status="accepted",
        idempotency_key="accept-verifier",
    )


def test_publish_blueprint_change_archives_previous_and_switches_one_current(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)

    published = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )

    assert published["status"] == "published"
    assert published["idempotent_replay"] is False
    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_text(encoding="utf-8") == "changed world\n"
    archive_bible = (
        project_root
        / published["archive_root"]
        / "production"
        / "bible"
        / "world.md"
    )
    assert archive_bible.read_text(encoding="utf-8") == "one world\n"
    assert validate_project_blueprint(tmp_path, project="Novel")["status"] == "pass"
    index = yaml.safe_load(
        (project_root / "project_artifact_index.yml").read_text(encoding="utf-8")
    )
    current_ids = [
        item["artifact_id"]
        for item in index["artifacts"]
        if item.get("status") == "current"
    ]
    assert len(current_ids) == len(set(current_ids))
    assert index["current"]["project_bible"] == "production/bible/"
    receipt_path = tmp_path / published["publication_receipt"]
    receipt_before_replay = receipt_path.read_bytes()

    replay = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )
    assert replay["idempotent_replay"] is True
    assert receipt_path.read_bytes() == receipt_before_replay


def test_publish_blueprint_change_rejects_unexecuted_review_claims(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(
        tmp_path,
        project_root,
        record_evidence=False,
    )

    with pytest.raises(
        ValueError,
        match="work item lacks accepted execution evidence",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_text(encoding="utf-8") == "one world\n"


def test_publish_blueprint_change_refuses_legacy_receipt_replay_without_runtime_evidence(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    published = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )
    receipt_path = tmp_path / published["publication_receipt"]
    receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("runtime_evidence")
    _write_yaml(receipt_path, receipt)

    with pytest.raises(
        ValueError,
        match="predates Runtime v2 evidence enforcement",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )


def test_publish_blueprint_change_ignores_mutable_staging_packet_tampering(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    packet_path = (
        project_root
        / "runtime"
        / "tasks"
        / "task-change-world"
        / "records"
        / "staging"
        / "narrative_task_packet.yml"
    )
    packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
    packet["required_roles"].remove("world-architect")
    _write_yaml(packet_path, packet)

    published = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )

    assert published["status"] == "published"
    assert published["runtime_evidence"]["packet_sha256"] != artifact_sha256(
        packet_path
    )


def test_publish_blueprint_change_rejects_missing_immutable_brain_trace(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    runtime = TaskRuntime(tmp_path, project="Novel")
    projection = runtime.load_task("task-change-world")
    execution_plan = next(
        record
        for record in projection["trace_records"].values()
        if record["record_type"] == "execution_plan"
    )
    (
        project_root
        / "runtime"
        / "tasks"
        / "task-change-world"
        / execution_plan["path"]
    ).unlink()

    with pytest.raises(
        ValueError,
        match="trace bytes are stale or predate the latest instruction: execution_plan",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )


def test_append_rejects_task_after_governed_execution_has_started(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    _blueprint_change(tmp_path, project_root)

    with pytest.raises(
        ValueError,
        match="execution already started",
    ):
        append_narrative_instruction(
            tmp_path,
            project="Novel",
            task_id="task-change-world",
            instruction_id="instruction-too-late",
            request={
                "change_kind": "blueprint_change",
                "requested_delta": "Do not modify world.md.",
                "target_scope": {"artifacts": ["production/bible"]},
                "preserve_invariants": ["Keep world.md unchanged."],
                "allowed_retcons": [],
                "acceptance_rules": ["World remains byte-identical."],
                "idempotency_key": "too-late-v1",
            },
        )


def test_publisher_rejects_direct_instruction_appended_after_evidence(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    TaskRuntime(tmp_path, project="Novel").append_instruction(
        "task-change-world",
        instruction_id="instruction-direct-too-late",
        requested_delta="Do not modify world.md.",
        target_scope={"artifacts": ["production/bible"]},
        preserve_invariants=["Keep world.md unchanged."],
        allowed_retcons=[],
        acceptance_rules=["World remains byte-identical."],
        idempotency_key="direct-too-late-v1",
    )

    with pytest.raises(
        ValueError,
        match="lacks accepted execution evidence",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_text(encoding="utf-8") == "one world\n"


def test_publish_global_character_change_uses_same_atomic_authority_gate(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(
        tmp_path,
        project_root,
        change_kind="global_character_change",
    )

    published = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )

    assert published["status"] == "published"


def test_publish_blueprint_change_rejects_stale_current_hashes(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    index_path = project_root / "project_artifact_index.yml"
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    index["updated_at"] = "concurrent-change"
    _write_yaml(index_path, index)
    receipt_path = project_root / "project_brain" / "blueprint_validation_receipt.yml"
    receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    receipt["artifact_index_sha256"] = artifact_sha256(index_path)
    _write_yaml(receipt_path, receipt)

    with pytest.raises(ValueError, match="stale blueprint change set"):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_text(encoding="utf-8") == "one world\n"


def test_publish_blueprint_change_rolls_back_when_index_switch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_runtime.narrative.blueprint_lifecycle as lifecycle

    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    index_path = project_root / "project_artifact_index.yml"
    before_index = index_path.read_bytes()
    before_authority = (
        project_root / "production" / "blueprint_authority.yml"
    ).read_bytes()
    real_write = lifecycle.atomic_write_text
    failed = False

    def fail_one_index_switch(path, content, *args, **kwargs):
        nonlocal failed
        if Path(path) == index_path and not failed:
            failed = True
            raise OSError("simulated index switch interruption")
        return real_write(path, content, *args, **kwargs)

    monkeypatch.setattr(lifecycle, "atomic_write_text", fail_one_index_switch)

    with pytest.raises(OSError, match="simulated index switch interruption"):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert index_path.read_bytes() == before_index
    assert (
        project_root / "production" / "blueprint_authority.yml"
    ).read_bytes() == before_authority
    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_text(encoding="utf-8") == "one world\n"
    assert not (
        project_root / ".agentlab" / "narrative_transactions"
    ).exists() or not any(
        (
            project_root / ".agentlab" / "narrative_transactions"
        ).iterdir()
    )


def test_publish_blueprint_change_restores_target_when_staged_install_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_runtime.narrative.blueprint_lifecycle as lifecycle

    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    real_replace = lifecycle.os.replace

    def fail_staged_bible_install(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            "/stage/projects/Novel/production/bible" in source_path.as_posix()
            and destination_path == project_root / "production" / "bible"
        ):
            raise OSError("simulated staged artifact install failure")
        return real_replace(source, destination)

    monkeypatch.setattr(lifecycle.os, "replace", fail_staged_bible_install)

    with pytest.raises(OSError, match="simulated staged artifact install failure"):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_text(encoding="utf-8") == "one world\n"
    assert not any(
        (
            project_root / ".agentlab" / "narrative_transactions"
        ).iterdir()
    )


def test_publish_cleans_initial_transaction_when_prepared_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_runtime.narrative.blueprint_lifecycle as lifecycle

    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    real_write = lifecycle.atomic_write_yaml
    failed = False

    def fail_initial_prepared_write(path, value, *args, **kwargs):
        nonlocal failed
        if Path(path).name == "prepared.yml" and not failed:
            failed = True
            raise OSError("simulated initial prepared write failure")
        return real_write(path, value, *args, **kwargs)

    monkeypatch.setattr(
        lifecycle,
        "atomic_write_yaml",
        fail_initial_prepared_write,
    )

    with pytest.raises(OSError, match="simulated initial prepared write failure"):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    transactions_root = (
        project_root / ".agentlab" / "narrative_transactions"
    )
    assert not transactions_root.exists() or not any(transactions_root.iterdir())
    published = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )
    assert published["status"] == "published"


def test_publish_rolls_back_when_post_commit_knowledge_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_runtime.knowledge_system as knowledge_system

    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    before_index = (
        project_root / "project_artifact_index.yml"
    ).read_bytes()
    before_bible = (
        project_root / "production" / "bible" / "world.md"
    ).read_bytes()
    archive_root = project_root / "archive" / "narrative_blueprints"
    before_archives = (
        {item.name for item in archive_root.iterdir()}
        if archive_root.is_dir()
        else set()
    )

    def fail_sync(_event):
        raise OSError("simulated knowledge sync failure")

    monkeypatch.setattr(knowledge_system, "sync_committed", fail_sync)

    with pytest.raises(OSError, match="simulated knowledge sync failure"):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert (
        project_root / "project_artifact_index.yml"
    ).read_bytes() == before_index
    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_bytes() == before_bible
    transactions_root = (
        project_root / ".agentlab" / "narrative_transactions"
    )
    assert not transactions_root.exists() or not any(transactions_root.iterdir())
    assert (
        {item.name for item in archive_root.iterdir()}
        if archive_root.is_dir()
        else set()
    ) == before_archives


def test_publish_rolls_back_when_knowledge_sync_is_not_synced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_runtime.knowledge_system as knowledge_system

    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    before_index = (
        project_root / "project_artifact_index.yml"
    ).read_bytes()
    before_bible = (
        project_root / "production" / "bible" / "world.md"
    ).read_bytes()

    class StaleSyncReceipt:
        def as_dict(self) -> dict[str, str]:
            return {
                "status": "INDEX_STALE",
                "receipt_id": "stale-fixture",
            }

    monkeypatch.setattr(
        knowledge_system,
        "sync_committed",
        lambda _event: StaleSyncReceipt(),
    )

    with pytest.raises(
        ValueError,
        match="project knowledge sync did not commit: INDEX_STALE",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert (
        project_root / "project_artifact_index.yml"
    ).read_bytes() == before_index
    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_bytes() == before_bible
    assert not (
        project_root
        / "project_brain"
        / "blueprint_change_receipts"
    ).exists()


def test_publish_invalidates_knowledge_when_immutable_receipt_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_runtime.narrative.blueprint_lifecycle as lifecycle

    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    before_index = (
        project_root / "project_artifact_index.yml"
    ).read_bytes()
    before_authority_sha256 = artifact_sha256(
        project_root / "production" / "blueprint_authority.yml"
    )
    before_bible = (
        project_root / "production" / "bible" / "world.md"
    ).read_bytes()

    def fail_receipt_creation(_path, _value):
        raise OSError("simulated immutable receipt creation failure")

    monkeypatch.setattr(
        lifecycle,
        "_create_immutable_yaml",
        fail_receipt_creation,
    )

    with pytest.raises(
        OSError,
        match="simulated immutable receipt creation failure",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert (
        project_root / "project_artifact_index.yml"
    ).read_bytes() == before_index
    assert (
        project_root / "production" / "bible" / "world.md"
    ).read_bytes() == before_bible
    knowledge_snapshot = yaml.safe_load(
        (
            project_root
            / "project_brain"
            / "knowledge_index_snapshot.yml"
        ).read_text(encoding="utf-8")
    )
    assert knowledge_snapshot["indexed_source_hashes"][
        "projects/Novel/production/blueprint_authority.yml"
    ] == before_authority_sha256
    assert not (
        project_root
        / "project_brain"
        / "blueprint_change_receipts"
    ).exists()
    from agent_runtime.knowledge_system.operations import knowledge_status

    spaces = {
        item["namespace"]: item
        for item in knowledge_status(tmp_path)["spaces"]
    }
    assert spaces["project.Novel"]["status"] == "stale"
    assert spaces["domain.longform_narrative"]["status"] == "stale"


def test_publish_rejects_preexisting_archive_symlink_without_writing_outside(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    receipt_key = hashlib.sha256(b"Novel\0change-world-v2").hexdigest()
    archive_root = (
        project_root / "archive" / "narrative_blueprints" / receipt_key
    )
    archive_root.mkdir(parents=True)
    outside = tmp_path / "outside-archive"
    outside.mkdir()
    sentinel = outside / "sentinel.md"
    sentinel.write_text("outside remains\n", encoding="utf-8")
    (archive_root / "production").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(
        ValueError,
        match="archive path already exists",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )

    assert sentinel.read_text(encoding="utf-8") == "outside remains\n"
    assert not (outside / "bible" / "world.md").exists()


def test_idempotent_replay_rejects_tampered_publication_receipt(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    published = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )
    receipt_path = tmp_path / published["publication_receipt"]
    receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    receipt["runtime_evidence"]["verified_attempts"] = ["forged"]
    receipt["knowledge_sync"]["status"] = "INDEX_STALE"
    _write_yaml(receipt_path, receipt)

    with pytest.raises(
        ValueError,
        match="publication receipt failed tamper validation",
    ):
        publish_blueprint_change(
            tmp_path,
            project="Novel",
            manifest_path=manifest,
            acceptance_receipt_path=approval,
        )


def test_publish_recovers_interrupted_prior_transaction_before_cas(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    manifest, approval = _blueprint_change(tmp_path, project_root)
    receipt_key = hashlib.sha256(
        b"Novel\0change-world-v2"
    ).hexdigest()
    transaction = (
        project_root / ".agentlab" / "narrative_transactions" / receipt_key
    )
    backup = transaction / "backup"
    backup.mkdir(parents=True)
    shutil.copy2(
        project_root / "project_artifact_index.yml",
        backup / "project_artifact_index.yml",
    )
    old_bible = project_root / "production" / "bible"
    backup_bible = backup / "production" / "bible"
    backup_bible.parent.mkdir(parents=True)
    old_bible.replace(backup_bible)
    old_bible.mkdir()
    (old_bible / "world.md").write_text(
        "partial interrupted candidate\n",
        encoding="utf-8",
    )
    _write_yaml(
        transaction / "prepared.yml",
        {
            "schema_version": "narrative-blueprint-transaction/v1",
            "status": "prepared",
            "project": "Novel",
            "task_id": "task-change-world",
            "change_set_sha256": artifact_sha256(manifest),
            "receipt_path": (
                "project_brain/blueprint_change_receipts/"
                f"{receipt_key}.yml"
            ),
            "targets": [
                {
                    "target_path": "production/bible",
                    "existed": True,
                }
            ],
        },
    )

    published = publish_blueprint_change(
        tmp_path,
        project="Novel",
        manifest_path=manifest,
        acceptance_receipt_path=approval,
    )

    assert published["status"] == "published"
    archived = project_root / published["archive_root"] / "production" / "bible"
    assert (archived / "world.md").read_text(encoding="utf-8") == "one world\n"


def test_recovery_refuses_symlinked_production_target_without_touching_outside(
    tmp_path: Path,
) -> None:
    from agent_runtime.narrative.blueprint_lifecycle import (
        _recover_blueprint_transactions,
    )

    project_root = tmp_path / "projects" / "Novel"
    project_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside_bible = outside / "bible"
    outside_bible.mkdir(parents=True)
    sentinel = outside_bible / "sentinel.md"
    sentinel.write_text("outside remains\n", encoding="utf-8")
    (project_root / "production").symlink_to(
        outside,
        target_is_directory=True,
    )
    transaction = (
        project_root / ".agentlab" / "narrative_transactions" / "unsafe"
    )
    backup_bible = transaction / "backup" / "production" / "bible"
    backup_bible.mkdir(parents=True)
    (backup_bible / "world.md").write_text("backup\n", encoding="utf-8")
    _write_yaml(
        transaction / "prepared.yml",
        {
            "schema_version": "narrative-blueprint-transaction/v1",
            "status": "prepared",
            "project": "Novel",
            "task_id": "task-unsafe",
            "change_set_sha256": "0" * 64,
            "receipt_path": "project_brain/blueprint_change_receipts/unsafe.yml",
            "targets": [
                {
                    "target_path": "production/bible",
                    "existed": True,
                }
            ],
        },
    )

    with pytest.raises(
        ValueError,
        match="recovery target contains a symlink",
    ):
        _recover_blueprint_transactions(project_root)

    assert sentinel.read_text(encoding="utf-8") == "outside remains\n"
    assert not (outside_bible / "world.md").exists()


def test_compile_runtime_v2_narrative_packet_and_append_prompt_without_overwrite(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    _write_yaml(
        project_root / "project_brain" / "knowledge_index_snapshot.yml",
        {
            "schema_version": 1,
            "status": "sealed",
            "namespace": "project.Novel",
            "index_snapshot": "idx_fixture",
            "indexed_paths": [],
            "indexed_source_hashes": {
                "projects/Novel/production/blueprint_authority.yml": (
                    artifact_sha256(
                        project_root / "production" / "blueprint_authority.yml"
                    )
                ),
                "projects/Novel/production/narrative_modification_contract.yml": (
                    artifact_sha256(
                        project_root
                        / "production"
                        / "narrative_modification_contract.yml"
                    )
                ),
                "projects/Novel/project_brain/project_fact_snapshot.yml": (
                    artifact_sha256(
                        project_root
                        / "project_brain"
                        / "project_fact_snapshot.yml"
                    )
                ),
            },
        },
    )
    request = {
        "change_kind": "chapter_revision",
        "requested_delta": "Rewrite chapter 1 so the discovery remains ambiguous.",
        "target_scope": {"chapters": [1]},
        "preserve_invariants": ["The protagonist survives.", "No retroactive reveal."],
        "allowed_retcons": [],
        "acceptance_rules": ["Continuity passes.", "Verifier reports no drift."],
        "idempotency_key": "revise-chapter-1-v1",
    }

    compiled = compile_narrative_task_packet(
        tmp_path,
        project="Novel",
        task_id="task-revise-chapter-1",
        request=request,
    )

    assert compiled["status"] == "compiled"
    assert compiled["runtime_standard"] == "task-runtime-v2"
    packet_path = tmp_path / compiled["packet_path"]
    packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
    assert packet["truth_bindings"]["blueprint_authority_sha256"] == artifact_sha256(
        project_root / "production" / "blueprint_authority.yml"
    )
    assert packet["truth_bindings"]["knowledge_index_snapshot_id"] == "idx_fixture"
    assert packet["candidate_output"] == (
        "runtime/tasks/task-revise-chapter-1/artifacts/manuscript_candidate/"
    )
    runtime = TaskRuntime(tmp_path, project="Novel")
    projection = runtime.load_task("task-revise-chapter-1")
    assert projection["task"]["instructions"][0]["requested_delta"] == (
        request["requested_delta"]
    )
    assert "writer" in projection["work_items"]
    assert projection["work_items"]["world-architect"]["depends_on"] == [
        "brain-plan"
    ]
    assert projection["work_items"]["verifier"]["depends_on"] == ["reviewer"]

    updated = append_narrative_instruction(
        tmp_path,
        project="Novel",
        task_id="task-revise-chapter-1",
        instruction_id="instruction-002",
        request={
            **request,
            "requested_delta": "Also preserve the final line exactly.",
            "idempotency_key": "revise-chapter-1-v2",
        },
    )
    assert updated["instruction_count"] == 2
    projection = runtime.load_task("task-revise-chapter-1")
    assert [item["requested_delta"] for item in projection["task"]["instructions"]] == [
        request["requested_delta"],
        "Also preserve the final line exactly.",
    ]
    with pytest.raises(ValueError, match="must keep the Task change_kind"):
        append_narrative_instruction(
            tmp_path,
            project="Novel",
            task_id="task-revise-chapter-1",
            instruction_id="instruction-003",
            request={
                **request,
                "change_kind": "global_character_change",
                "idempotency_key": "wrong-kind-v1",
            },
        )


def test_compile_binds_enabled_project_agents_before_creating_task(
    tmp_path: Path,
) -> None:
    project_root = _generic_project(tmp_path)
    seal_project_blueprint(
        tmp_path,
        project="Novel",
        source_task="task-normalize",
    )
    _write_yaml(
        project_root / "project_brain" / "knowledge_index_snapshot.yml",
        {
            "schema_version": 1,
            "status": "sealed",
            "namespace": "project.Novel",
            "index_snapshot": "idx_fixture",
            "indexed_paths": [],
            "indexed_source_hashes": {
                "projects/Novel/production/blueprint_authority.yml": (
                    artifact_sha256(
                        project_root / "production" / "blueprint_authority.yml"
                    )
                ),
                "projects/Novel/production/narrative_modification_contract.yml": (
                    artifact_sha256(
                        project_root
                        / "production"
                        / "narrative_modification_contract.yml"
                    )
                ),
                "projects/Novel/project_brain/project_fact_snapshot.yml": (
                    artifact_sha256(
                        project_root
                        / "project_brain"
                        / "project_fact_snapshot.yml"
                    )
                ),
            },
        },
    )
    _write_yaml(
        project_root / "project.yml",
        {
            "project_id": "Novel",
            "features": {
                "project_truth_mode": "enforced",
                "enable_project_agents": True,
            },
            "workspace": {"isolation": "required"},
        },
    )
    truth = ProjectTruthStore(project_root)
    initial = truth.initialize("Novel")
    character_policy = {
        "schema_version": "character-content-policy/v1",
        "status": "active",
        "project": "Novel",
    }
    _write_yaml(
        project_root
        / "production"
        / "canonical"
        / "character_content_policy.yml",
        character_policy,
    )
    policy_commit = truth.commit(
        ChangeSet(
            project_id="Novel",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="character-policy-v1",
            resources=(
                ResourceChange(
                    key="governance.character_content_policy.current",
                    content=character_policy,
                ),
            ),
        )
    )
    registry = ProjectAgentRegistry(truth)
    created = ProjectAgentFactory().create_team(
        registry,
        (
            "Write a long fantasy novel with mystery, world, character, "
            "timeline, and style governance."
        ),
        expected_snapshot_id=policy_commit.snapshot_id,
        actor_id="user",
        approved=True,
    )
    current_truth_snapshot = (
        project_root
        / ".agentlab"
        / "truth"
        / "snapshots"
        / f"{created.snapshot_id}.yml"
    )
    _write_yaml(
        project_root / "project_brain" / "knowledge_index_snapshot.yml",
        {
            "schema_version": 1,
            "status": "sealed",
            "namespace": "project.Novel",
            "index_snapshot": "idx_fixture",
            "formal_fact_roots": ["canonical_truth"],
            "indexed_paths": [
                "projects/Novel/project_truth.yml",
                (
                    "projects/Novel/.agentlab/truth/snapshots/"
                    f"{created.snapshot_id}.yml"
                ),
            ],
            "indexed_source_hashes": {
                "projects/Novel/project_truth.yml": artifact_sha256(
                    project_root / "project_truth.yml"
                ),
                (
                    "projects/Novel/.agentlab/truth/snapshots/"
                    f"{created.snapshot_id}.yml"
                ): artifact_sha256(current_truth_snapshot),
            },
        },
    )
    request = {
        "change_kind": "blueprint_change",
        "requested_delta": "Change one world rule.",
        "target_scope": {"artifacts": ["production/bible"]},
        "preserve_invariants": ["Keep accepted chapters unchanged."],
        "allowed_retcons": [],
        "acceptance_rules": ["All governed reviews pass."],
        "idempotency_key": "bound-blueprint-v1",
    }

    compiled = compile_narrative_task_packet(
        tmp_path,
        project="Novel",
        task_id="task-bound-blueprint",
        request=request,
    )
    runtime = TaskRuntime(tmp_path, project="Novel")
    projection = runtime.load_task("task-bound-blueprint")

    assert compiled["status"] == "compiled"
    assert {
        item["canonical_snapshot_id"]
        for item in projection["work_items"].values()
    } == {created.snapshot_id}
    assert all(
        item["assigned_agent_id"]
        and item["agent_manifest_revision"] == 1
        and item["effective_contract_hash"]
        for item in projection["work_items"].values()
    )

    archived = AgentLifecycle(registry).archive(
        "blueprint_producer",
        expected_snapshot_id=created.snapshot_id,
        actor_id="user",
    )
    assert archived.snapshot_id != created.snapshot_id
    archived_truth_snapshot = (
        project_root
        / ".agentlab"
        / "truth"
        / "snapshots"
        / f"{archived.snapshot_id}.yml"
    )
    _write_yaml(
        project_root / "project_brain" / "knowledge_index_snapshot.yml",
        {
            "schema_version": 1,
            "status": "sealed",
            "namespace": "project.Novel",
            "index_snapshot": "idx_fixture_after_archive",
            "formal_fact_roots": ["canonical_truth"],
            "indexed_paths": [
                "projects/Novel/project_truth.yml",
                (
                    "projects/Novel/.agentlab/truth/snapshots/"
                    f"{archived.snapshot_id}.yml"
                ),
            ],
            "indexed_source_hashes": {
                "projects/Novel/project_truth.yml": artifact_sha256(
                    project_root / "project_truth.yml"
                ),
                (
                    "projects/Novel/.agentlab/truth/snapshots/"
                    f"{archived.snapshot_id}.yml"
                ): artifact_sha256(archived_truth_snapshot),
            },
        },
    )
    rejected_task_root = (
        project_root / "runtime" / "tasks" / "task-incomplete-agent-team"
    )
    with pytest.raises(AgentContractViolation, match="not active"):
        compile_narrative_task_packet(
            tmp_path,
            project="Novel",
            task_id="task-incomplete-agent-team",
            request={**request, "idempotency_key": "incomplete-team-v1"},
        )
    assert not rejected_task_root.exists()
