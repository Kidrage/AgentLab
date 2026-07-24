from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console
from typer.testing import CliRunner

from agent_runtime.cli.project_agents import register_project_agent_commands
from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_ops.project_router import init_project
from agent_runtime.project_truth import ChangeSet, FactChange, ProjectTruthStore


def _app(root: Path) -> typer.Typer:
    app = typer.Typer()
    register_project_agent_commands(app, root, Console())
    return app


def test_cli_enables_truth_adds_lists_and_pauses_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Demo"
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Demo",
                "features": {
                    "project_truth_mode": "legacy",
                    "enable_project_agents": False,
                },
                "workspace": {"isolation": "required"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    app = _app(tmp_path)

    enabled = runner.invoke(app, ["project-agents-enable", "--project", "Demo"])
    assert enabled.exit_code == 0, enabled.output

    first_fact = runner.invoke(
        app,
        [
            "set-project-fact",
            "--project",
            "Demo",
            "--key",
            "novel.total_word_count",
            "--value-json",
            "120000",
            "--owner",
            "project.editorial",
            "--idempotency-key",
            "length-v1",
        ],
    )
    assert first_fact.exit_code == 0, first_fact.output
    second_fact = runner.invoke(
        app,
        [
            "set-project-fact",
            "--project",
            "Demo",
            "--key",
            "novel.total_word_count",
            "--value-json",
            "150000",
            "--owner",
            "project.editorial",
            "--idempotency-key",
            "length-v2",
        ],
    )
    assert second_fact.exit_code == 0, second_fact.output
    retried_fact = runner.invoke(
        app,
        [
            "set-project-fact",
            "--project",
            "Demo",
            "--key",
            "novel.total_word_count",
            "--value-json",
            "150000",
            "--owner",
            "project.editorial",
            "--idempotency-key",
            "length-v2",
        ],
    )
    assert retried_fact.exit_code == 0, retried_fact.output
    history = runner.invoke(
        app,
        [
            "project-fact-history",
            "--project",
            "Demo",
            "--key",
            "novel.total_word_count",
        ],
    )
    assert history.exit_code == 0, history.output
    assert history.output.index("150000") < history.output.index("120000")

    added = runner.invoke(
        app,
        [
            "add-agent",
            "--project",
            "Demo",
            "--agent-id",
            "history",
            "--name",
            "History Research Agent",
            "--role",
            "history_researcher",
            "--responsibility",
            "Maintain historical accuracy",
            "--read-scope",
            "world.*",
            "--write-scope",
            "research.history.*",
        ],
    )
    assert added.exit_code == 0, added.output

    listed = runner.invoke(
        app, ["list-agents", "--project", "Demo", "--format", "yaml"]
    )
    assert listed.exit_code == 0, listed.output
    assert "history_researcher" in listed.output

    paused = runner.invoke(
        app, ["pause-agent", "--project", "Demo", "--agent-id", "history"]
    )
    assert paused.exit_code == 0, paused.output
    registry = ProjectAgentRegistry(ProjectTruthStore(project_root))
    assert registry.get("history").status == "paused"
    assert (
        registry.truth.current().facts["novel.total_word_count"].value
        == 150_000
    )


def test_enable_refuses_legacy_content_and_leaves_flags_unchanged(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Legacy"
    (project_root / "project_brain").mkdir(parents=True)
    (project_root / "project_brain" / "rules.yml").write_text(
        "length: 120000\n", encoding="utf-8"
    )
    manifest_path = project_root / "project.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "project_id": "Legacy",
                "features": {
                    "project_truth_mode": "legacy",
                    "enable_project_agents": False,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        _app(tmp_path),
        ["project-agents-enable", "--project", "Legacy"],
    )

    assert result.exit_code != 0
    assert "migration" in result.output
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["features"]["project_truth_mode"] == "legacy"

    assert not (project_root / "project_truth.yml").exists()


def test_cli_rejects_symlink_project_alias(tmp_path: Path) -> None:
    real_root = tmp_path / "projects" / "Real"
    real_root.mkdir(parents=True)
    (real_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Real",
                "features": {
                    "project_truth_mode": "legacy",
                    "enable_project_agents": False,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "projects" / "Alias").symlink_to(
        real_root, target_is_directory=True
    )

    result = CliRunner().invoke(
        _app(tmp_path),
        ["project-agents-enable", "--project", "Alias"],
    )

    assert result.exit_code != 0
    assert "must not be a symlink" in result.output
    assert not (real_root / "project_truth.yml").exists()


def test_new_project_skeleton_can_enable_without_migration(tmp_path: Path) -> None:
    init_project(tmp_path, "Fresh", "generic", "Fresh")

    result = CliRunner().invoke(
        _app(tmp_path),
        ["project-agents-enable", "--project", "Fresh"],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "projects" / "Fresh" / "project_truth.yml").is_file()


def test_enable_rejects_meaningful_legacy_content_with_empty_pointer(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Interrupted"
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Interrupted",
                "features": {
                    "project_truth_mode": "legacy",
                    "enable_project_agents": False,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project_brain").mkdir()
    (project_root / "project_brain" / "rules.yml").write_text(
        "word_count: 120000\n", encoding="utf-8"
    )
    ProjectTruthStore(project_root).initialize("Interrupted")

    result = CliRunner().invoke(
        _app(tmp_path),
        ["project-agents-enable", "--project", "Interrupted"],
    )

    assert result.exit_code != 0
    assert "completed truth migration" in result.output
    manifest = yaml.safe_load(
        (project_root / "project.yml").read_text(encoding="utf-8")
    )
    assert manifest["features"]["project_truth_mode"] == "legacy"

    truth = ProjectTruthStore(project_root)
    truth.commit(
        ChangeSet(
            project_id="Interrupted",
            expected_snapshot_id=truth.current().snapshot_id,
            actor_id="user",
            idempotency_key="unrelated-canonical-write",
            facts=(
                FactChange(
                    key="unrelated.fact",
                    value=True,
                    owner="user",
                ),
            ),
        )
    )
    fake_result = (
        project_root / ".agentlab" / "truth" / "migration_result.yml"
    )
    fake_result.write_text("{}\n", encoding="utf-8")

    forged = CliRunner().invoke(
        _app(tmp_path),
        ["project-agents-enable", "--project", "Interrupted"],
    )

    assert forged.exit_code != 0
    assert "invalid or stale" in forged.output


def test_shadow_mode_persists_non_mutating_conflict_audit(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Shadow"
    (project_root / "project_brain").mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Shadow",
                "features": {
                    "project_truth_mode": "legacy",
                    "enable_project_agents": False,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project_brain" / "rules.yml").write_text(
        "word_count: 120000\n", encoding="utf-8"
    )

    result = CliRunner().invoke(
        _app(tmp_path),
        ["project-truth-shadow", "--project", "Shadow"],
    )

    assert result.exit_code == 0, result.output
    report = project_root / ".agentlab" / "truth" / "shadow_audit.yml"
    assert report.is_file()
    manifest = yaml.safe_load(
        (project_root / "project.yml").read_text(encoding="utf-8")
    )
    assert manifest["features"] == {
        "project_truth_mode": "shadow",
        "enable_project_agents": False,
    }
    assert not (project_root / "project_truth.yml").exists()
