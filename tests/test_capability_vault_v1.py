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
    metadata_root = vault_root / "metadata"
    metadata_root.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", str(metadata_root)],
        check=True,
    )
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
    assert subprocess.run(
        ["git", "-C", str(metadata_root), "rev-list", "--count", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "1"
    assert vault.register(_manifest(digest), source_archive=bundle)["status"] == (
        "discovered"
    )
    changed = _manifest(digest)
    changed["capability_tags"] = ["different-capability"]
    with pytest.raises(
        CapabilityVaultError,
        match="immutable capability metadata collision",
    ):
        vault.register(changed, source_archive=bundle)


def test_vault_rejects_source_substitution_before_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"substituted")
    vault_root = tmp_path / "private-vault"
    metadata_root = vault_root / "metadata"
    metadata_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(metadata_root)], check=True)
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

    def runner(command: list[str]) -> subprocess.CompletedProcess[str] | None:
        commands.append(command)
        if (
            command[:3] == ["ssh", "private-vault", "sha256sum"]
            and "/objects/" in command[-1]
        ):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"{digest}  {command[-1]}\n",
                stderr="",
            )
        return None

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
    object_copy = next(command for command in commands if command[0] == "rsync")
    assert "--ignore-existing" in object_copy
    assert any(
        command[:4] == ["ssh", "private-vault", "git", "-C"]
        and "commit" in command
        for command in commands
    )
    assert all(
        not any(token in {"python", "python3", "bash", "sh", "zsh"} for token in command)
        for command in commands
    )


def test_ssh_vault_rejects_invalid_git_and_metadata_collision(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"remote object")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

    def invalid_git(
        command: list[str],
    ) -> subprocess.CompletedProcess[str] | None:
        if "rev-parse" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="false\n",
                stderr="",
            )
        return None

    invalid = CapabilityVault.from_config(
        {
            "driver": "ssh_filesystem",
            "ssh_alias": "private-vault",
            "root": "/srv/private/capability-vault",
        },
        command_runner=invalid_git,
    )
    assert invalid.doctor()["status"] == "blocked"

    def collision(
        command: list[str],
    ) -> subprocess.CompletedProcess[str] | None:
        if "rev-parse" in command:
            stdout = "true\n"
        elif command[:3] == ["ssh", "private-vault", "sha256sum"]:
            stdout = (
                f"{digest}\n"
                if "/objects/" in command[-1]
                else f"{'f' * 64}\n"
            )
        else:
            return None
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=stdout,
            stderr="",
        )

    colliding = CapabilityVault.from_config(
        {
            "driver": "ssh_filesystem",
            "ssh_alias": "private-vault",
            "root": "/srv/private/capability-vault",
        },
        command_runner=collision,
    )
    with pytest.raises(
        CapabilityVaultError,
        match="immutable capability metadata collision",
    ):
        colliding.register(_manifest(digest), source_archive=bundle)


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


def test_vault_records_private_radar_evidence_by_digest(tmp_path: Path) -> None:
    vault_root = tmp_path / "private-vault"
    metadata_root = vault_root / "metadata"
    metadata_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(metadata_root)], check=True)
    vault = CapabilityVault.from_config(
        {"driver": "local_filesystem", "root": str(vault_root)}
    )

    receipt = vault.record_evidence(
        evidence_kind="radar-narrative",
        payload={
            "schema_version": "capability-discovery-result/v1",
            "status": "pass",
            "candidates": [],
        },
    )

    assert receipt["status"] == "recorded"
    assert receipt["private_locations_redacted"] is True
    evidence = list(
        (
            vault_root / "metadata" / "evidence" / "radar-narrative"
        ).glob("*.yml")
    )
    assert len(evidence) == 1
    document = yaml.safe_load(evidence[0].read_text(encoding="utf-8"))
    assert document["payload"]["candidates"] == []


def test_radar_timer_is_weekly_persistent_and_private() -> None:
    root = Path(__file__).resolve().parents[1]
    timer = (
        root / "deploy" / "systemd" / "agentlab-capability-radar.timer"
    ).read_text(encoding="utf-8")
    service = (
        root / "deploy" / "systemd" / "agentlab-capability-radar.service"
    ).read_text(encoding="utf-8")
    script = (root / "scripts" / "run_capability_radar.sh").read_text(
        encoding="utf-8"
    )

    assert "OnCalendar=weekly" in timer
    assert "Persistent=true" in timer
    assert "--record-vault" in script
    assert ".agentlab_runtime/capability_radar" in script
    assert "User=root" not in service
    assert "10.147." not in service + script
