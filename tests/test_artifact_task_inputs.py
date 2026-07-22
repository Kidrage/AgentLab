"""Offline tests for explicit ArtifactTask input contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agent_runtime.protocols import build_artifact_task_contract
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_contract_records_explicit_inputs_with_hashes_and_staging_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    first = root / "inputs" / "source.csv"
    second = root / "brief.md"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"name,value\nalpha,1\n")
    second.write_text("# Exact brief\n", encoding="utf-8")

    packet = build_artifact_task_contract(
        root,
        "Create an xlsx spreadsheet from the assigned inputs.",
        artifact_type="spreadsheet",
        assigned_input_paths=[first, Path("brief.md")],
    )

    assert packet["assigned_inputs"] == [
        {
            "source_path": "inputs/source.csv",
            "staged_path": "artifact_inputs/01_source.csv",
            "sha256": _sha256(first),
            "byte_count": first.stat().st_size,
            "read_only": True,
        },
        {
            "source_path": "brief.md",
            "staged_path": "artifact_inputs/02_brief.md",
            "sha256": _sha256(second),
            "byte_count": second.stat().st_size,
            "read_only": True,
        },
    ]


def test_contract_without_inputs_has_an_empty_explicit_input_set(
    tmp_path: Path,
) -> None:
    packet = build_artifact_task_contract(
        tmp_path,
        "Create a markdown report.",
    )

    assert packet["assigned_inputs"] == []


def test_contract_records_project_relative_logical_path_for_project_inputs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    source = root / "projects" / "Crown_of_Ash" / "production" / "bible" / "world.md"
    source.parent.mkdir(parents=True)
    source.write_text("stable fact\n", encoding="utf-8")

    packet = build_artifact_task_contract(
        root,
        "Create fact_distillation.yml from the assigned input.",
        project="Crown_of_Ash",
        output_path="runs/task_fact/artifacts/fact_distillation.yml",
        assigned_input_paths=[source],
    )

    assert packet["assigned_inputs"][0]["source_path"] == (
        "projects/Crown_of_Ash/production/bible/world.md"
    )
    assert packet["assigned_inputs"][0]["project_path"] == "production/bible/world.md"
    assert packet["validation"]["semantic_validator"] == "fact_distillation"


def test_contract_rejects_directory_input(tmp_path: Path) -> None:
    root = tmp_path / "root"
    directory = root / "inputs"
    directory.mkdir(parents=True)

    with pytest.raises(ValueError, match="regular file"):
        build_artifact_task_contract(
            root,
            "Create a spreadsheet.",
            assigned_input_paths=[directory],
        )


def test_contract_rejects_symbolic_link_input(tmp_path: Path) -> None:
    root = tmp_path / "root"
    source = root / "source.csv"
    link = root / "linked.csv"
    root.mkdir()
    source.write_text("value\n1\n", encoding="utf-8")
    try:
        link.symlink_to(source)
    except OSError as exc:  # pragma: no cover - unsupported host filesystem
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link"):
        build_artifact_task_contract(
            root,
            "Create a spreadsheet.",
            assigned_input_paths=[link],
        )


def test_contract_rejects_input_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside AgentLab root"):
        build_artifact_task_contract(
            root,
            "Create a spreadsheet.",
            assigned_input_paths=[outside],
        )


def test_cli_artifact_task_plan_accepts_repeated_inputs() -> None:
    result = runner.invoke(
        app,
        [
            "artifact-task-plan",
            "--task-text",
            "Create a markdown report.",
            "--input",
            str(ROOT / "README.md"),
            "--input",
            str(ROOT / "AGENTS.md"),
        ],
    )

    assert result.exit_code == 0, result.output
    packet = yaml.safe_load(result.output)
    assert [item["source_path"] for item in packet["assigned_inputs"]] == [
        "README.md",
        "AGENTS.md",
    ]
    assert [item["staged_path"] for item in packet["assigned_inputs"]] == [
        "artifact_inputs/01_README.md",
        "artifact_inputs/02_AGENTS.md",
    ]
    assert all(item["read_only"] is True for item in packet["assigned_inputs"])
