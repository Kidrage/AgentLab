from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import typer
import yaml
from rich.console import Console
from typer.testing import CliRunner

from agent_runtime.cli.task_runtime_v2 import register_task_runtime_commands
from agent_runtime.narrative import blueprint_shards
from agent_runtime.project_agents import ProjectAgentFactory, ProjectAgentRegistry
from agent_runtime.project_ops.project_router import init_project
from agent_runtime.project_truth import ProjectTruthStore


ROOT = Path(__file__).resolve().parents[1]


def test_blueprint_shard_cli_allows_bounded_recovery_attempts(
    tmp_path: Path, monkeypatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return {"status": "candidate"}

    monkeypatch.setattr(blueprint_shards, "run_blueprint_shard_workflow", fake_run)
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    result = CliRunner().invoke(
        app,
        [
            "task",
            "execute-blueprint-shards",
            "--project",
            "Demo",
            "--task-id",
            "task-demo",
            "--total-chapters",
            "40",
            "--volume-count",
            "1",
            "--title",
            "Demo",
            "--writer-work-item-id",
            "writer",
            "--story-artifact-type",
            "story_blueprint",
            "--candidate-gate-id",
            "candidate_hash_bound",
            "--context-artifact-type",
            "outline_tree",
            "--required-field",
            "chapter_id",
            "--writer-instruction",
            "writer.md",
            "--external-context-request",
            "request.yml",
            "--semantic-contract",
            "contract.yml",
            "--retries-per-volume",
            "10",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["retries_per_volume"] == 10


def test_task_runtime_cli_exposes_one_task_lifecycle_and_project_doctor(
    tmp_path: Path,
) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--title",
            "One business goal",
            "--goal",
            "Keep all work under one Task.",
            "--idempotency-key",
            "request-one",
        ],
    )
    paused = runner.invoke(
        app,
        [
            "task",
            "pause",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--idempotency-key",
            "pause-one",
        ],
    )
    resumed = runner.invoke(
        app,
        [
            "task",
            "resume",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--idempotency-key",
            "resume-one",
        ],
    )
    paused_again = runner.invoke(
        app,
        [
            "task",
            "pause",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--idempotency-key",
            "pause-two",
        ],
    )
    doctor = runner.invoke(app, ["runtime", "doctor", "--project", "Demo"])
    compatibility_help = runner.invoke(app, ["runtime-v2", "--help"])

    assert created.exit_code == 0, created.output
    assert paused.exit_code == 0, paused.output
    assert "status: paused" in paused.output
    assert resumed.exit_code == 0, resumed.output
    assert "status: running" in resumed.output
    assert paused_again.exit_code == 0, paused_again.output
    assert "status: paused" in paused_again.output
    assert doctor.exit_code == 0, doctor.output
    assert compatibility_help.exit_code == 0, compatibility_help.output
    assert "ok: true" in doctor.output.lower()


def test_task_cli_creates_and_prepares_exact_protocol(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()
    facts = {
        "kind": "code_build",
        "scope": "large",
        "target_count": 6,
        "canon_impact": "none",
        "risk_flags": [],
        "repository": "fixture-repository",
    }

    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "CodeCanary",
            "--task-id",
            "task-code-canary",
            "--title",
            "Repair fixture",
            "--goal",
            "Produce one tested patch.",
            "--protocol-ref",
            "code.large.v1",
            "--input-profile-json",
            json.dumps(facts),
            "--idempotency-key",
            "create-code-canary",
        ],
    )
    executed = runner.invoke(
        app,
        [
            "task",
            "execute",
            "--project",
            "CodeCanary",
            "--task-id",
            "task-code-canary",
        ],
    )

    assert created.exit_code == 0, created.output
    assert "protocol_ref: code.large.v1" in created.output
    assert executed.exit_code == 0, executed.output
    assert "compiled_protocol:" in executed.output
    assert "promotion_verification:" in executed.output


def test_runtime_cli_runs_both_protocol_canaries(tmp_path: Path) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, ROOT, Console(width=120))
    result = CliRunner().invoke(
        app,
        [
            "runtime",
            "protocol-canary",
            "--iterations",
            "1",
            "--state-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "schema_version: protocol-canary-report/v1" in result.output
    assert "canary: NovelCanary" in result.output
    assert "canary: CodeCanary" in result.output


def test_work_item_cli_can_require_user_acceptance(tmp_path: Path) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-acceptance-gate",
            "--title",
            "Acceptance gate",
            "--goal",
            "Keep projection behind explicit user acceptance.",
            "--idempotency-key",
            "create-acceptance-gate",
        ],
    )
    gated = runner.invoke(
        app,
        [
            "work-item",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-acceptance-gate",
            "--work-item-id",
            "state-projector",
            "--kind",
            "verification",
            "--title",
            "Project accepted state",
            "--requires-user-acceptance",
            "--idempotency-key",
            "create-state-projector",
        ],
    )

    assert created.exit_code == 0, created.output
    assert gated.exit_code == 0, gated.output
    assert "requires_user_acceptance: true" in gated.output.lower()
    assert "status: ready" in gated.output.lower()


def test_work_item_cli_materializes_project_agent_collaboration(
    tmp_path: Path,
) -> None:
    init_project(tmp_path, "Demo", "narrative_project", "Demo")
    project_root = tmp_path / "projects" / "Demo"
    project = yaml.safe_load((project_root / "project.yml").read_text(encoding="utf-8"))
    project["features"] = {
        "project_truth_mode": "enforced",
        "enable_project_agents": True,
    }
    (project_root / "project.yml").write_text(
        yaml.safe_dump(project, sort_keys=False),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project_root)
    initial = truth.initialize("Demo")
    ProjectAgentFactory().create_team(
        ProjectAgentRegistry(truth),
        "成人黑暗幻想小说，需要谜团悬念控制与成熟感官美学",
        expected_snapshot_id=initial.current_snapshot_id,
        actor_id="user",
        approved=True,
    )
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()
    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "pilot",
            "--title",
            "Pilot",
            "--goal",
            "Create one governed narrative pilot.",
            "--idempotency-key",
            "create-pilot",
        ],
    )
    materialized = runner.invoke(
        app,
        [
            "work-item",
            "materialize-collaboration",
            "--project",
            "Demo",
            "--task-id",
            "pilot",
            "--domain",
            "narrative",
            "--idempotency-prefix",
            "pilot-dag",
        ],
    )

    assert created.exit_code == 0, created.output
    assert materialized.exit_code == 0, materialized.output
    assert "mystery-check" in materialized.output
    assert "style-check" in materialized.output
    assert "canonical_snapshot_id" in materialized.output


def test_task_cli_previews_and_records_strict_input_tier(tmp_path: Path) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()
    profile = (
        '{"kind":"prose_build","scope":"multi_chapter","target_count":0,'
        '"canon_impact":"canonical","risk_flags":["longform_continuity"]}'
    )

    preview = runner.invoke(
        app,
        ["task", "classify", "--input-profile-json", profile],
    )
    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-prose",
            "--title",
            "First governed prose build",
            "--goal",
            "Let the Brain choose and govern the first prose build.",
            "--input-profile-json",
            profile,
            "--idempotency-key",
            "request-prose",
        ],
    )

    assert preview.exit_code == 0, preview.output
    assert "tier: L3" in preview.output
    assert "route: governed_pipeline" in preview.output
    assert created.exit_code == 0, created.output
    assert "input_classification:" in created.output
    assert "brain_decision_required: true" in created.output.lower()


def test_trace_cli_records_immutable_memory_receipt(tmp_path: Path) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()
    profile = (
        '{"kind":"exact_patch","scope":"single_detail","target_count":1,'
        '"canon_impact":"candidate","risk_flags":[]}'
    )
    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-trace",
            "--title",
            "Trace one patch",
            "--goal",
            "Keep one detail update traceable.",
            "--input-profile-json",
            profile,
            "--idempotency-key",
            "create-trace",
        ],
    )
    source = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-trace"
        / "records"
        / "staging"
        / "memory.yml"
    )
    source.parent.mkdir(parents=True)
    memory_file = tmp_path / "projects" / "Demo" / "candidate" / "detail.yml"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text("detail: retained\n", encoding="utf-8")
    memory_path = memory_file.relative_to(tmp_path).as_posix()
    memory_hash = hashlib.sha256(memory_file.read_bytes()).hexdigest()
    source.write_text(
        "schema_version: memory-update-receipt/v1\n"
        "status: pass\n"
        f"updated_paths: [{memory_path}]\n"
        f"content_hashes: {{{memory_path}: {memory_hash}}}\n",
        encoding="utf-8",
    )

    recorded = runner.invoke(
        app,
        [
            "trace",
            "record",
            "--project",
            "Demo",
            "--task-id",
            "task-trace",
            "--record-id",
            "memory-one",
            "--record-type",
            "memory_update",
            "--producer",
            "brain",
            "--producer-role",
            "Supervisor",
            "--path",
            str(source),
            "--idempotency-key",
            "memory-one",
        ],
    )

    assert created.exit_code == 0, created.output
    assert recorded.exit_code == 0, recorded.output
    assert "record_type: memory_update" in recorded.output
    assert "records/immutable/memory-one/" in recorded.output
