from __future__ import annotations

from pathlib import Path
import pytest
from typer.testing import CliRunner

from agent_runtime.capabilities.role_requirements import RoleRequirementsRegistry
from agent_runtime.run_task import app


def test_role_requirements_loads_correctly() -> None:
    roles_path = Path(__file__).resolve().parent.parent / "config" / "agent_role_requirements.yml"
    registry = RoleRequirementsRegistry.load_from_file(roles_path)

    # 9 roles defined
    roles = registry.list_roles()
    assert len(roles) == 9

    # Inspect Coder
    coder_req = registry.get_role_requirements("Coder")
    assert coder_req is not None
    assert "file_edit" in coder_req.required_capabilities
    assert "patch_generation" in coder_req.required_capabilities
    assert coder_req.default_risk_ceiling == "high"

    # Test normalization case-insensitive lookup
    supervisor_req = registry.get_role_requirements("supervisor")
    supervisor_req2 = registry.get_role_requirements("Supervisor")
    assert supervisor_req is not None
    assert supervisor_req == supervisor_req2
    assert "planning" in supervisor_req.required_capabilities
    assert "task_decomposition" in supervisor_req.required_capabilities


def test_role_cli_commands() -> None:
    runner = CliRunner()

    # 1. role-requirements command
    result1 = runner.invoke(app, ["role-requirements"])
    assert result1.exit_code == 0
    assert "coder" in result1.stdout.lower()
    assert "supervisor" in result1.stdout.lower()

    # 2. role-inspect Coder command
    result2 = runner.invoke(app, ["role-inspect", "--role", "Coder"])
    assert result2.exit_code == 0
    assert "file_edit" in result2.stdout
    assert "patch_generation" in result2.stdout
    assert "HIGH" in result2.stdout

    # 3. role-inspect with invalid name returns non-zero code
    result3 = runner.invoke(app, ["role-inspect", "--role", "InvalidRoleName"])
    assert result3.exit_code != 0
    assert "Error: Unknown role" in result3.stdout
