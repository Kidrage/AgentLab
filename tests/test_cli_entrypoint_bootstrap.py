from pathlib import Path
import os
import shutil

from typer.testing import CliRunner
import yaml

from agent_runtime.protocols import (
    doctor_cli_entrypoints,
    install_cli_entrypoints,
    scan_cli_entrypoints,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _copy_config(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    (root / "config").mkdir(parents=True)
    for name in [
        "cli_entrypoint_policy.yml",
        "agent_role_bindings.yml",
        "protocol_enforcement.yml",
        "agent_collaboration.yml",
        "shared_agent_directory.yml",
        "worker_invocation_contracts.yml",
    ]:
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    (root / "docs").mkdir()
    for name in [
        "WORKSPACE_ENTRY_PROTOCOL.md",
        "FRONTDESK_PROTOCOL.md",
        "ROLE_SESSION_PROTOCOL.md",
        "PROTOCOL_ENFORCEMENT.md",
        "CLI_ENTRYPOINT_BOOTSTRAP.md",
    ]:
        shutil.copy(ROOT / "docs" / name, root / "docs" / name)
    (root / "agentlab.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return root


def _fake_bins(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for cmd in ["agy", "openclaw", "codex", "qwen", "claude", "hermes"]:
        path = bin_dir / cmd
        path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")


def test_scan_recognizes_configurable_agents(tmp_path, monkeypatch):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)

    result = scan_cli_entrypoints(root)

    assert result["recognized"]["agy"]["profiles"] == ["frontdesk"]
    assert "worker" in result["recognized"]["codex"]["profiles"]
    assert result["recognized"]["claude_code"]["command"] == "claude"
    assert result["ignored"]["bl"]["reason"] == "specialist_cloud_tool_not_entrypoint"


def test_install_writes_managed_entrypoints_and_wrappers(tmp_path, monkeypatch):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)
    custom_entry = root / ".agy" / "AGENTLAB_ENTRYPOINT.md"
    custom_entry.parent.mkdir()
    custom_entry.write_text("custom user note\n", encoding="utf-8")

    result = install_cli_entrypoints(root, write=True)

    assert "agy" in result["installed"]
    agy_text = custom_entry.read_text(encoding="utf-8")
    assert "custom user note" in agy_text
    assert "AGENTLAB_MANAGED_START" in agy_text
    assert "workspace-entry --agent agy" in agy_text

    agy_role = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "workers" / "agy-role-agentlab"
    agy_frontdesk = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "frontdesk" / "agy-agentlab"
    codex_role = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "workers" / "codex-role-agentlab"

    assert agy_frontdesk.exists()
    assert not agy_role.exists()
    assert codex_role.exists()
    assert "protocol-doctor" in codex_role.read_text(encoding="utf-8")
    assert "role-doctor" in codex_role.read_text(encoding="utf-8")
    assert "role-session" in codex_role.read_text(encoding="utf-8")


def test_install_respects_policy_wrapper_kind(tmp_path, monkeypatch):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)
    policy_path = root / "config" / "cli_entrypoint_policy.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["agents"]["codex"]["wrapper_kind"] = "frontdesk"
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = install_cli_entrypoints(root, agent="codex", write=True)

    assert set(result["installed"]["codex"]["wrappers"]) == {"frontdesk"}
    codex_role = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "workers" / "codex-role-agentlab"
    assert not codex_role.exists()


def test_doctor_passes_after_install_and_detects_drift(tmp_path, monkeypatch):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)

    install_cli_entrypoints(root, write=True)
    good = doctor_cli_entrypoints(root)
    assert good["status"] == "pass"

    wrapper = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "frontdesk" / "agy-agentlab"
    wrapper.write_text("#!/usr/bin/env bash\nagy\n", encoding="utf-8")
    wrapper.chmod(0o755)

    bad = doctor_cli_entrypoints(root, agent="agy")
    assert bad["status"] == "fail"
    assert any(c["id"] == "wrapper_protocol_compliant" and c["status"] == "fail" for c in bad["checks"])


def test_cli_entrypoint_bootstrap_plan_does_not_write(monkeypatch, tmp_path):
    # Exercise the public Typer command against the real repo in plan mode only.
    result = runner.invoke(app, ["cli-entrypoint-bootstrap"])

    assert result.exit_code == 0
    assert "write: false" in result.output
