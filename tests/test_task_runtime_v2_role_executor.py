from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent_runtime.project_agents import (
    AgentManifest,
    ProjectAgentRegistry,
    effective_contract_hash,
)
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import InvalidTransition, RoleAttemptExecutor, TaskRuntime


def test_governed_source_manifest_binds_exact_task_local_files(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-manifest",
        title="Bind derived sources",
        user_goal="Admit only hash-bound Task-local derived context.",
        idempotency_key="create-manifest-task",
    )
    task_root = (
        tmp_path / "projects" / "Demo" / "runtime" / "tasks" / "task-manifest"
    )
    source_path = task_root / "inputs" / "derived-context.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("bounded context\n", encoding="utf-8")
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest_path = task_root / "inputs" / "governed-sources.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "task-runtime-governed-source-manifest/v1",
                "task_id": "task-manifest",
                "work_item_id": "writer",
                "sources": [
                    {
                        "path": "inputs/derived-context.md",
                        "sha256": source_digest,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    executor = RoleAttemptExecutor(tmp_path, project="Demo", cli_runner=lambda: None)

    admitted = executor._load_governed_source_manifest(
        manifest_path,
        task_id="task-manifest",
        work_item_id="writer",
    )

    assert admitted["sources"] == {source_path.resolve(): source_digest}
    assert admitted["sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    source_path.write_text("drifted context\n", encoding="utf-8")
    with pytest.raises(ValueError, match="failed hash admission"):
        executor._load_governed_source_manifest(
            manifest_path,
            task_id="task-manifest",
            work_item_id="writer",
        )

    nested_root = task_root / "inputs" / "nested"
    nested_root.mkdir()
    nested_source = nested_root / "context.md"
    nested_source.write_text("nested context\n", encoding="utf-8")
    alias = task_root / "inputs" / "alias"
    alias.symlink_to(nested_root, target_is_directory=True)
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "task-runtime-governed-source-manifest/v1",
                "task_id": "task-manifest",
                "work_item_id": "writer",
                "sources": [
                    {
                        "path": "inputs/alias/context.md",
                        "sha256": hashlib.sha256(
                            nested_source.read_bytes()
                        ).hexdigest(),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="may not bind symlinks"):
        executor._load_governed_source_manifest(
            manifest_path,
            task_id="task-manifest",
            work_item_id="writer",
        )


def test_role_executor_dispatches_recorded_route_and_pins_attempt_receipt(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "agent_role_bindings.yml").write_text(
        yaml.safe_dump(
            {
                "roles": {"Writer": {"allowed_workers": ["claude_code"]}},
                "workers": {
                    "claude_code": {
                        "worker_capable": True,
                        "worker_capabilities": ["role_worker"],
                        "allowed_roles": ["Writer"],
                        "forbidden_roles": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (config / "agent_model_profiles.yml").write_text(
        yaml.safe_dump(
            {
                "tier_policy": {
                    "default_tier": "performance",
                    "tiers": {
                        "performance": {
                            "budget_aliases": ["performance"],
                        }
                    },
                },
                "professional_role_profiles": {
                    "writer": {
                        "base_role_key": "writer",
                        "execution_tier": "performance",
                        "execution_kind": "cli_agent",
                        "capacity_route": "WriterStrict",
                    }
                },
                "modes": {
                    "full_cli": {
                        "tiers": {
                            "performance": {
                                "writer": {
                                    "executor_type": "cli_agent",
                                    "cli_agent": "claude_code",
                                    "invocation_contract": "claude_writer",
                                    "default": "writer-model",
                                }
                            }
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "model_capacity.yml").write_text(
        yaml.safe_dump(
            {
                "routes": {
                    "WriterStrict": {
                        "role": "writer",
                        "worker": "claude_code",
                        "invocation_contract": "claude_writer",
                        "model_key": "writer-model",
                        "pool": "fixture",
                        "approved_fallbacks": [],
                        "fallback_on": [],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "writer-model": {
                        "runtime_provider": "deepseek",
                        "model_id": "deepseek-v4-pro",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "worker_invocation_contracts.yml").write_text(
        yaml.safe_dump(
            {
                "contracts": {
                    "claude_writer": {
                        "worker_id": "claude_code",
                        "availability": "test_fixture_only",
                        "selectable": True,
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    project_root = tmp_path / "projects" / "Demo"
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Demo",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project_root)
    initial = truth.initialize("Demo")
    manifest = AgentManifest(
        id="writer",
        name="Writer",
        version="2.0.0",
        role="writer",
        description="Write governed candidates.",
        responsibilities=("Write governed candidates.",),
        runtime_role="Writer",
        read_scope=("production/**", "runs/**", "runtime/tasks/**"),
        write_scope=("runs/**",),
        approval_scope=(),
        knowledge_binding={"namespace": "agent.Demo.writer"},
        model_profile="writer",
        tool_permission=(),
        budget_profile="standard",
        status="active",
        acceptance_rules=("candidate_only",),
    )
    registered = ProjectAgentRegistry(truth).register(
        manifest,
        expected_snapshot_id=initial.current_snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )
    manifest = ProjectAgentRegistry(truth).get("writer")
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-role",
        title="One worker role",
        user_goal="Dispatch one governed local Writer.",
        input_profile={
            "kind": "creative_patch",
            "scope": "localized",
            "target_count": 1,
            "canon_impact": "candidate",
            "risk_flags": [],
        },
        idempotency_key="create-role",
    )
    runtime.create_work_item(
        "task-role",
        job_id="job-main",
        work_item_id="writer",
        kind="patch",
        title="Writer patch",
        assigned_agent_id=manifest.id,
        agent_manifest_revision=manifest.manifest_revision,
        canonical_snapshot_id=registered.snapshot_id,
        effective_contract_hash=effective_contract_hash(manifest),
        idempotency_key="work-writer",
    )
    calls: list[dict] = []
    source = project_root / "production" / "source.yml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("fact: grounded\n", encoding="utf-8")
    candidate_source = (
        project_root
        / "runs"
        / "candidate-patch"
        / "outputs"
        / "overlay.yml"
    )
    candidate_source.parent.mkdir(parents=True, exist_ok=True)
    candidate_source.write_text("candidate: contextual only\n", encoding="utf-8")

    def fake_cli(plan, role, profile, **kwargs):
        calls.append(
            {
                "plan": plan,
                "role": role,
                "profile": profile,
                "kwargs": kwargs,
            }
        )
        model_receipt = Path(plan.run_dir) / "model_execution_receipt.yml"
        model_receipt.write_text(
            yaml.safe_dump(
                {
                    "status": "pass",
                    "role": role,
                    "worker": "claude_code",
                    "invocation_contract": "claude_writer",
                    "selected_provider": "deepseek",
                    "selected_model_key": "writer-model",
                    "requested_model_id": "deepseek-v4-pro",
                    "profile_binding_verified": True,
                    "command_binding_verified": True,
                    "provider_model_binding_verified": True,
                    "fallback_detected": False,
                    "provider_process_started": True,
                    "exit_code": 0,
                    "issues": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            status="completed",
            provider="agentlab-cli-executor",
            model="claude_code",
            content="候选文本",
            error=None,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            raw_usage={
                "cli_agent": "claude_code",
                "cli_model_key": "writer-model",
                "cli_model_id": "deepseek-v4-pro",
                "cli_catalog_model_id": "deepseek-v4-pro",
                "cli_runtime_provider": "deepseek",
                "exit_code": 0,
                "model_resolution_failed": False,
                "provider_model_mismatch": False,
                "qwen_provider_model_mismatch": False,
                "grok_provider_model_mismatch": False,
                "model_execution_receipt": str(model_receipt),
            },
        )

    with pytest.raises(
        ValueError,
        match="external context approval request",
    ):
        RoleAttemptExecutor(
            tmp_path,
            project="Demo",
            cli_runner=fake_cli,
        ).execute(
            task_id="task-role",
            work_item_id="writer",
            attempt_id="writer-attempt-unapproved-messages",
            role="Writer",
            messages=[
                {
                    "role": "user",
                    "content": "Do not export this without approval.",
                }
            ],
            idempotency_key="writer-attempt-unapproved-messages",
        )

    with pytest.raises(ValueError, match="expires_at_must_be_future_timezone_aware"):
        RoleAttemptExecutor(
            tmp_path,
            project="Demo",
            cli_runner=fake_cli,
        ).execute(
            task_id="task-role",
            work_item_id="writer",
            attempt_id="writer-attempt-expired-approval",
            role="Writer",
            messages=[{"role": "user", "content": "Do not start this call."}],
            source_paths=[source],
            external_context_request={
                "purpose": "Expired fixture request.",
                "minimal_fragment": "Do not start this call.",
                "expires_at": "2000-01-01T00:00:00Z",
            },
            idempotency_key="writer-attempt-expired-approval",
        )
    assert (
        "writer-attempt-expired-approval"
        not in runtime.load_task("task-role")["attempts"]
    )

    result = RoleAttemptExecutor(
        tmp_path, project="Demo", cli_runner=fake_cli
    ).execute(
        task_id="task-role",
        work_item_id="writer",
        attempt_id="writer-attempt-001",
        role="Writer",
        messages=[{"role": "user", "content": "Write the assigned patch."}],
        source_paths=[source, candidate_source],
        external_context_request={
            "purpose": "Write one bounded candidate.",
            "minimal_fragment": "Write the assigned patch.",
            "expires_at": "2999-01-01T00:00:00Z",
        },
        idempotency_key="writer-attempt-001",
    )

    attempt = result["projection"]["attempts"]["writer-attempt-001"]
    assert attempt["status"] == "succeeded"
    assert attempt["execution_contract"]["input_tier"] == "L1"
    assert attempt["execution_contract"]["route"] == "single_worker"
    assert calls[0]["role"] == "Writer"
    assert calls[0]["profile"]["invocation_contract"] == "claude_writer"
    assert calls[0]["kwargs"]["sealed_messages"][0]["content"].startswith("Write")
    assert calls[0]["kwargs"]["sealed_messages"][1]["content"].startswith(
        "AUTHORITATIVE_SOURCE"
    )
    assert "fact: grounded" in calls[0]["kwargs"]["sealed_messages"][1]["content"]
    assert calls[0]["kwargs"]["sealed_messages"][2]["content"].startswith(
        "GOVERNED_CANDIDATE_SOURCE"
    )
    assert calls[0]["kwargs"]["outbound_source_paths"] == [source, candidate_source]
    assert Path(result["output_path"]).read_text(encoding="utf-8") == "候选文本"
    receipt = yaml.safe_load(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "task-runtime-role-attempt-receipt/v1"
    assert receipt["output_sha256"]
    assert receipt["model_execution"]["model_id"] == "deepseek-v4-pro"

    chained = RoleAttemptExecutor(
        tmp_path, project="Demo", cli_runner=fake_cli
    ).execute(
        task_id="task-role",
        work_item_id="writer",
        attempt_id="writer-attempt-002",
        role="Writer",
        messages=[{"role": "user", "content": "Read the prior Attempt."}],
        source_paths=[Path(result["output_path"])],
        external_context_request={
            "purpose": "Read one prior governed attempt.",
            "minimal_fragment": "Read the prior Attempt.",
            "expires_at": "2999-01-01T00:00:00Z",
        },
        idempotency_key="writer-attempt-002",
    )
    assert chained["projection"]["attempts"]["writer-attempt-002"]["status"] == "succeeded"
    assert calls[-1]["kwargs"]["sealed_messages"][1]["content"].startswith(
        "RUNTIME_V2_SOURCE"
    )

    for child_attempt_id in ("writer-attempt-001", "writer-attempt-002"):
        validation_path = (
            tmp_path
            / "projects"
            / "Demo"
            / "runtime"
            / "tasks"
            / "task-role"
            / "attempt_logs"
            / child_attempt_id
            / "validation.yml"
        )
        child_attempt = runtime.load_task("task-role")["attempts"][child_attempt_id]
        validation_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "protocol-artifact-validation/v1",
                    "status": "pass",
                    "task_id": "task-role",
                    "attempt_id": child_attempt_id,
                    "output_sha256": child_attempt["outcome"]["output_sha256"],
                    "issues": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        runtime.record_attempt_output_validation(
            "task-role",
            attempt_id=child_attempt_id,
            status="pass",
            validation_receipt_path=validation_path,
            issues=[],
            idempotency_key=f"{child_attempt_id}-validation",
        )
    assembled = RoleAttemptExecutor(tmp_path, project="Demo").assemble_validated_attempts(
        task_id="task-role",
        work_item_id="writer",
        attempt_id="writer-assembled-001",
        child_attempt_ids=["writer-attempt-001", "writer-attempt-002"],
        output_text="deterministically assembled output\n",
        idempotency_key="writer-assembled-001",
    )
    assembled_receipt = yaml.safe_load(
        Path(assembled["receipt_path"]).read_text(encoding="utf-8")
    )
    model_receipt_path = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-role"
        / assembled_receipt["model_execution"]["path"]
    )
    model_receipt = yaml.safe_load(model_receipt_path.read_text(encoding="utf-8"))
    assert model_receipt["provider_process_started"] is False
    assert model_receipt["command_binding_verified"] is False
    assert model_receipt["provider_model_binding_verified"] is False
    assert model_receipt["exit_code"] is None
    runtime.verify_attempt_execution_receipt("task-role", "writer-assembled-001")

    governed = RoleAttemptExecutor(
        tmp_path,
        project="Demo",
        cli_runner=fake_cli,
    ).execute(
        task_id="task-role",
        work_item_id="writer",
        attempt_id="writer-attempt-outbound-approved",
        role="Writer",
        messages=[{"role": "user", "content": "Review governed context."}],
        source_paths=[source],
        external_context_request={
            "purpose": "Review one bounded candidate.",
            "minimal_fragment": "Review governed context.",
            "expires_at": "2999-01-01T00:00:00Z",
        },
        idempotency_key="writer-attempt-outbound-approved",
    )
    assert governed["projection"]["attempts"][
        "writer-attempt-outbound-approved"
    ]["status"] == "succeeded"
    outbound_policy = calls[-1]["plan"].execution_policy
    assert outbound_policy["external_context_approval_required"] is True
    assert outbound_policy[
        "external_context_payload_sha256_required"
    ] is True
    assert outbound_policy[
        "external_context_scope_sha256_required"
    ] is True
    assert outbound_policy["external_context_transfer"]["recipient"] == (
        "cli_agent:claude_code;runtime_provider:deepseek"
    )
    assert len(outbound_policy["external_context_scope_sha256"]) == 64

    def mismatched_cli(*args, **kwargs):
        bad_result = fake_cli(*args, **kwargs)
        bad_result.raw_usage["cli_runtime_provider"] = "unexpected-provider"
        return bad_result

    with pytest.raises(InvalidTransition, match="metadata does not match"):
        RoleAttemptExecutor(tmp_path, project="Demo", cli_runner=mismatched_cli).execute(
            task_id="task-role",
            work_item_id="writer",
            attempt_id="writer-attempt-model-mismatch",
            role="Writer",
            messages=[{"role": "user", "content": "Reject a mismatched route."}],
            external_context_request={
                "purpose": "Exercise a mismatched governed route.",
                "minimal_fragment": "Reject a mismatched route.",
                "expires_at": "2999-01-01T00:00:00Z",
            },
            idempotency_key="writer-attempt-model-mismatch",
        )
    assert (
        TaskRuntime(tmp_path, project="Demo")
        .load_task("task-role")["attempts"]["writer-attempt-model-mismatch"]["status"]
        == "failed"
    )

    forbidden = tmp_path / "projects" / "Demo" / "runtime" / "private.yml"
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_text("secret: do-not-export\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside governed project source roots"):
        RoleAttemptExecutor(tmp_path, project="Demo", cli_runner=fake_cli).execute(
            task_id="task-role",
            work_item_id="writer",
            attempt_id="writer-attempt-forbidden",
            role="Writer",
            messages=[{"role": "user", "content": "Read the forbidden source."}],
            source_paths=[forbidden],
            idempotency_key="writer-attempt-forbidden",
        )
    sealed_prompt = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-role"
        / "attempt_logs"
        / "writer-attempt-001"
        / "sealed_user_request.md"
    )
    sealed_prompt.write_text("private prompt", encoding="utf-8")
    with pytest.raises(ValueError, match="outside governed project source roots"):
        RoleAttemptExecutor(tmp_path, project="Demo", cli_runner=fake_cli).execute(
            task_id="task-role",
            work_item_id="writer",
            attempt_id="writer-attempt-private-prompt",
            role="Writer",
            messages=[{"role": "user", "content": "Do not reread prompt logs."}],
            source_paths=[sealed_prompt],
            idempotency_key="writer-attempt-private-prompt",
        )

    Path(result["output_path"]).write_text("tampered output", encoding="utf-8")
    with pytest.raises(InvalidTransition, match="output path or hash"):
        RoleAttemptExecutor(tmp_path, project="Demo", cli_runner=fake_cli).execute(
            task_id="task-role",
            work_item_id="writer",
            attempt_id="writer-attempt-001",
            role="Writer",
            messages=[{"role": "user", "content": "Retry idempotently."}],
            idempotency_key="writer-attempt-001",
        )
    doctor = TaskRuntime(tmp_path, project="Demo").doctor_project()
    assert doctor["ok"] is False
    assert "invalid Attempt receipt" in doctor["tasks"]["task-role"]["failures"][0]


def test_role_executor_resolves_the_cli_runtime_provider_from_catalog() -> None:
    root = Path(__file__).resolve().parents[1]
    executor = RoleAttemptExecutor(root, project="Crown_of_Ash", cli_runner=lambda: None)

    profile, provider = executor._resolve_profile("Writer")

    assert provider == "deepseek"
    assert profile["_resolved_model_id"] == "deepseek-v4-pro"
