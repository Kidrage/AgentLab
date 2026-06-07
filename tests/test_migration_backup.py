from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from migration_doctor import run_migration_doctor
from truenas_sync import build_backup_status, run_truenas_sync


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def create_root(root: Path, remote: Path) -> None:
    for rel in ["agent_runtime", "agent_templates", "config", "projects", "web_ui"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / "projects" / "Demo" / "agent_docs").mkdir(parents=True, exist_ok=True)
    (root / "projects" / "Demo" / "runs").mkdir(parents=True, exist_ok=True)
    write_yaml(root / "projects" / "Demo" / "agent_docs" / "10_SYNC_LEDGER.yml", {"version": 1, "project": "Demo", "entries": []})
    write_yaml(root / "projects" / "Demo" / "project_config.yml", {"github": {"backup": {"enabled": True, "repo": "Demo", "branch": "main"}}})
    write_yaml(root / "config" / "github_policy.yml", {"auth": {"token_env": "GITHUB_TOKEN"}, "defaults": {"backup_branch": "main"}})
    write_yaml(
        root / "config" / "migration_profile.yml",
        {
            "environment": {"python": ">=3.10"},
            "required_user_inputs": {
                "model_api": [{"name": "DEEPSEEK_API_KEY", "required": False, "purpose": "test"}],
                "backup_permissions": {"github": {"token_env": "GITHUB_TOKEN"}},
                "web_ui": {"port_env": "AGENTLAB_PORT", "default_port": 8765, "auth_required": False},
                "cache": {"root": ".agentlab_runtime/cache"},
            },
        },
    )
    write_yaml(
        root / "config" / "backup_policy.yml",
        {
            "targets": {
                "truenas": {
                    "enabled": True,
                    "protocol_url": "smb://example/AgentLab_WorkSpace",
                    "mount_path": str(remote),
                    "exclude": ["**/.env"],
                    "sync_items": [
                        {"local_path": "projects/Demo/agent_docs", "remote_path": "projects/Demo/agent_docs", "direction": "push_only_merge"}
                    ],
                }
            }
        },
    )


class MigrationDoctorTests(TestCase):
    def test_migration_doctor_reports_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            remote = Path(td) / "remote"
            remote.mkdir(parents=True)
            create_root(root, remote)
            old = os.environ.get("GITHUB_TOKEN")
            os.environ["GITHUB_TOKEN"] = "secret-token-value"
            try:
                report = run_migration_doctor(root, "Demo", write_probe=True)
            finally:
                if old is None:
                    os.environ.pop("GITHUB_TOKEN", None)
                else:
                    os.environ["GITHUB_TOKEN"] = old

            text = yaml.safe_dump(report)
            self.assertIn(report["status"], {"pass", "warn"})
            self.assertNotIn("secret-token-value", text)


class TrueNASSyncTests(TestCase):
    def test_dry_run_does_not_write_remote_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            remote = Path(td) / "remote"
            remote.mkdir(parents=True)
            create_root(root, remote)
            source = root / "projects" / "Demo" / "agent_docs" / "07_DEVELOPMENT_LOG.md"
            source.write_text("local log\n", encoding="utf-8")

            report = run_truenas_sync(root, "Demo", "task_0001", dry_run=True, execute=False)

            self.assertEqual(report["status"], "dry_run_completed")
            self.assertFalse((remote / "projects" / "Demo" / "agent_docs" / "07_DEVELOPMENT_LOG.md").exists())
            self.assertTrue((root / "projects" / "Demo" / "runs" / "task_0001" / "truenas_manifest.yml").exists())

    def test_execute_does_not_overwrite_existing_remote_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            remote = Path(td) / "remote"
            remote.mkdir(parents=True)
            create_root(root, remote)
            source = root / "projects" / "Demo" / "agent_docs" / "07_DEVELOPMENT_LOG.md"
            source.write_text("local log\n", encoding="utf-8")
            target = remote / "projects" / "Demo" / "agent_docs" / "07_DEVELOPMENT_LOG.md"
            target.parent.mkdir(parents=True)
            target.write_text("remote log\n", encoding="utf-8")

            report = run_truenas_sync(root, "Demo", "task_0002", dry_run=False, execute=True)

            self.assertEqual(report["status"], "synced")
            self.assertEqual(target.read_text(encoding="utf-8"), "remote log\n")
            self.assertEqual(report["skipped_existing"], 1)

    def test_execute_copies_new_file_and_updates_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            remote = Path(td) / "remote"
            remote.mkdir(parents=True)
            create_root(root, remote)
            source = root / "projects" / "Demo" / "agent_docs" / "08_CODEX_DIALOGUE_LOG.md"
            source.write_text("codex log\n", encoding="utf-8")

            report = run_truenas_sync(root, "Demo", "task_0003", dry_run=False, execute=True)
            copied = remote / "projects" / "Demo" / "agent_docs" / "08_CODEX_DIALOGUE_LOG.md"
            status = build_backup_status(root, "Demo", task_id="task_0003")

            self.assertEqual(report["status"], "synced")
            self.assertTrue(copied.exists())
            self.assertEqual(copied.read_text(encoding="utf-8"), "codex log\n")
            self.assertEqual(status["truenas"]["latest"].get("target"), "truenas")


if __name__ == "__main__":
    main()
