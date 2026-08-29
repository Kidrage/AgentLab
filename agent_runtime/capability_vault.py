"""Private, content-addressed capability package storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
import hashlib
import re
import shutil
import subprocess
import tempfile

import yaml

from atomic_io import atomic_write_text

PACKAGE_TYPES = {
    "skill",
    "mcp_server",
    "plugin_bundle",
    "agent_adapter",
    "deterministic_tool",
    "classifier",
    "research_corpus",
}
LIFECYCLE_STATUSES = {
    "discovered",
    "quarantined",
    "statically_audited",
    "auditioned",
    "supervisor_reviewed",
    "canary",
    "active",
    "deprecated",
    "retired",
}
_PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SSH_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CapabilityVaultError(ValueError):
    """Raised when package integrity or private vault policy is violated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CapabilityVaultError(f"{label} must be a mapping")
    return dict(value)


def _require_fields(value: Mapping[str, Any], fields: tuple[str, ...], label: str) -> None:
    for field in fields:
        if field not in value or value[field] in (None, ""):
            raise CapabilityVaultError(f"{label}.{field} is required")


@dataclass(frozen=True, slots=True)
class CapabilityPackage:
    """Validated capability-package/v1 document."""

    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CapabilityPackage":
        document = dict(value)
        _require_fields(
            document,
            (
                "schema_version",
                "package_id",
                "package_type",
                "version",
                "source",
                "capability_tags",
                "compatible_environments",
                "inputs",
                "outputs",
                "dependencies",
                "permissions",
                "network_boundary",
                "data_boundary",
                "installation",
                "health_probe",
                "tests",
                "rollback_version",
                "project_allowlist",
            ),
            "package",
        )
        if document["schema_version"] != "capability-package/v1":
            raise CapabilityVaultError("package.schema_version is unsupported")
        package_id = str(document["package_id"])
        if not _PACKAGE_ID.fullmatch(package_id):
            raise CapabilityVaultError("package.package_id is invalid")
        if document["package_type"] not in PACKAGE_TYPES:
            raise CapabilityVaultError("package.package_type is invalid")
        if not _VERSION.fullmatch(str(document["version"])):
            raise CapabilityVaultError("package.version is invalid")
        source = _require_mapping(document["source"], "source")
        _require_fields(
            source,
            ("uri", "revision", "digest", "license"),
            "source",
        )
        if not _SHA256.fullmatch(str(source["digest"])):
            raise CapabilityVaultError("source.digest must be a SHA-256 digest")
        for field in ("capability_tags", "compatible_environments", "tests"):
            if not isinstance(document[field], list) or not document[field]:
                raise CapabilityVaultError(f"package.{field} must be a non-empty list")
        for field in ("dependencies", "risks", "project_allowlist"):
            if not isinstance(document.get(field), list):
                raise CapabilityVaultError(f"package.{field} must be a list")
        for field in (
            "inputs",
            "outputs",
            "permissions",
            "network_boundary",
            "data_boundary",
            "installation",
            "health_probe",
        ):
            _require_mapping(document[field], f"package.{field}")
        return cls(document=document)

    @property
    def package_id(self) -> str:
        return str(self.document["package_id"])

    @property
    def package_type(self) -> str:
        return str(self.document["package_type"])

    @property
    def version(self) -> str:
        return str(self.document["version"])

    @property
    def source_digest(self) -> str:
        return str(self.document["source"]["digest"])

    @property
    def requires_user_approval(self) -> bool:
        permissions = self.document["permissions"]
        network = self.document["network_boundary"]
        data = self.document["data_boundary"]
        installation = self.document["installation"]
        return bool(
            permissions.get("filesystem_write") not in (None, "none")
            or permissions.get("shell") not in (None, "none")
            or permissions.get("credentials")
            or network.get("mode") not in (None, "none")
            or data.get("external_transfer") is True
            or installation.get("executes_code") is True
        )


CommandRunner = Callable[
    [list[str]],
    subprocess.CompletedProcess[str] | None,
]


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


class _LocalFilesystemAdapter:
    driver_name = "local_filesystem"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def doctor(self) -> list[str]:
        metadata_root = self.root / "metadata"
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(metadata_root),
                    "rev-parse",
                    "--is-inside-work-tree",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            return ["metadata_not_private_git"]
        return (
            []
            if result.stdout.strip() == "true"
            else ["metadata_not_private_git"]
        )

    def put_object(self, digest: str, source: Path) -> None:
        target = self.root / "objects" / "sha256" / digest[:2] / digest
        if target.exists():
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise CapabilityVaultError("content-addressed object collision")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    def put_metadata(
        self,
        relative: PurePosixPath,
        content: str,
        *,
        immutable: bool = False,
    ) -> None:
        metadata_root = (self.root / "metadata").resolve()
        target = (metadata_root / Path(relative.as_posix())).resolve()
        try:
            target.relative_to(metadata_root)
        except ValueError as exc:
            raise CapabilityVaultError("metadata path escapes private vault") from exc
        if immutable and target.exists():
            if (
                not target.is_file()
                or target.read_text(encoding="utf-8") != content
            ):
                raise CapabilityVaultError("immutable capability metadata collision")
            return
        atomic_write_text(target, content)
        relative_path = target.relative_to(metadata_root).as_posix()
        subprocess.run(
            ["git", "-C", str(metadata_root), "add", "--", relative_path],
            check=True,
            capture_output=True,
            text=True,
        )
        changed = subprocess.run(
            [
                "git",
                "-C",
                str(metadata_root),
                "diff",
                "--cached",
                "--quiet",
                "--",
                relative_path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if changed.returncode == 1:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(metadata_root),
                    "-c",
                    "user.name=AgentLab-Vault",
                    "-c",
                    "user.email=agentlab-vault@localhost",
                    "commit",
                    "-m",
                    "vault-metadata-update",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        elif changed.returncode != 0:
            raise CapabilityVaultError("private metadata Git diff failed")


class _SshFilesystemAdapter:
    driver_name = "ssh_filesystem"

    def __init__(
        self,
        *,
        ssh_alias: str,
        root: str,
        command_runner: CommandRunner,
    ) -> None:
        if not _SSH_ALIAS.fullmatch(ssh_alias):
            raise CapabilityVaultError("ssh_alias is invalid")
        posix_root = PurePosixPath(root)
        if not posix_root.is_absolute() or any(
            char.isspace() for char in posix_root.as_posix()
        ):
            raise CapabilityVaultError("ssh vault root must be an absolute path without spaces")
        self.ssh_alias = ssh_alias
        self.root = posix_root
        self.run = command_runner

    def doctor(self) -> list[str]:
        try:
            result = self.run(
                [
                    "ssh",
                    self.ssh_alias,
                    "git",
                    "-C",
                    (self.root / "metadata").as_posix(),
                    "rev-parse",
                    "--is-inside-work-tree",
                ]
            )
        except (OSError, subprocess.SubprocessError):
            return ["metadata_not_private_git_or_unreachable"]
        if (
            isinstance(result, subprocess.CompletedProcess)
            and str(result.stdout or "").strip() != "true"
        ):
            return ["metadata_not_private_git_or_unreachable"]
        return []

    def _put_file(
        self,
        source: Path,
        target: PurePosixPath,
        *,
        immutable: bool,
    ) -> subprocess.CompletedProcess[str] | None:
        self.run(
            [
                "ssh",
                self.ssh_alias,
                "mkdir",
                "-p",
                target.parent.as_posix(),
            ]
        )
        command = ["rsync", "-a"]
        if immutable:
            command.append("--ignore-existing")
        command.extend(
            [
                str(source),
                f"{self.ssh_alias}:{target.as_posix()}",
            ]
        )
        return self.run(command)

    def put_object(self, digest: str, source: Path) -> None:
        target = self.root / "objects" / "sha256" / digest[:2] / digest
        self._put_file(
            source,
            target,
            immutable=True,
        )
        result = self.run(
            ["ssh", self.ssh_alias, "sha256sum", target.as_posix()]
        )
        if (
            isinstance(result, subprocess.CompletedProcess)
            and str(result.stdout or "").split(maxsplit=1)[0] != digest
        ):
            raise CapabilityVaultError("remote content-addressed object collision")

    def put_metadata(
        self,
        relative: PurePosixPath,
        content: str,
        *,
        immutable: bool = False,
    ) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".yml",
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            self._put_file(
                Path(temporary.name),
                self.root / "metadata" / relative,
                immutable=immutable,
            )
        metadata_root = self.root / "metadata"
        target = metadata_root / relative
        if immutable:
            result = self.run(
                ["ssh", self.ssh_alias, "sha256sum", target.as_posix()]
            )
            expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if (
                isinstance(result, subprocess.CompletedProcess)
                and str(result.stdout or "").split(maxsplit=1)[0] != expected
            ):
                raise CapabilityVaultError(
                    "immutable capability metadata collision"
                )
        self.run(
            [
                "ssh",
                self.ssh_alias,
                "git",
                "-C",
                metadata_root.as_posix(),
                "add",
                "--",
                relative.as_posix(),
            ]
        )
        self.run(
            [
                "ssh",
                self.ssh_alias,
                "git",
                "-C",
                metadata_root.as_posix(),
                "-c",
                "user.name=AgentLab-Vault",
                "-c",
                "user.email=agentlab-vault@localhost",
                "commit",
                "--allow-empty",
                "-m",
                "vault-metadata-update",
            ]
        )


class CapabilityVault:
    """Register immutable packages through one private storage interface."""

    def __init__(self, adapter: _LocalFilesystemAdapter | _SshFilesystemAdapter) -> None:
        self._adapter = adapter

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        command_runner: CommandRunner | None = None,
    ) -> "CapabilityVault":
        driver = str(config.get("driver") or "")
        root = config.get("root")
        if not root:
            raise CapabilityVaultError("capability_vault.root is required")
        if driver == "local_filesystem":
            return cls(_LocalFilesystemAdapter(Path(str(root))))
        if driver == "ssh_filesystem":
            return cls(
                _SshFilesystemAdapter(
                    ssh_alias=str(config.get("ssh_alias") or ""),
                    root=str(root),
                    command_runner=command_runner or _run_command,
                )
            )
        raise CapabilityVaultError("capability_vault.driver is unsupported")

    def doctor(self) -> dict[str, Any]:
        issues = self._adapter.doctor()
        return {
            "schema_version": "capability-vault-doctor/v1",
            "status": "pass" if not issues else "blocked",
            "driver": self._adapter.driver_name,
            "issues": issues,
            "private_locations_redacted": True,
        }

    def register(
        self,
        manifest: Mapping[str, Any],
        *,
        source_archive: Path,
    ) -> dict[str, Any]:
        package = CapabilityPackage.from_mapping(manifest)
        source = Path(source_archive)
        if source.is_symlink() or not source.is_file():
            raise CapabilityVaultError("source archive must be a regular non-symlink file")
        actual_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_digest != package.source_digest:
            raise CapabilityVaultError("source digest mismatch")
        doctor = self.doctor()
        if doctor["status"] != "pass":
            raise CapabilityVaultError("private vault doctor is blocked")
        metadata = {
            **package.document,
            "lifecycle": {
                "status": "discovered",
                "allowed_transitions": sorted(
                    LIFECYCLE_STATUSES - {"discovered"}
                ),
            },
            "object": {
                "algorithm": "sha256",
                "digest": actual_digest,
                "relative_path": (
                    f"objects/sha256/{actual_digest[:2]}/{actual_digest}"
                ),
            },
            "approval": {
                "user_approval_required": package.requires_user_approval,
                "status": (
                    "pending"
                    if package.requires_user_approval
                    else "not_required_at_discovery"
                ),
            },
        }
        metadata_body = yaml.safe_dump(
            metadata,
            sort_keys=False,
            allow_unicode=True,
        )
        self._adapter.put_object(actual_digest, source)
        self._adapter.put_metadata(
            PurePosixPath("packages")
            / package.package_id
            / f"{package.version}.yml",
            metadata_body,
            immutable=True,
        )
        return {
            "schema_version": "capability-vault-registration/v1",
            "status": "discovered",
            "package_id": package.package_id,
            "version": package.version,
            "package_type": package.package_type,
            "source_digest": actual_digest,
            "driver": self._adapter.driver_name,
            "user_approval_required": package.requires_user_approval,
            "private_locations_redacted": True,
        }

    def record_lifecycle_decision(
        self,
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one approved promotion/rollback decision and update its pointer."""

        if decision.get("status") != "approved":
            raise CapabilityVaultError("only approved lifecycle decisions may be recorded")
        package_id = str(decision.get("package_id") or "")
        if not _PACKAGE_ID.fullmatch(package_id):
            raise CapabilityVaultError("lifecycle decision package_id is invalid")
        schema = str(decision.get("schema_version") or "")
        if schema not in {
            "capability-promotion-decision/v1",
            "capability-rollback-decision/v1",
        }:
            raise CapabilityVaultError("unsupported lifecycle decision schema")
        decided_at = str(decision.get("decided_at") or _utc_now())
        serialized = yaml.safe_dump(
            dict(decision),
            sort_keys=False,
            allow_unicode=True,
        )
        event_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        event_name = re.sub(r"[^0-9A-Za-z._-]", "_", decided_at)
        relative = (
            PurePosixPath("lifecycle_events")
            / package_id
            / f"{event_name}-{event_digest[:12]}.yml"
        )
        self._adapter.put_metadata(relative, serialized)
        pointer = {
            "schema_version": "capability-lifecycle-pointer/v1",
            "package_id": package_id,
            "decision_schema": schema,
            "decision_sha256": event_digest,
            "decision_event": relative.as_posix(),
            "updated_at": decided_at,
        }
        if schema == "capability-promotion-decision/v1":
            pointer["status"] = decision.get("transition", {}).get("to")
            pointer["version"] = decision.get("version")
            pointer["source_digest"] = decision.get("source_digest")
        else:
            pointer["status"] = decision.get("rollback", {}).get(
                "resulting_status"
            )
            pointer["version"] = decision.get("rollback", {}).get("to_version")
            pointer["source_digest"] = None
        self._adapter.put_metadata(
            PurePosixPath("lifecycle_pointers") / f"{package_id}.yml",
            yaml.safe_dump(pointer, sort_keys=False, allow_unicode=True),
        )
        return {
            "schema_version": "capability-lifecycle-record/v1",
            "status": "recorded",
            "package_id": package_id,
            "decision_sha256": event_digest,
            "private_locations_redacted": True,
        }

    def record_evidence(
        self,
        *,
        evidence_kind: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Store one private evidence document without exposing its location."""

        if not _PACKAGE_ID.fullmatch(evidence_kind):
            raise CapabilityVaultError("evidence_kind is invalid")
        if not isinstance(payload, Mapping):
            raise CapabilityVaultError("evidence payload must be a mapping")
        recorded_at = _utc_now()
        document = {
            "schema_version": "capability-vault-evidence/v1",
            "evidence_kind": evidence_kind,
            "recorded_at": recorded_at,
            "payload": dict(payload),
        }
        serialized = yaml.safe_dump(
            document,
            sort_keys=False,
            allow_unicode=True,
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        event_name = re.sub(r"[^0-9A-Za-z._-]", "_", recorded_at)
        self._adapter.put_metadata(
            PurePosixPath("evidence")
            / evidence_kind
            / f"{event_name}-{digest[:12]}.yml",
            serialized,
        )
        return {
            "schema_version": "capability-vault-evidence-record/v1",
            "status": "recorded",
            "evidence_kind": evidence_kind,
            "evidence_sha256": digest,
            "private_locations_redacted": True,
        }


def load_private_capability_vault(
    agentlab_root: Path,
    *,
    command_runner: CommandRunner | None = None,
) -> CapabilityVault:
    """Load the gitignored private topology without exposing its locations."""

    root = Path(agentlab_root).resolve()
    config_path = root / "config" / "local_private_topology.yml"
    if not config_path.is_file():
        raise CapabilityVaultError(
            "config/local_private_topology.yml is required and must remain untracked"
        )
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            "config/local_private_topology.yml",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if tracked.returncode == 0:
        raise CapabilityVaultError("private topology must not be tracked by Git")
    try:
        value = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CapabilityVaultError("private topology is unreadable") from exc
    if not isinstance(value, Mapping):
        raise CapabilityVaultError("private topology must be a mapping")
    config = _require_mapping(value.get("capability_vault"), "capability_vault")
    if config.get("driver") == "local_filesystem":
        private_root = Path(str(config.get("root") or ""))
        if not private_root.is_absolute():
            config["root"] = str((root / private_root).resolve())
    return CapabilityVault.from_config(
        config,
        command_runner=command_runner,
    )
