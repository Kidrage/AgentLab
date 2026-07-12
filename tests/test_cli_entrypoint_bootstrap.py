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

    assert result["recognized"]["agy"]["profiles"] == ["frontdesk", "worker"]
    assert result["recognized"]["codex"]["profiles"] == ["worker"]
    assert result["recognized"]["hermes"]["profiles"] == ["frontdesk", "worker"]
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
    codex_frontdesk = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "frontdesk" / "codex-agentlab"
    hermes_frontdesk = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "frontdesk" / "hermes-agentlab"

    assert agy_frontdesk.exists()
    assert agy_role.exists()
    assert codex_role.exists()
    assert not codex_frontdesk.exists()
    assert hermes_frontdesk.exists()
    assert "--provider deepseek -m deepseek-v4-pro" in hermes_frontdesk.read_text(encoding="utf-8")
    assert "ArtifactProducer" not in agy_role.read_text(encoding="utf-8")
    assert "protocol-doctor" in codex_role.read_text(encoding="utf-8")
    assert "role-doctor" in codex_role.read_text(encoding="utf-8")
    assert "role-session" in codex_role.read_text(encoding="utf-8")


def test_optional_entrypoint_write_failure_does_not_block_hermes_wrappers(
    tmp_path,
    monkeypatch,
):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)
    protected_entrypoint = root / ".hermes" / "AGENTLAB_ENTRYPOINT.md"
    original_write_text = Path.write_text

    def guarded_write_text(path, data, *args, **kwargs):
        if path == protected_entrypoint:
            raise PermissionError("managed CLI workspace is read-only")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", guarded_write_text)
    result = install_cli_entrypoints(root, agent="hermes", write=True)
    installed = result["installed"]["hermes"]

    assert installed["entrypoint_required"] is False
    assert installed["entrypoint_status"] == "optional_write_skipped"
    assert "PermissionError" in installed["entrypoint_error"]
    assert Path(installed["wrappers"]["frontdesk"]).exists()
    assert Path(installed["wrappers"]["role"]).exists()


def test_install_removes_stale_wrapper_for_disabled_profile(tmp_path, monkeypatch):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)
    stale = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "frontdesk" / "codex-agentlab"
    stale.parent.mkdir(parents=True)
    stale.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    result = install_cli_entrypoints(root, agent="codex", write=True)

    assert not stale.exists()
    assert str(stale) in result["installed"]["codex"]["removed_wrappers"]


def test_doctor_allows_missing_optional_entrypoint_when_wrappers_exist(tmp_path, monkeypatch):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)
    install_cli_entrypoints(root, agent="hermes", write=True)
    (root / ".hermes" / "AGENTLAB_ENTRYPOINT.md").unlink()

    report = doctor_cli_entrypoints(root, agent="hermes")

    assert report["status"] == "pass"
    assert report["summary"]["failed"] == 0
    assert report["summary"]["warnings"] == 2


def test_install_respects_policy_wrapper_kind(tmp_path, monkeypatch):
    root = _copy_config(tmp_path)
    _fake_bins(tmp_path, monkeypatch)
    policy_path = root / "config" / "cli_entrypoint_policy.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["agents"]["hermes"]["wrapper_kind"] = "frontdesk"
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = install_cli_entrypoints(root, agent="hermes", write=True)

    assert set(result["installed"]["hermes"]["wrappers"]) == {"frontdesk"}
    hermes_role = root / ".agentlab" / "cli_entrypoints" / "wrappers" / "workers" / "hermes-role-agentlab"
    assert not hermes_role.exists()


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
