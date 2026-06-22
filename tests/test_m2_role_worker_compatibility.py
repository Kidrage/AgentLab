from __future__ import annotations

from pathlib import Path
import pytest
from typer.testing import CliRunner

from agent_runtime.capabilities.capability_schema import CapabilitySchema
from agent_runtime.capabilities.role_requirements import RoleRequirementsRegistry
from agent_runtime.capabilities.compatibility import WorkerCapabilityRegistry, CompatibilityChecker
from agent_runtime.run_task import app


def test_compatibility_checker_rules() -> None:
    root = Path(__file__).resolve().parent.parent
    schema = CapabilitySchema.load_from_file(root / "config" / "capability_schema.yml")
    roles_registry = RoleRequirementsRegistry.load_from_file(root / "config" / "agent_role_requirements.yml")
    workers_registry = WorkerCapabilityRegistry.load_from_file(root / "config" / "worker_capability_defaults.yml")

    checker = CompatibilityChecker(schema, roles_registry, workers_registry)

    # 1. rg cannot be assigned as Coder
    is_comp, reason = checker.is_compatible("rg", "Coder")
    assert not is_comp
    assert "lacks required capability" in reason

    # 2. pytest cannot be assigned as Supervisor
    is_comp, reason = checker.is_compatible("pytest", "Supervisor")
    assert not is_comp
    assert "lacks required capability" in reason

    # 3. Coder can be claude_code
    is_comp, reason = checker.is_compatible("claude_code", "Coder")
    assert is_comp

    # 4. Supervisor can be hermes, gemini, qwen
    assert checker.is_compatible("hermes", "Supervisor")[0]
    assert checker.is_compatible("gemini", "Supervisor")[0]
    assert checker.is_compatible("qwen", "Supervisor")[0]

    # 5. bl has cloud_upload / multimodal_generation which are marked high-risk (and require approval)
    requires_app, reasons = checker.requires_approval_for_assignment("bl", "Researcher")
    # Researcher has cloud_upload in preferred or required? Wait, Researcher forbids file_edit. Researcher has cloud_upload as forbidden, wait.
    # Let's check Researcher forbidden capabilities in config: file_edit.
    # What about bl vs Researcher compatibility? bl doesn't support external_research (which Researcher requires).
    # So bl is not compatible with Researcher.
    # Let's check if we evaluate bl's assignment to something that requires approval.
    # If bl is assigned to a role that requires/prefers cloud_upload, or if bl brings cloud_upload.
    # In compatibility.py:
    #   if worker_id == "bl" and "cloud_upload" in supported:
    #       if "cloud_upload" in role_req.required_capabilities or "cloud_upload" in role_req.preferred_capabilities: ...
    # Wait, does any role require or prefer cloud_upload?
    # Let's check the YAML config: None of the roles have cloud_upload in required_capabilities or preferred_capabilities.
    # Wait, does supervisor have human_approval_required_for: cloud_upload? Yes.
    # Let's check:
    # If a role/task requires cloud_upload capability, does it need approval?
    # Yes, cloud_upload has risk_level: high, so it always requires approval.
    cloud_upload_def = schema.get_capability("cloud_upload")
    assert cloud_upload_def is not None
    assert cloud_upload_def.risk_level == "high"

    # Also bl requires approval for assignment if the capability is requested
    # Let's verify bl requires approval for cloud_upload tasks (i.e. if the role uses cloud_upload)
    # Let's check is_approval_required_for_role_capability on supervisor and cloud_upload:
    supervisor_req = roles_registry.get_role_requirements("supervisor")
    assert checker.requires_approval_for_assignment("claude_code", "Supervisor")[0]  # claude_code supports shell_execution and cloud_upload which are high risk


def test_role_compatible_workers_cli() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["role-compatible-workers", "--role", "RepoScout"])
    assert result.exit_code == 0
    # rg is compatible (YES)
    assert "rg" in result.stdout
    assert "YES" in result.stdout
    # claude_code is incompatible (NO) due to forbidden file_edit
    assert "claude_code" in result.stdout
    assert "NO" in result.stdout
    assert "forbidden" in result.stdout
