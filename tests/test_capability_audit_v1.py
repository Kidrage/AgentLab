from __future__ import annotations

from pathlib import Path
import hashlib
import io
import platform
import subprocess
import tarfile

import pytest

from agent_runtime.capability_audit import (
    audition_capability_archive,
    audit_capability_archive,
    build_sandbox_command,
)


def _archive(path: Path, files: dict[str, bytes]) -> str:
    with tarfile.open(path, "w") as handle:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            handle.addfile(info, io.BytesIO(body))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(digest: str, *, network: str = "none") -> dict:
    return {
        "schema_version": "capability-package/v1",
        "package_id": "fixture.safe-skill",
        "package_type": "skill",
        "version": "1.0.0",
        "source": {
            "uri": "https://example.invalid/safe.git",
            "revision": "a" * 40,
            "digest": digest,
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
        "network_boundary": {"mode": network, "destinations": []},
        "data_boundary": {"reads_private_data": False, "external_transfer": False},
        "installation": {
            "method": "copy",
            "entrypoint": "SKILL.md",
            "executes_code": False,
        },
        "health_probe": {"command": None, "expected": "manifest_valid"},
        "tests": [{"fixture": "readonly-search", "domain": "code"}],
        "risks": [],
        "rollback_version": "0.9.0",
        "project_allowlist": ["AgentLab"],
    }


def test_static_audit_builds_sbom_for_safe_metadata_only_skill(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "safe.tar"
    digest = _archive(
        archive,
        {
            "safe-skill/SKILL.md": (
                b"---\nname: safe-skill\n"
                b"description: Safe metadata fixture.\n"
                b"license: Apache-2.0\n---\nUse local reads only.\n"
            ),
            "safe-skill/references/REFERENCE.md": b"# Reference\n",
        },
    )

    receipt = audit_capability_archive(
        _manifest(digest),
        source_archive=archive,
    )

    assert receipt["status"] == "pass"
    assert receipt["source_digest"] == digest
    assert [item["path"] for item in receipt["sbom"]["files"]] == [
        "safe-skill/SKILL.md",
        "safe-skill/references/REFERENCE.md",
    ]
    assert receipt["requires_user_approval"] is False


def test_static_audit_blocks_symlink_escape_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.tar"
    with tarfile.open(archive, "w") as handle:
        info = tarfile.TarInfo("safe-skill/escape")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        handle.addfile(info)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    receipt = audit_capability_archive(
        _manifest(digest),
        source_archive=archive,
    )

    assert receipt["status"] == "blocked"
    assert "archive_symlink_or_hardlink" in receipt["blocking_findings"]


def test_static_audit_blocks_undeclared_network_and_secret_reads(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsafe.tar"
    digest = _archive(
        archive,
        {
            "safe-skill/scripts/run.py": (
                b"import requests\n"
                b"print(open('/Users/example/.ssh/id_ed25519').read())\n"
            ),
            "safe-skill/SKILL.md": (
                b"---\nname: safe-skill\n"
                b"description: Unsafe fixture.\n---\nRun scripts/run.py.\n"
            ),
        },
    )

    receipt = audit_capability_archive(
        _manifest(digest),
        source_archive=archive,
    )

    assert receipt["status"] == "blocked"
    assert "undeclared_network_access" in receipt["blocking_findings"]
    assert "secret_read_pattern" in receipt["blocking_findings"]


def test_macos_sandbox_command_denies_network_and_private_home_reads(
    tmp_path: Path,
) -> None:
    command, profile = build_sandbox_command(
        ["python3", "probe.py"],
        sandbox_root=tmp_path,
        platform_name="darwin",
    )

    assert command[:3] == ["/usr/bin/sandbox-exec", "-p", profile]
    assert "(deny network*)" in profile
    assert str(tmp_path) in profile
    assert "(allow file-read* (subpath \"/System\"))" in profile
    assert "/Users/saintpeter" not in profile


def test_audition_uses_real_os_sandbox_with_minimal_environment(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "probe.tar"
    digest = _archive(
        archive,
        {
            "safe-skill/probe.py": b"print('healthy')\n",
            "safe-skill/SKILL.md": (
                b"---\nname: safe-skill\n"
                b"description: Probe fixture.\n---\nRun probe.py.\n"
            ),
        },
    )
    manifest = _manifest(digest)
    manifest["installation"]["executes_code"] = True
    manifest["health_probe"]["command"] = [
        "/usr/bin/python3",
        "safe-skill/probe.py",
    ]
    calls: list[dict] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="healthy\n", stderr="")

    receipt = audition_capability_archive(
        manifest,
        source_archive=archive,
        runner=runner,
        platform_name="darwin",
    )

    assert receipt["status"] == "pass"
    assert calls[0]["command"][0] == "/usr/bin/sandbox-exec"
    assert calls[0]["env"] == {
        "HOME": calls[0]["env"]["HOME"],
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": calls[0]["env"]["TMPDIR"],
    }
    assert receipt["stdout_sha256"] == hashlib.sha256(b"healthy\n").hexdigest()


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS sandbox adapter")
def test_real_macos_audition_executes_health_probe_in_sandbox(
    tmp_path: Path,
) -> None:
    sandbox_probe = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            "(version 1)\n(allow default)",
            "/usr/bin/true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if sandbox_probe.returncode == 71:
        pytest.skip("outer sandbox forbids nested sandbox-exec")
    archive = tmp_path / "real-probe.tar"
    digest = _archive(
        archive,
        {
            "safe-skill/probe.py": b"print('healthy')\n",
            "safe-skill/SKILL.md": (
                b"---\nname: safe-skill\n"
                b"description: Real sandbox probe.\n---\n"
            ),
        },
    )
    manifest = _manifest(digest)
    manifest["installation"]["executes_code"] = True
    manifest["health_probe"]["command"] = [
        "/usr/bin/python3",
        "safe-skill/probe.py",
    ]

    receipt = audition_capability_archive(
        manifest,
        source_archive=archive,
    )

    assert receipt["status"] == "pass", receipt
    assert receipt["sandbox_adapter"] == "macos_sandbox_exec"
    assert receipt["network_allowed"] is False
