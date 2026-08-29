from __future__ import annotations

from pathlib import Path
import hashlib
import shutil

import pytest
import yaml

from agent_runtime.narrative.author_team import (
    materialize_author_team_contract,
    register_author_team_proposal,
)
from agent_runtime.narrative.metric_universe import metric_universe_issues
from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_agents.contract import (
    effective_contract_hash,
)
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import InvalidTransition, TaskRuntime
from agent_runtime.task_runtime_v2.deterministic_executor import (
    DeterministicToolExecutor,
)
from task_runtime_v2_support import execute_role_with_output


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "Crown_of_Ash"


def _registered_project(root: Path) -> tuple[ProjectTruthStore, str]:
    config = root / "config"
    config.mkdir()
    for name in (
        "narrative_author_team.yml",
        "agent_registry.yml",
        "agent_model_profiles.yml",
        "task_input_tiers.yml",
    ):
        (config / name).write_bytes((ROOT / "config" / name).read_bytes())
    project_root = root / "projects" / PROJECT
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": PROJECT,
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
    pointer = truth.initialize(PROJECT)
    proposed = materialize_author_team_contract(
        root,
        project=PROJECT,
        task_id="task_author_team",
        template_path=config / "narrative_author_team.yml",
    )
    register_author_team_proposal(
        root,
        project=PROJECT,
        proposal_path=root / proposed["proposal_path"],
        expected_proposal_sha256=proposed["proposal_sha256"],
        expected_snapshot_id=pointer.current_snapshot_id,
        actor_id="user",
        approved=True,
    )
    return truth, truth.current().snapshot_id


def _bound_work_item(
    runtime: TaskRuntime,
    truth: ProjectTruthStore,
    *,
    task_id: str,
    work_item_id: str,
    kind: str,
    agent_id: str,
    snapshot_id: str,
) -> None:
    manifest = ProjectAgentRegistry(truth).get(agent_id)
    runtime.create_work_item(
        task_id,
        job_id="job-main",
        work_item_id=work_item_id,
        kind=kind,
        title=work_item_id,
        idempotency_key=f"create-{work_item_id}",
        assigned_agent_id=agent_id,
        agent_manifest_revision=manifest.manifest_revision,
        canonical_snapshot_id=snapshot_id,
        effective_contract_hash=effective_contract_hash(manifest),
    )


def test_metric_universe_runs_as_real_deterministic_attempt(
    tmp_path: Path,
) -> None:
    truth, snapshot_id = _registered_project(tmp_path)
    runtime = TaskRuntime(tmp_path, project=PROJECT)
    subject_task = "task_metric_subject"
    subject_attempt = "attempt_metric_subject"
    subject_work = "work_metric_subject"
    runtime.create_task(
        task_id=subject_task,
        title="Hard continuity audit",
        user_goal="Produce one verified continuity audit subject.",
        input_profile={
            "kind": "creative_patch",
            "scope": "localized",
            "target_count": 1,
            "canon_impact": "candidate",
            "risk_flags": [],
        },
        idempotency_key="create-subject-task",
    )
    _bound_work_item(
        runtime,
        truth,
        task_id=subject_task,
        work_item_id=subject_work,
        kind="narrative-hard-continuity-audit",
        agent_id="canon_timeline_steward",
        snapshot_id=snapshot_id,
    )
    subject = {
        "schema_version": "narrative-hard-continuity-audit/v1",
        "project": PROJECT,
        "status": "pass",
        "blocking_findings": [],
        "evidence_bindings": [{"path": "project.yml", "sha256": hashlib.sha256(
            (tmp_path / "projects" / PROJECT / "project.yml").read_bytes()
        ).hexdigest()}],
        "runtime_binding": {
            "task_id": subject_task,
            "attempt_id": subject_attempt,
            "work_item_id": subject_work,
        },
    }
    execute_role_with_output(
        runtime,
        tmp_path,
        task_id=subject_task,
        work_item_id=subject_work,
        attempt_id=subject_attempt,
        role="Reviewer",
        output=subject,
        project=PROJECT,
    )
    subject_path = (
        tmp_path
        / "projects"
        / PROJECT
        / "acceptance"
        / "metric-subjects"
        / "hard_continuity_errors"
        / "001.yml"
    )
    subject_path.parent.mkdir(parents=True)
    shutil.copyfile(
        tmp_path
        / "projects"
        / PROJECT
        / "runtime"
        / "tasks"
        / subject_task
        / "attempt_logs"
        / subject_attempt
        / "output.md",
        subject_path,
    )

    task_id = "task_metric_universe"
    work_item_id = "work_metric_universe"
    attempt_id = "attempt_metric_universe"
    runtime.create_task(
        task_id=task_id,
        title="Project metric universe",
        user_goal="Project the exact verified hard-continuity subject set.",
        input_profile={
            "kind": "exact_patch",
            "scope": "single_detail",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
        },
        idempotency_key="create-universe-task",
    )
    _bound_work_item(
        runtime,
        truth,
        task_id=task_id,
        work_item_id=work_item_id,
        kind="metric-universe",
        agent_id="state_projector",
        snapshot_id=snapshot_id,
    )

    result = DeterministicToolExecutor(
        tmp_path,
        project=PROJECT,
    ).execute_metric_universe(
        task_id=task_id,
        work_item_id=work_item_id,
        attempt_id=attempt_id,
        metric_id="hard_continuity_errors",
        idempotency_key="execute-universe",
    )
    attempt = result["projection"]["attempts"][attempt_id]
    artifact_path = tmp_path / "projects" / PROJECT / result["artifact"]["path"]
    document = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome"]["execution_origin"] == (
        "deterministic_tool_executor"
    )
    assert runtime.verify_attempt_execution_receipt(
        task_id,
        attempt_id,
    )["output_sha256"] == result["artifact"]["sha256"]
    assert metric_universe_issues(
        tmp_path / "projects" / PROJECT,
        document,
    ) == []


def test_role_executor_origin_cannot_complete_deterministic_contract(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "task_input_tiers.yml").write_bytes(
        (ROOT / "config" / "task_input_tiers.yml").read_bytes()
    )
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-deterministic",
        title="Deterministic attempt",
        user_goal="Reject a model executor claiming deterministic provenance.",
        input_profile={
            "kind": "exact_patch",
            "scope": "single_detail",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
        },
        idempotency_key="create-task",
    )
    runtime.create_work_item(
        "task-deterministic",
        job_id="job-main",
        work_item_id="work-deterministic",
        kind="metric-universe",
        title="Metric universe",
        idempotency_key="create-work",
    )
    runtime.schedule_attempt(
        "task-deterministic",
        work_item_id="work-deterministic",
        attempt_id="attempt-deterministic",
        worker="agentlab.narrative.metric_universe_projector",
        provider="agentlab-deterministic",
        execution_contract={
            "role": "Scribe",
            "executor_type": "deterministic_tool",
            "input_tier": "L0",
            "route": "brain_direct",
            "deterministic_tool": {
                "tool_id": "agentlab.narrative.metric_universe_projector",
                "tool_version": "1",
                "input_tree_sha256": "a" * 64,
            },
        },
        idempotency_key="schedule-attempt",
    )
    runtime.transition_attempt(
        "task-deterministic",
        attempt_id="attempt-deterministic",
        status="running",
        idempotency_key="run-attempt",
    )
    task_root = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-deterministic"
    )
    attempt_root = task_root / "attempt_logs" / "attempt-deterministic"
    attempt_root.mkdir(parents=True)
    receipt_path = attempt_root / "receipt.yml"
    receipt_path.write_text("status: pass\n", encoding="utf-8")

    with pytest.raises(
        InvalidTransition,
        match="cannot impersonate a deterministic tool",
    ):
        runtime._transition_executed_attempt(
            "task-deterministic",
            attempt_id="attempt-deterministic",
            status="succeeded",
            idempotency_key="fake-role-success",
            outcome={
                "execution_origin": "role_attempt_executor",
                "receipt_path": receipt_path.relative_to(task_root).as_posix(),
                "receipt_sha256": hashlib.sha256(
                    receipt_path.read_bytes()
                ).hexdigest(),
                "output_sha256": "b" * 64,
            },
        )
