from __future__ import annotations

from pathlib import Path
import hashlib
import os
import subprocess

import pytest
import yaml

from agent_runtime.capability_vault import (
    CapabilityPackage,
    CapabilityVault,
    CapabilityVaultError,
)


def _manifest(source_digest: str) -> dict:
    return {
        "schema_version": "capability-package/v1",
        "package_id": "fixture.readonly-search",
        "package_type": "skill",
        "version": "1.2.3",
        "source": {
            "uri": "https://example.invalid/fixture.git",
            "revision": "a" * 40,
            "digest": source_digest,
            "license": "Apache-2.0",
        },
        "capability_tags": ["read_only_repo_search"],
        "compatible_environments": ["local_runtime"],
        "inputs": {"query": "string"},
        "outputs": {"matches": "list"},
        "dependencies": [],
        "permissions": {
            "filesystem_read": "project_scoped",
            "filesystem_write": "none",
            "shell": "none",
            "credentials": [],
        },
        "network_boundary": {"mode": "none", "destinations": []},
        "data_boundary": {"reads_private_data": False, "external_transfer": False},
        "installation": {"method": "copy", "entrypoint": "SKILL.md"},
        "health_probe": {"command": None, "expected": "manifest_valid"},
        "tests": [{"fixture": "readonly-search", "domain": "code"}],
        "risks": [],
        "rollback_version": "1.2.2",
        "project_allowlist": ["AgentLab"],
    }


def test_capability_package_requires_complete_supply_chain_contract() -> None:
    manifest = _manifest("b" * 64)

    package = CapabilityPackage.from_mapping(manifest)

    assert package.package_type == "skill"
    assert package.requires_user_approval is False
    del manifest["source"]["license"]
    with pytest.raises(CapabilityVaultError, match="source.license"):
        CapabilityPackage.from_mapping(manifest)


def test_local_vault_registers_hash_bound_object_and_private_git_metadata(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"immutable capability bundle")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    vault_root = tmp_path / "private-vault"
    (vault_root / "metadata" / ".git").mkdir(parents=True)
    vault = CapabilityVault.from_config(
        {
            "driver": "local_filesystem",
            "root": str(vault_root),
        }
    )

    receipt = vault.register(_manifest(digest), source_archive=bundle)

    assert receipt["status"] == "discovered"
    assert receipt["source_digest"] == digest
    assert "root" not in receipt
    assert (
        vault_root / "objects" / "sha256" / digest[:2] / digest
    ).read_bytes() == bundle.read_bytes()
    metadata = yaml.safe_load(
        (
            vault_root
            / "metadata"
            / "packages"
            / "fixture.readonly-search"
            / "1.2.3.yml"
        ).read_text(encoding="utf-8")
    )
    assert metadata["lifecycle"]["status"] == "discovered"
    assert metadata["source"]["digest"] == digest
    assert vault.doctor()["status"] == "pass"


def test_vault_rejects_source_substitution_before_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"substituted")
    vault_root = tmp_path / "private-vault"
    (vault_root / "metadata" / ".git").mkdir(parents=True)
    vault = CapabilityVault.from_config(
        {"driver": "local_filesystem", "root": str(vault_root)}
    )

    with pytest.raises(CapabilityVaultError, match="source digest mismatch"):
        vault.register(_manifest("c" * 64), source_archive=bundle)

    assert not (vault_root / "objects").exists()


def test_ssh_vault_adapter_only_issues_storage_commands(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"remote object")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        commands.append(command)

    vault = CapabilityVault.from_config(
        {
            "driver": "ssh_filesystem",
            "ssh_alias": "private-vault",
            "root": "/srv/private/capability-vault",
        },
        command_runner=runner,
    )

    receipt = vault.register(_manifest(digest), source_archive=bundle)

    assert receipt["driver"] == "ssh_filesystem"
    assert any(command[0] == "rsync" for command in commands)
    assert all(
        not any(token in {"python", "python3", "bash", "sh", "zsh"} for token in command)
        for command in commands
    )


def test_capability_vault_cli_exposes_register_and_doctor() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [str(root / "agentlab.sh"), "capability-vault", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NO_COLOR": "1", "COLUMNS": "180"},
    )

    assert result.returncode == 0, result.stderr
    assert "register" in result.stdout
    assert "doctor" in result.stdout
