"""Static security audit and real one-shot sandbox helpers for capabilities."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
import hashlib
import platform
import re
import subprocess
import tarfile
import tempfile

from agent_runtime.capability_vault import CapabilityPackage, CapabilityVaultError

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
CODE_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".sh",
    ".bash",
    ".zsh",
    ".rb",
    ".go",
    ".rs",
    ".java",
}
NETWORK_PATTERNS = (
    re.compile(r"\b(?:import|from)\s+requests\b"),
    re.compile(r"\brequests\."),
    re.compile(r"\burllib\."),
    re.compile(r"\bsocket\."),
    re.compile(r"\bcurl\b"),
    re.compile(r"\bfetch\s*\("),
)
SECRET_READ_PATTERNS = (
    re.compile(r"(?:^|[/\\])\.ssh(?:[/\\])"),
    re.compile(r"(?:^|[/\\])\.aws(?:[/\\])"),
    re.compile(r"(?:^|[/\\])\.config[/\\]gcloud"),
    re.compile(r"\bos\.environ\b"),
    re.compile(r"\bkeychain\b", re.IGNORECASE),
)
OBFUSCATION_PATTERNS = (
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bmarshal\.loads\s*\("),
    re.compile(r"\bbase64\.b64decode\s*\("),
)
PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all )?previous instructions", re.IGNORECASE),
    re.compile(r"reveal (?:the )?system prompt", re.IGNORECASE),
)
INSTALL_SCRIPT_NAMES = {
    "install.sh",
    "postinstall.sh",
    "setup.py",
}


def _safe_member_path(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".."} for part in path.parts):
        return None
    return path


def _scan_text(path: PurePosixPath, text: str) -> set[str]:
    findings: set[str] = set()
    if any(pattern.search(text) for pattern in NETWORK_PATTERNS):
        findings.add("network_access_pattern")
    if any(pattern.search(text) for pattern in SECRET_READ_PATTERNS):
        findings.add("secret_read_pattern")
    if any(pattern.search(text) for pattern in OBFUSCATION_PATTERNS):
        findings.add("obfuscation_pattern")
    if any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS):
        findings.add("prompt_injection_pattern")
    if path.name.casefold() in INSTALL_SCRIPT_NAMES:
        findings.add("install_script_present")
    return findings


def audit_capability_archive(
    manifest: Mapping[str, Any],
    *,
    source_archive: Path,
) -> dict[str, Any]:
    """Audit an immutable tar archive without executing or extracting it."""

    try:
        package = CapabilityPackage.from_mapping(manifest)
    except CapabilityVaultError as exc:
        return {
            "schema_version": "capability-static-audit/v1",
            "status": "blocked",
            "blocking_findings": [f"invalid_manifest:{exc}"],
            "sbom": {"files": []},
        }
    archive = Path(source_archive)
    blocking: set[str] = set()
    observations: set[str] = set()
    files: list[dict[str, Any]] = []
    contains_code = False
    if archive.is_symlink() or not archive.is_file():
        blocking.add("source_archive_not_regular_file")
        actual_digest = None
    else:
        actual_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual_digest != package.source_digest:
            blocking.add("source_digest_mismatch")
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            blocking.add("archive_size_limit_exceeded")
    if not blocking:
        try:
            with tarfile.open(archive, mode="r:*") as handle:
                total_size = 0
                for member in handle:
                    member_path = _safe_member_path(member.name)
                    if member_path is None:
                        blocking.add("archive_path_traversal")
                        continue
                    if member.issym() or member.islnk():
                        blocking.add("archive_symlink_or_hardlink")
                        continue
                    if member.isdir():
                        continue
                    if not member.isfile():
                        blocking.add("archive_special_file")
                        continue
                    total_size += member.size
                    if member.size > MAX_FILE_BYTES or total_size > MAX_ARCHIVE_BYTES:
                        blocking.add("archive_size_limit_exceeded")
                        continue
                    extracted = handle.extractfile(member)
                    if extracted is None:
                        blocking.add("archive_member_unreadable")
                        continue
                    body = extracted.read(MAX_FILE_BYTES + 1)
                    if len(body) != member.size:
                        blocking.add("archive_member_size_mismatch")
                        continue
                    suffix = member_path.suffix.casefold()
                    contains_code = contains_code or suffix in CODE_SUFFIXES
                    files.append(
                        {
                            "path": member_path.as_posix(),
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "bytes": len(body),
                            "kind": "code" if suffix in CODE_SUFFIXES else "resource",
                        }
                    )
                    if len(body) <= 1024 * 1024:
                        text = body.decode("utf-8", errors="replace")
                        observations.update(_scan_text(member_path, text))
        except (OSError, tarfile.TarError):
            blocking.add("archive_unreadable")
    network_mode = str(package.document["network_boundary"].get("mode") or "none")
    if "network_access_pattern" in observations and network_mode == "none":
        blocking.add("undeclared_network_access")
    credentials = package.document["permissions"].get("credentials") or []
    if "secret_read_pattern" in observations and not credentials:
        blocking.add("secret_read_pattern")
    if "obfuscation_pattern" in observations:
        blocking.add("obfuscation_pattern")
    if "prompt_injection_pattern" in observations:
        blocking.add("prompt_injection_pattern")
    if (
        "install_script_present" in observations
        and package.document["installation"].get("method") != "script"
    ):
        blocking.add("undeclared_install_script")
    files.sort(key=lambda item: item["path"])
    return {
        "schema_version": "capability-static-audit/v1",
        "status": "pass" if not blocking else "blocked",
        "package_id": package.package_id,
        "version": package.version,
        "source_digest": actual_digest,
        "blocking_findings": sorted(blocking),
        "observations": sorted(observations),
        "sbom": {
            "format": "agentlab-file-sbom/v1",
            "files": files,
            "file_count": len(files),
        },
        "contains_code": contains_code,
        "requires_user_approval": bool(
            package.requires_user_approval or contains_code
        ),
        "execution_performed": False,
    }


def _sandbox_quote(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')


def build_sandbox_command(
    command: list[str],
    *,
    sandbox_root: Path,
    platform_name: str | None = None,
) -> tuple[list[str], str]:
    """Build a fail-closed OS sandbox command; never emulate isolation."""

    if not command or any("\x00" in item for item in command):
        raise ValueError("sandbox command is invalid")
    selected_platform = platform_name or platform.system().casefold()
    if selected_platform == "darwin":
        root = _sandbox_quote(sandbox_root)
        profile = "\n".join(
            (
                "(version 1)",
                "(deny default)",
                "(allow process*)",
                "(allow signal)",
                "(allow sysctl-read)",
                "(allow file-read-metadata)",
                '(allow file-read* (subpath "/System"))',
                '(allow file-read* (subpath "/usr"))',
                '(allow file-read* (subpath "/bin"))',
                '(allow file-read* (subpath "/Library"))',
                '(allow file-read* (literal "/dev/null"))',
                '(allow file-read* (literal "/dev/urandom"))',
                '(allow file-write* (literal "/dev/null"))',
                f'(allow file-read* (subpath "{root}"))',
                f'(allow file-write* (subpath "{root}"))',
                "(deny network*)",
            )
        )
        return ["/usr/bin/sandbox-exec", "-p", profile, *command], profile
    raise RuntimeError(
        f"no verified sandbox adapter for platform: {selected_platform}"
    )


AuditionRunner = Callable[..., subprocess.CompletedProcess[str]]


def _extract_audited_archive(source_archive: Path, target_root: Path) -> None:
    with tarfile.open(source_archive, mode="r:*") as handle:
        for member in handle:
            member_path = _safe_member_path(member.name)
            if member_path is None or member.issym() or member.islnk():
                raise RuntimeError("audited archive changed before extraction")
            target = target_root / Path(member_path.as_posix())
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise RuntimeError("audited archive contains a special file")
            extracted = handle.extractfile(member)
            if extracted is None:
                raise RuntimeError("audited archive member is unreadable")
            body = extracted.read(MAX_FILE_BYTES + 1)
            if len(body) != member.size:
                raise RuntimeError("audited archive member size changed")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)


def audition_capability_archive(
    manifest: Mapping[str, Any],
    *,
    source_archive: Path,
    runner: AuditionRunner | None = None,
    platform_name: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Run one declared health probe in an ephemeral network-denied OS sandbox."""

    audit = audit_capability_archive(manifest, source_archive=source_archive)
    if audit.get("status") != "pass":
        return {
            "schema_version": "capability-audition/v1",
            "status": "blocked",
            "blocking_findings": ["static_audit_not_passed"],
            "static_audit": audit,
            "execution_performed": False,
        }
    package = CapabilityPackage.from_mapping(manifest)
    raw_command = package.document["health_probe"].get("command")
    if (
        not isinstance(raw_command, list)
        or not raw_command
        or any(not isinstance(item, str) or not item for item in raw_command)
    ):
        return {
            "schema_version": "capability-audition/v1",
            "status": "blocked",
            "blocking_findings": ["declared_health_probe_command_required"],
            "static_audit": audit,
            "execution_performed": False,
        }
    execute = runner or subprocess.run
    try:
        with tempfile.TemporaryDirectory(prefix="agentlab_capability_audition_") as raw:
            sandbox_root = Path(raw).resolve()
            _extract_audited_archive(Path(source_archive), sandbox_root)
            (sandbox_root / "home").mkdir()
            (sandbox_root / "tmp").mkdir()
            sandbox_command, profile = build_sandbox_command(
                list(raw_command),
                sandbox_root=sandbox_root,
                platform_name=platform_name,
            )
            environment = {
                "HOME": str(sandbox_root / "home"),
                "LANG": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "TMPDIR": str(sandbox_root / "tmp"),
            }
            result = execute(
                sandbox_command,
                cwd=sandbox_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            "schema_version": "capability-audition/v1",
            "status": "blocked",
            "package_id": package.package_id,
            "blocking_findings": [f"sandbox_execution_failed:{type(exc).__name__}"],
            "static_audit": audit,
            "execution_performed": False,
        }
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return {
        "schema_version": "capability-audition/v1",
        "status": "pass" if result.returncode == 0 else "blocked",
        "package_id": package.package_id,
        "version": package.version,
        "source_digest": package.source_digest,
        "sandbox_adapter": (
            "macos_sandbox_exec"
            if (platform_name or platform.system().casefold()) == "darwin"
            else "unsupported"
        ),
        "sandbox_profile_sha256": hashlib.sha256(
            profile.encode("utf-8")
        ).hexdigest(),
        "network_allowed": False,
        "private_home_mounted": False,
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        "execution_performed": True,
        "requires_user_approval": audit["requires_user_approval"],
        "blocking_findings": (
            [] if result.returncode == 0 else ["health_probe_failed"]
        ),
    }
