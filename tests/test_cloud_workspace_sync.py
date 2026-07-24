from __future__ import annotations

import contextlib
import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import cloud_workspace_sync as cws
from cloud_workspace_sync import (
    SyncError,
    build_plan,
    build_rsync_command,
    classify_project_sync,
    knowledge_marker,
    launch_agent_payload,
    load_profile,
    tree_hash,
)


def _write_config(root: Path) -> None:
    path = root / "config" / "cloud_workspace_sync.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "profiles": {
                    "cloud_250": {
                        "endpoint_alias": "250",
                        "remote_root": "/home/admin/AgentLab",
                        "branch": "agentlab/unified-stable",
                        "interval_seconds": 300,
                        "project_paths": ["projects/AgentLab", "projects/Crown_of_Ash"],
                        "rag_path": ".agentlab_runtime/knowledge",
                        "receipt_path": ".agentlab/sync/cloud_250",
                        "local_untracked_allowlist": ["tmp_debug/"],
                        "never_sync": [".env", ".git", ".claude"],
                        "initial_rag_seed": True,
                        "rebuild_rag_after_project_change": True,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_tree_hash_is_deterministic_and_tracks_relative_symlinks(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("one", encoding="utf-8")
    (tree / "link").symlink_to(Path("a.txt"))
    first = tree_hash(tree)
    assert first == tree_hash(tree)
    (tree / "a.txt").write_text("two", encoding="utf-8")
    assert tree_hash(tree) != first


def test_knowledge_marker_uses_small_latest_build_receipt(tmp_path: Path) -> None:
    latest = tmp_path / ".agentlab_runtime/knowledge/receipts/latest_build.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps({"receipt_id": "kbuild_a"}), encoding="utf-8")
    assert knowledge_marker(tmp_path, Path(".agentlab_runtime/knowledge")) == tree_hash(latest)


@pytest.mark.parametrize(
    ("baseline", "local", "remote", "expected"),
    [
        (None, {"p": "a"}, {"p": None}, "initial_push"),
        ({"p": "a"}, {"p": "b"}, {"p": "a"}, "push"),
        ({"p": "a"}, {"p": "a"}, {"p": "b"}, "pull"),
        ({"p": "a"}, {"p": "b"}, {"p": "c"}, "conflict"),
        ({"p": "a"}, {"p": "b"}, {"p": "b"}, "synced"),
    ],
)
def test_classify_project_sync(
    baseline: dict[str, str | None] | None,
    local: dict[str, str | None],
    remote: dict[str, str | None],
    expected: str,
) -> None:
    assert classify_project_sync(baseline, local, remote) == expected


def test_explicit_push_refuses_to_overwrite_remote_only_change(tmp_path: Path) -> None:
    _write_config(tmp_path)
    profile = load_profile(tmp_path)
    receipt = {"state": {"projects": {"projects/AgentLab": "a", "projects/Crown_of_Ash": "a"}}}
    local = {
        "code_commit": "c1",
        "project_inventory": ["AgentLab", "Crown_of_Ash"],
        "forbidden_project_paths": [],
        "projects": {"projects/AgentLab": "a", "projects/Crown_of_Ash": "a"},
        "knowledge_marker": "k1",
    }
    remote = {
        "code_commit": "c1",
        "project_inventory": ["AgentLab", "Crown_of_Ash"],
        "forbidden_project_paths": [],
        "projects": {"projects/AgentLab": "b", "projects/Crown_of_Ash": "a"},
        "knowledge_marker": "k2",
    }
    with pytest.raises(SyncError, match="newer pull side"):
        build_plan(tmp_path, profile, local, remote, receipt, "push")


def test_rsync_command_is_argv_and_dry_run_is_explicit() -> None:
    command = build_rsync_command(
        "/source",
        "250:/destination",
        dry_run=True,
        excludes=(".env", ".git"),
    )
    assert command == [
        "rsync",
        "-a",
        "-e",
        "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ConnectionAttempts=1",
        "--delete",
        "--dry-run",
        "--exclude",
        ".env",
        "--exclude",
        ".git",
        "/source/",
        "250:/destination/",
    ]


def test_profile_and_launch_agent_preserve_frontdesk_and_five_minute_lag(
    tmp_path: Path,
) -> None:
    _write_config(tmp_path)
    (tmp_path / "scripts").mkdir()
    profile = load_profile(tmp_path)
    payload = launch_agent_payload(tmp_path, profile)
    assert payload["StartInterval"] == 300
    assert payload["ProgramArguments"][-2:] == ["auto", "--execute"]


def test_repository_profile_declares_openclaw_frontdesk_only() -> None:
    payload = yaml.safe_load(
        (ROOT / "config/cloud_workspace_sync.yml").read_text(encoding="utf-8")
    )
    openclaw = payload["profiles"]["cloud_250"]["openclaw"]
    assert openclaw["role"] == "frontdesk_only"
    assert openclaw["worker_capable"] is False
    assert {".env", ".git", ".claude", ".codex", ".grok", ".openclaw"}.issubset(
        set(payload["profiles"]["cloud_250"]["never_sync"])
    )


def test_execution_lock_blocks_a_second_synchronizer(tmp_path: Path) -> None:
    _write_config(tmp_path)
    profile = load_profile(tmp_path)
    with cws.execution_lock(tmp_path, profile):
        with pytest.raises(SyncError, match="already running"):
            with cws.execution_lock(tmp_path, profile):
                pass


def test_remote_deploy_never_stashes_a_dirty_workspace() -> None:
    assert "git\", \"stash" not in cws._REMOTE_DEPLOY_CODE_BODY
    assert "remote changes block deployment" in cws._REMOTE_DEPLOY_CODE_BODY


def test_plan_cas_rejects_local_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    profile = load_profile(tmp_path)
    plan = {
        "local": {
            "code_commit": "old",
            "projects": {"projects/AgentLab": "a"},
            "knowledge_marker": "k",
        },
        "remote": {
            "code_commit": "remote",
            "git_status": [],
            "projects": {"projects/AgentLab": "a"},
            "knowledge_marker": "k",
        },
    }
    monkeypatch.setattr(
        cws,
        "local_state",
        lambda *_args, **_kwargs: {
            "code_commit": "new",
            "projects": {"projects/AgentLab": "a"},
            "knowledge_marker": "k",
        },
    )
    monkeypatch.setattr(cws, "remote_state", lambda *_args, **_kwargs: plan["remote"])
    with pytest.raises(SyncError, match="local workspace changed"):
        cws._assert_plan_current(tmp_path, profile, plan)


def test_build_plan_rejects_a_third_project(tmp_path: Path) -> None:
    _write_config(tmp_path)
    profile = load_profile(tmp_path)
    state = {
        "code_commit": "c1",
        "project_inventory": ["AgentLab", "Crown_of_Ash", "OldProject"],
        "forbidden_project_paths": [],
        "projects": {"projects/AgentLab": "a", "projects/Crown_of_Ash": "b"},
        "knowledge_marker": "k",
    }
    with pytest.raises(SyncError, match="exactly the configured projects"):
        build_plan(tmp_path, profile, state, state, None, "auto")


def test_activate_launch_agent_bootstraps_and_kickstarts(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> object:
        calls.append(command)
        return type(
            "Result",
            (),
            {"returncode": 1 if len(calls) == 1 else 0, "stdout": "", "stderr": ""},
        )()

    cws.activate_launch_agent(tmp_path / "sync.plist", runner=runner)

    assert calls[0][:2] == ["launchctl", "print"]
    assert calls[1][:2] == ["launchctl", "bootstrap"]
    assert calls[2][:3] == ["launchctl", "kickstart", "-k"]


def test_activate_launch_agent_accepts_runatload_when_kickstart_is_denied(
    tmp_path: Path,
) -> None:
    responses = [
        (1, "", ""),
        (0, "", ""),
        (1, "", "Operation not permitted"),
        (0, "state = running", ""),
    ]

    def runner(_command: list[str], **_kwargs: object) -> object:
        returncode, stdout, stderr = responses.pop(0)
        return type(
            "Result",
            (),
            {"returncode": returncode, "stdout": stdout, "stderr": stderr},
        )()

    cws.activate_launch_agent(tmp_path / "sync.plist", runner=runner)
    assert responses == []


def test_code_only_deploy_rebuilds_remote_agentlab_knowledge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    profile = load_profile(tmp_path)
    projects = {"projects/AgentLab": "a", "projects/Crown_of_Ash": "b"}
    plan = {
        "code_action": "deploy_remote_from_github",
        "project_action": "synced",
        "local": {
            "code_commit": "c2",
            "projects": projects,
            "knowledge_marker": "k1",
        },
        "remote": {
            "code_commit": "c1",
            "projects": projects,
            "knowledge_marker": "k0",
        },
    }
    calls: list[list[str]] = []
    monkeypatch.setattr(cws, "_validate_local_git_clean", lambda *_: None)
    monkeypatch.setattr(cws, "_assert_plan_current", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cws,
        "remote_execution_lock",
        lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        cws,
        "deploy_remote_code",
        lambda *_args, **_kwargs: {"head": "c2"},
    )
    monkeypatch.setattr(
        cws,
        "run_remote_agentlab",
        lambda _profile, args, **_kwargs: calls.append(list(args)) or {},
    )
    monkeypatch.setattr(
        cws,
        "local_state",
        lambda *_args, **_kwargs: {
            "code_commit": "c2",
            "project_inventory": ["AgentLab", "Crown_of_Ash"],
            "forbidden_project_paths": [],
            "projects": projects,
            "knowledge_marker": "k2",
        },
    )
    monkeypatch.setattr(
        cws,
        "remote_state",
        lambda *_args, **_kwargs: {
            "code_commit": "c2",
            "project_inventory": ["AgentLab", "Crown_of_Ash"],
            "forbidden_project_paths": [],
            "projects": projects,
            "knowledge_marker": "k2",
        },
    )
    monkeypatch.setattr(cws, "write_receipt", lambda *_args, **_kwargs: None)

    cws.execute_plan(tmp_path, profile, plan, seed_rag=False)

    assert calls == [
        ["knowledge", "build", "--all-projects", "--seal-project-snapshot"]
    ]
