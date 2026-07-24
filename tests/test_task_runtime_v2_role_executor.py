from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent_runtime.project_agents import (
    AgentLifecycle,
    AgentManifest,
    ProjectAgentRegistry,
    effective_contract_hash,
)
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import InvalidTransition, RoleAttemptExecutor, TaskRuntime


def test_role_executor_dispatches_recorded_route_and_pins_attempt_receipt(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "agent_model_profiles.yml").write_text(
        yaml.safe_dump(
            {
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
        idempotency_key="work-writer",
    )
    calls: list[dict] = []
    source = tmp_path / "projects" / "Demo" / "production" / "source.yml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("fact: grounded\n", encoding="utf-8")
    candidate_source = (
        tmp_path
        / "projects"
        / "Demo"
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
                    "selected_model_id": "deepseek-v4-pro",
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

    result = RoleAttemptExecutor(
        tmp_path, project="Demo", cli_runner=fake_cli
    ).execute(
        task_id="task-role",
        work_item_id="writer",
        attempt_id="writer-attempt-001",
        role="Writer",
        messages=[{"role": "user", "content": "Write the assigned patch."}],
        source_paths=[source, candidate_source],
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
        idempotency_key="writer-attempt-002",
    )
    assert chained["projection"]["attempts"]["writer-attempt-002"]["status"] == "succeeded"
    assert calls[-1]["kwargs"]["sealed_messages"][1]["content"].startswith(
        "RUNTIME_V2_SOURCE"
    )

    idempotent_executor = RoleAttemptExecutor(
        tmp_path,
        project="Demo",
        cli_runner=fake_cli,
    )

    def reject_new_profile_resolution(*args, **kwargs):
        raise AssertionError("successful Attempt retry must not resolve a new route")

    idempotent_executor._resolve_bound_profile = reject_new_profile_resolution
    idempotent = idempotent_executor.execute(
        task_id="task-role",
        work_item_id="writer",
        attempt_id="writer-attempt-001",
        role="Writer",
        messages=[{"role": "user", "content": "Return the immutable receipt."}],
        idempotency_key="writer-attempt-001",
    )
    assert idempotent["receipt_path"] == result["receipt_path"]

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


def test_bound_agent_model_profile_selects_runtime_tier_and_replacement(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "agent_model_profiles.yml").write_text(
        yaml.safe_dump(
            {
                "tier_policy": {
                    "default_tier": "performance",
                    "tiers": {
                        "full": {
                            "budget_aliases": [
                                "max_quality",
                                "full",
                                "high_reasoning",
                            ]
                        },
                        "performance": {
                            "budget_aliases": ["balanced", "performance"]
                        },
                    },
                },
                "modes": {
                    "full_cli": {
                        "tiers": {
                            "full": {
                                "writer": {
                                    "executor_type": "cli_agent",
                                    "cli_agent": "claude_code",
                                    "invocation_contract": "writer-full",
                                    "default": "writer-full-model",
                                }
                            },
                            "performance": {
                                "writer": {
                                    "executor_type": "cli_agent",
                                    "cli_agent": "claude_code",
                                    "invocation_contract": "writer-balanced",
                                    "default": "writer-balanced-model",
                                }
                            },
                        }
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "writer-full-model": {
                        "runtime_provider": "deepseek",
                        "model_id": "deepseek-v4-pro",
                    },
                    "writer-balanced-model": {
                        "runtime_provider": "deepseek",
                        "model_id": "deepseek-v4-flash",
                    },
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
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project_root)
    initial = truth.initialize("Demo")
    registry = ProjectAgentRegistry(truth)
    manifest = AgentManifest(
        id="writer",
        name="Writer Agent",
        version="1.0.0",
        role="writer",
        description="Write governed project artifacts.",
        responsibilities=("Write the assigned artifact.",),
        runtime_role="Writer",
        read_scope=("narrative.*",),
        write_scope=("manuscript.*",),
        approval_scope=(),
        knowledge_binding={"namespace": "agent.Demo.writer"},
        model_profile="high_reasoning",
        tool_permission=("knowledge.read",),
        budget_profile="standard",
        status="active",
        acceptance_rules=("artifact_is_complete",),
    )
    registry.register(
        manifest,
        expected_snapshot_id=initial.current_snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )
    current = truth.current()
    bound_work_item = {
        "assigned_agent_id": "writer",
        "agent_manifest_revision": 1,
        "canonical_snapshot_id": current.snapshot_id,
        "effective_contract_hash": effective_contract_hash(registry.get("writer")),
    }
    executor = RoleAttemptExecutor(tmp_path, project="Demo", cli_runner=lambda: None)

    profile, provider, model_profile = executor._resolve_bound_profile(
        "Writer",
        bound_work_item,
    )

    assert provider == "deepseek"
    assert model_profile == "high_reasoning"
    assert profile["_resolved_tier"] == "full"
    assert profile["_resolved_budget_mode"] == "max_quality"
    assert profile["_resolved_model_id"] == "deepseek-v4-pro"
    with pytest.raises(InvalidTransition, match="unknown Agent model profile"):
        executor._resolve_profile("Writer", model_profile="unregistered-tier")

    replaced = AgentLifecycle(registry).replace(
        "writer",
        model_profile="balanced",
        expected_snapshot_id=current.snapshot_id,
        actor_id="user",
    )
    updated = registry.get("writer")
    replacement_binding = {
        "assigned_agent_id": "writer",
        "agent_manifest_revision": updated.manifest_revision,
        "canonical_snapshot_id": replaced.snapshot_id,
        "effective_contract_hash": effective_contract_hash(updated),
    }

    profile, provider, model_profile = executor._resolve_bound_profile(
        "Writer",
        replacement_binding,
    )

    assert provider == "deepseek"
    assert model_profile == "balanced"
    assert profile["_resolved_tier"] == "performance"
    assert profile["_resolved_budget_mode"] == "balanced"
    assert profile["_resolved_model_id"] == "deepseek-v4-flash"
    with pytest.raises(ValueError, match="canonical snapshot binding is stale"):
        executor._resolve_bound_profile("Writer", bound_work_item)
