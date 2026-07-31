from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from subprocess import CompletedProcess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from project_memory_relay import (
    _commit_version_slot,
    _next_version_slot,
    _snapshot,
    project_memory_remote_path,
    sync_all_project_memories,
    sync_project_memory_file,
    watcher_interval_seconds,
)


class FakeRunner:
    def __init__(self, responses: list[tuple[int, str, str]]) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs) -> CompletedProcess[str]:
        self.calls.append(command)
        returncode, stdout, stderr = self.responses.pop(0)
        return CompletedProcess(command, returncode, stdout, stderr)


def _root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "AgentLab"
    identity = root / ".agentlab_runtime" / "test-key"
    identity.parent.mkdir(parents=True)
    identity.write_text("test", encoding="utf-8")
    config = {
        "targets": {
            "truenas": {
                "enabled": True,
                "transport": "ssh",
                "ssh": {
                    "host": "relay.test",
                    "port": 2222,
                    "user": "agentlab",
                    "identity_file": str(identity),
                    "remote_base_path": "/relay/AgentLab",
                },
                "continuous_project_memory": {
                    "enabled": True,
                    "endpoint_id": "cloud_250",
                },
                "exclude": ["**/.env", "*.key", "*.pem"],
            }
        }
    }
    (root / "config").mkdir(parents=True)
    (root / "config" / "backup_policy.yml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    (root / "config" / "memory_policy.yml").write_text(
        yaml.safe_dump(
            {
                "records": {
                    "project_memory": [
                        "00_CONTEXT_PACK.md",
                        "07_DEVELOPMENT_LOG.md",
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    memory = root / "projects" / "Example" / "agent_docs" / "07_DEVELOPMENT_LOG.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("updated memory\n", encoding="utf-8")
    return root, memory


def test_project_memory_remote_path_is_bounded_to_agent_docs(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)

    assert project_memory_remote_path(root, memory) == (
        "memory/projects/Example/agent_docs/07_DEVELOPMENT_LOG.md"
    )
    outside = root / "projects" / "Example" / "production" / "chapter.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("no", encoding="utf-8")
    assert project_memory_remote_path(root, outside) is None


def test_dry_run_is_read_only_and_reports_missing_remote_file(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)
    runner = FakeRunner([(0, "MISSING\n", "")])

    result = sync_project_memory_file(root, memory, execute=False, runner=runner)

    assert result["status"] == "would_update"
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "ssh"
    assert "mkdir" not in runner.calls[0][-1]


def test_execute_verifies_remote_sha256(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)
    digest = sha256(memory.read_bytes()).hexdigest()
    runner = FakeRunner(
        [
            (0, "", ""),
            (0, "<f.st...... 07_DEVELOPMENT_LOG.md\n", ""),
            (0, f"{digest}  remote-file\n", ""),
        ]
    )

    result = sync_project_memory_file(root, memory, execute=True, runner=runner)

    assert result["status"] == "synced"
    assert result["verified"] is True
    assert result["sha256"] == digest
    rsync = runner.calls[1]
    assert {"--checksum", "--update", "--backup", "--protect-args"} <= set(rsync)
    assert not any(flag.startswith("--delete") for flag in rsync)
    assert any(
        flag.startswith("--backup-dir=/relay/AgentLab/memory/history/cloud_250/slot-")
        for flag in rsync
    )
    assert any(
        flag.startswith("--rsync-path=flock -x ") and "sha256sum" in flag
        for flag in rsync
    )
    assert rsync[-1] == "agentlab@relay.test:/relay/AgentLab/memory/projects/Example/agent_docs/"


def test_execute_reports_conflict_when_remote_remains_different(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)
    runner = FakeRunner(
        [
            (0, "", ""),
            (0, "", ""),
            (0, f"{'0' * 64}  remote-file\n", ""),
        ]
    )

    result = sync_project_memory_file(root, memory, execute=True, runner=runner)

    assert result["status"] == "conflict"
    assert result["verified"] is False
    assert "remote is newer or changed concurrently" in result["error"]


def test_sync_all_discovers_every_project_agent_docs_file(tmp_path: Path) -> None:
    root, first = _root(tmp_path)
    second = root / "projects" / "Second" / "agent_docs" / "00_CONTEXT_PACK.md"
    second.parent.mkdir(parents=True)
    second.write_text("second\n", encoding="utf-8")
    runner = FakeRunner(
        [
            (0, "MISSING\n", ""),
            (0, "MISSING\n", ""),
        ]
    )

    report = sync_all_project_memories(root, execute=False, runner=runner)

    assert report["status"] == "dry_run_completed"
    assert report["file_count"] == 2
    assert {item["local_path"] for item in report["files"]} == {
        str(first),
        str(second),
    }


def test_unsafe_endpoint_id_is_rejected_before_remote_commands(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)
    config_path = root / "config" / "backup_policy.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["targets"]["truenas"]["continuous_project_memory"]["endpoint_id"] = "../../escape"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    runner = FakeRunner([])

    result = sync_project_memory_file(root, memory, execute=True, runner=runner)

    assert result["status"] == "error"
    assert runner.calls == []


def test_sync_all_does_not_report_success_when_feature_is_disabled(tmp_path: Path) -> None:
    root, _ = _root(tmp_path)
    config_path = root / "config" / "backup_policy.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["targets"]["truenas"]["continuous_project_memory"]["enabled"] = False
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    report = sync_all_project_memories(root, execute=True, runner=FakeRunner([]))

    assert report["status"] == "disabled"
    assert report["problem_count"] == 1


def test_ungoverned_agent_docs_file_is_not_transmitted(tmp_path: Path) -> None:
    root, _ = _root(tmp_path)
    secret = root / "projects" / "Example" / "agent_docs" / ".env"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")
    runner = FakeRunner([])

    result = sync_project_memory_file(root, secret, execute=True, runner=runner)

    assert result["status"] == "rejected"
    assert runner.calls == []


def test_verification_command_failure_is_not_misreported_as_conflict(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)
    runner = FakeRunner(
        [
            (0, "", ""),
            (0, "<f.st...... 07_DEVELOPMENT_LOG.md\n", ""),
            (1, "", "sha256sum unavailable"),
        ]
    )

    result = sync_project_memory_file(root, memory, execute=True, runner=runner)

    assert result["status"] == "error"
    assert "verification command failed" in result["message"]
    remote = "memory/projects/Example/agent_docs/07_DEVELOPMENT_LOG.md"
    assert _next_version_slot(root, remote, 10) == 1


def test_snapshot_detects_same_size_edit_with_restored_mtime(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)
    before = _snapshot(root)
    original_stat = memory.stat()
    memory.write_text("changed memory\n", encoding="utf-8")
    assert memory.stat().st_size == original_stat.st_size
    import os

    os.utime(memory, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    assert _snapshot(root) != before


def test_watcher_interval_honors_hourly_policy_floor(tmp_path: Path) -> None:
    root, _ = _root(tmp_path)

    assert watcher_interval_seconds(root, requested=2) == 60


def test_version_slots_advance_sequentially_and_wrap(tmp_path: Path) -> None:
    root, _ = _root(tmp_path)
    remote = "memory/projects/Example/agent_docs/07_DEVELOPMENT_LOG.md"

    observed = []
    for _ in range(5):
        slot = _next_version_slot(root, remote, 3)
        observed.append(slot)
        _commit_version_slot(root, remote, slot)
    assert observed == [0, 1, 2, 0, 1]


def test_versioned_update_rejects_disabled_remote_history(tmp_path: Path) -> None:
    root, memory = _root(tmp_path)
    config_path = root / "config" / "backup_policy.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["targets"]["truenas"]["continuous_project_memory"]["remote_history"] = False
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    result = sync_project_memory_file(root, memory, execute=True, runner=FakeRunner([]))

    assert result["status"] == "error"
    assert "remote_history=true" in result["message"]


def test_sync_all_reports_empty_when_no_governed_memory_exists(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    (root / "config").mkdir(parents=True)
    (root / "config" / "backup_policy.yml").write_text("targets: {}\n", encoding="utf-8")
    (root / "config" / "memory_policy.yml").write_text("records: {}\n", encoding="utf-8")

    report = sync_all_project_memories(root, execute=True, runner=FakeRunner([]))

    assert report["status"] == "empty"
    assert report["file_count"] == 0
