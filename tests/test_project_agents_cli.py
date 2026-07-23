from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console
from typer.testing import CliRunner

from agent_runtime.cli.project_agents import register_project_agent_commands
from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_truth import ProjectTruthStore


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
