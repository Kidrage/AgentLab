from __future__ import annotations

from pathlib import Path
import pytest
from typer.testing import CliRunner

from agent_runtime.capabilities.capability_schema import CapabilitySchema
from agent_runtime.run_task import app


def test_capability_schema_loads_correctly() -> None:
    schema_path = Path(__file__).resolve().parent.parent / "config" / "capability_schema.yml"
    schema = CapabilitySchema.load_from_file(schema_path)

    planning_cap = schema.get_capability("planning")
    assert planning_cap is not None
    assert planning_cap.display_name == "Planning"
    assert planning_cap.risk_level == "medium"

    cloud_upload_cap = schema.get_capability("cloud_upload")
    assert cloud_upload_cap is not None
    assert cloud_upload_cap.risk_level == "high"

    # Make sure all 25 capability families exist
    caps = schema.list_capabilities()
    assert len(caps) >= 25


def test_capabilities_cli() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["capabilities"])
    assert result.exit_code == 0
    assert "Planning" in result.stdout
    assert "Cloud Upload" in result.stdout
