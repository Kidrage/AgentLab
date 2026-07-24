"""Versioned synchronization between the local AgentLab workspace and cloud 250.

GitHub is the source authority for tracked files. Project directories use a
single-writer-per-sync-interval protocol: the side that changed since the last
shared receipt wins, while simultaneous divergent changes fail closed. RAG is
seeded once and then rebuilt from the synchronized source/project truth.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml


class SyncError(RuntimeError):
    """Raised when a synchronization invariant is not satisfied."""


Runner = Callable[..., subprocess.CompletedProcess[str]]
REMOTE_RE = re.compile(r"^[A-Za-z0-9_.@-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class SyncProfile:
    name: str
    remote: str
    remote_root: Path
    branch: str
    interval_seconds: int
    project_paths: tuple[Path, ...]
    rag_path: Path
    receipt_path: Path
    allowed_untracked: tuple[str, ...]
    never_sync: tuple[str, ...]
    seed_rag: bool
    rebuild_rag: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def tree_hash(path: Path) -> str | None:
    """Hash a tree without following symlinks.

    Symlink targets are part of the manifest so portable relative links remain
    verifiable and host-specific absolute links are detected as drift.
    """

    target = Path(path)
    if not target.exists() and not target.is_symlink():
        return None
    if target.is_symlink():
        return _sha256_bytes(f"symlink:{os.readlink(target)}".encode())
    if target.is_file():
        return _sha256_bytes(target.read_bytes())
    entries: list[dict[str, str]] = []
    for root, dirnames, filenames in os.walk(target, followlinks=False):
        root_path = Path(root)
        for name in sorted(tuple(dirnames)):
            child = root_path / name
            if child.is_symlink():
                entries.append(
                    {
                        "path": child.relative_to(target).as_posix(),
                        "kind": "symlink",
                        "sha256": _sha256_bytes(os.readlink(child).encode()),
                    }
                )
                dirnames.remove(name)
        for name in sorted(filenames):
            child = root_path / name
            relative = child.relative_to(target).as_posix()
            if child.is_symlink():
                entries.append(
                    {
                        "path": relative,
                        "kind": "symlink",
                        "sha256": _sha256_bytes(os.readlink(child).encode()),
                    }
                )
            elif child.is_file():
                entries.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "sha256": _sha256_bytes(child.read_bytes()),
                    }
                )
    encoded = json.dumps(
        sorted(entries, key=lambda item: (item["path"], item["kind"])),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _sha256_bytes(encoded)


def knowledge_marker(root: Path, relative: Path) -> str | None:
    latest = root / relative / "receipts" / "latest_build.json"
    return tree_hash(latest)


def load_profile(root: Path, profile_name: str = "cloud_250") -> SyncProfile:
    path = root / "config" / "cloud_workspace_sync.yml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = (payload.get("profiles") or {}).get(profile_name)
    if not isinstance(raw, dict):
        raise SyncError(f"unknown workspace sync profile: {profile_name}")
    remote = str(raw.get("endpoint_alias") or "")
    branch = str(raw.get("branch") or "")
    remote_root = Path(str(raw.get("remote_root") or ""))
    if not REMOTE_RE.fullmatch(remote):
        raise SyncError("endpoint_alias contains unsupported characters")
    if not BRANCH_RE.fullmatch(branch) or ".." in branch:
        raise SyncError("branch contains unsupported characters")
    if not remote_root.is_absolute() or str(remote_root) == "/":
        raise SyncError("remote_root must be a specific absolute path")
    project_paths = tuple(Path(str(item)) for item in raw.get("project_paths") or [])
    if not project_paths or any(path.is_absolute() or ".." in path.parts for path in project_paths):
        raise SyncError("project_paths must be non-empty repository-relative paths")
    return SyncProfile(
        name=profile_name,
        remote=remote,
        remote_root=remote_root,
        branch=branch,
        interval_seconds=int(raw.get("interval_seconds") or 300),
        project_paths=project_paths,
        rag_path=Path(str(raw.get("rag_path") or ".agentlab_runtime/knowledge")),
        receipt_path=Path(str(raw.get("receipt_path") or ".agentlab/sync/cloud_250")),
        allowed_untracked=tuple(str(item) for item in raw.get("local_untracked_allowlist") or []),
        never_sync=tuple(str(item) for item in raw.get("never_sync") or []),
        seed_rag=bool(raw.get("initial_rag_seed", True)),
        rebuild_rag=bool(raw.get("rebuild_rag_after_project_change", True)),
    )


def _git(root: Path, *args: str, runner: Runner = subprocess.run) -> str:
    result = runner(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SyncError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def local_state(root: Path, profile: SyncProfile) -> dict[str, Any]:
    return {
        "code_commit": _git(root, "rev-parse", "HEAD"),
        "projects": {
            path.as_posix(): tree_hash(root / path) for path in profile.project_paths
        },
        "knowledge_marker": knowledge_marker(root, profile.rag_path),
    }


_REMOTE_STATE_BODY = r"""
import hashlib
import json
import os
import pathlib
import subprocess

root = pathlib.Path(PAYLOAD["root"])

def sha(payload):
    return hashlib.sha256(payload).hexdigest()

def tree_hash(path):
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        return sha(("symlink:" + os.readlink(path)).encode())
    if path.is_file():
        return sha(path.read_bytes())
    entries = []
    for current, dirnames, filenames in os.walk(path, followlinks=False):
        current_path = pathlib.Path(current)
        for name in sorted(tuple(dirnames)):
            child = current_path / name
            if child.is_symlink():
                entries.append({
                    "path": child.relative_to(path).as_posix(),
                    "kind": "symlink",
                    "sha256": sha(os.readlink(child).encode()),
                })
                dirnames.remove(name)
        for name in sorted(filenames):
            child = current_path / name
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                entries.append({
                    "path": relative,
                    "kind": "symlink",
                    "sha256": sha(os.readlink(child).encode()),
                })
            elif child.is_file():
                entries.append({
                    "path": relative,
                    "kind": "file",
                    "sha256": sha(child.read_bytes()),
                })
    encoded = json.dumps(
        sorted(entries, key=lambda item: (item["path"], item["kind"])),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha(encoded)

head = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=root,
    text=True,
    capture_output=True,
    check=False,
)
status = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=root,
    text=True,
    capture_output=True,
    check=False,
)
latest = root / PAYLOAD["rag_path"] / "receipts" / "latest_build.json"
receipt = root / PAYLOAD["receipt_path"] / "current.json"
print(json.dumps({
    "code_commit": head.stdout.strip() if head.returncode == 0 else None,
    "git_status": status.stdout.splitlines(),
    "projects": {
        relative: tree_hash(root / relative)
        for relative in PAYLOAD["project_paths"]
    },
    "knowledge_marker": tree_hash(latest),
    "receipt": json.loads(receipt.read_text()) if receipt.exists() else None,
}, ensure_ascii=False))
"""


def _remote_python(
    profile: SyncProfile,
    body: str,
    payload: Mapping[str, Any],
    *,
    runner: Runner = subprocess.run,
    timeout: int = 180,
) -> dict[str, Any]:
    prefix = "import json\nPAYLOAD = json.loads(" + repr(json.dumps(payload)) + ")\n"
    result = runner(
        ["ssh", profile.remote, "python3", "-"],
        input=prefix + body,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise SyncError(result.stderr.strip() or "remote Python command failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SyncError(f"remote command returned invalid JSON: {result.stdout[:200]}") from exc


def remote_state(profile: SyncProfile, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    return _remote_python(
        profile,
        _REMOTE_STATE_BODY,
        {
            "root": str(profile.remote_root),
            "project_paths": [path.as_posix() for path in profile.project_paths],
            "rag_path": profile.rag_path.as_posix(),
            "receipt_path": profile.receipt_path.as_posix(),
        },
        runner=runner,
    )


def load_local_receipt(root: Path, profile: SyncProfile) -> dict[str, Any] | None:
    path = root / profile.receipt_path / "current.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def classify_project_sync(
    baseline: Mapping[str, str | None] | None,
    local_projects: Mapping[str, str | None],
    remote_projects: Mapping[str, str | None],
) -> str:
    """Return synced, push, pull, initial_push, or conflict."""

    local = dict(local_projects)
    remote = dict(remote_projects)
    if local == remote:
        return "synced"
    if baseline is None:
        if all(value is None for value in remote.values()) and any(
            value is not None for value in local.values()
        ):
            return "initial_push"
        return "conflict"
    base = dict(baseline)
    local_changed = local != base
    remote_changed = remote != base
    if local_changed and not remote_changed:
        return "push"
    if remote_changed and not local_changed:
        return "pull"
    if local_changed and remote_changed and local == remote:
        return "synced"
    return "conflict"


def build_plan(
    root: Path,
    profile: SyncProfile,
    local: Mapping[str, Any],
    remote: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    requested_direction: str,
) -> dict[str, Any]:
    baseline = None
    if receipt:
        baseline = ((receipt.get("state") or {}).get("projects"))
    project_action = classify_project_sync(
        baseline,
        local.get("projects") or {},
        remote.get("projects") or {},
    )
    if requested_direction in {"push", "pull"}:
        if project_action == "conflict":
            raise SyncError("both workspaces changed since the last receipt; manual resolution required")
        if project_action not in {"synced", "initial_push", requested_direction}:
            raise SyncError(
                f"requested {requested_direction} would overwrite a newer {project_action} side"
            )
        project_action = requested_direction if project_action != "synced" else "synced"
    elif requested_direction != "auto":
        raise SyncError(f"unsupported direction: {requested_direction}")
    code_action = (
        "synced"
        if local.get("code_commit") == remote.get("code_commit")
        else "deploy_remote_from_github"
    )
    return {
        "schema_version": 1,
        "profile": profile.name,
        "generated_at": _utc_now(),
        "requested_direction": requested_direction,
        "code_action": code_action,
        "project_action": project_action,
        "local": dict(local),
        "remote": dict(remote),
        "receipt_present": receipt is not None,
    }


def _validate_local_git_clean(root: Path, profile: SyncProfile) -> None:
    lines = _git(root, "status", "--porcelain").splitlines()
    disallowed = []
    for line in lines:
        path = line[3:] if len(line) > 3 else line
        if line.startswith("?? ") and any(path.startswith(item) for item in profile.allowed_untracked):
            continue
        disallowed.append(line)
    if disallowed:
        raise SyncError(f"local tracked/unapproved changes block sync: {disallowed}")


@contextlib.contextmanager
def execution_lock(root: Path, profile: SyncProfile) -> Iterable[None]:
    """Serialize manual and scheduled synchronization on the local authority."""

    path = root / profile.receipt_path / "execution.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncError("another workspace synchronization is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _assert_plan_current(
    root: Path,
    profile: SyncProfile,
    plan: Mapping[str, Any],
    *,
    runner: Runner = subprocess.run,
) -> None:
    current_local = local_state(root, profile)
    current_remote = remote_state(profile, runner=runner)
    local_keys = ("code_commit", "projects", "knowledge_marker")
    remote_keys = ("code_commit", "git_status", "projects", "knowledge_marker")
    if any(current_local.get(key) != plan["local"].get(key) for key in local_keys):
        raise SyncError("local workspace changed after synchronization planning")
    if any(current_remote.get(key) != plan["remote"].get(key) for key in remote_keys):
        raise SyncError("remote workspace changed after synchronization planning")


_REMOTE_DEPLOY_CODE_BODY = r"""
import json
import pathlib
import shutil
import subprocess

root = pathlib.Path(PAYLOAD["root"])
branch = PAYLOAD["branch"]
status = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=root,
    text=True,
    capture_output=True,
    check=True,
).stdout.splitlines()
if status:
    raise SystemExit("remote changes block deployment: " + repr(status))
subprocess.run(["git", "fetch", "origin", branch], cwd=root, check=True)
exists = subprocess.run(
    ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + branch],
    cwd=root,
).returncode == 0
if exists:
    subprocess.run(["git", "switch", branch], cwd=root, check=True)
    subprocess.run(["git", "merge", "--ff-only", "origin/" + branch], cwd=root, check=True)
else:
    subprocess.run(["git", "switch", "-c", branch, "--track", "origin/" + branch], cwd=root, check=True)
head = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=root,
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()
print(json.dumps({"status": "deployed", "head": head}))
"""


def deploy_remote_code(profile: SyncProfile, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    return _remote_python(
        profile,
        _REMOTE_DEPLOY_CODE_BODY,
        {"root": str(profile.remote_root), "branch": profile.branch},
        runner=runner,
    )


def build_rsync_command(
    source: str,
    destination: str,
    *,
    delete: bool = True,
    dry_run: bool = False,
    excludes: Sequence[str] = (),
) -> list[str]:
    command = ["rsync", "-a"]
    if delete:
        command.append("--delete")
    if dry_run:
        command.append("--dry-run")
    for pattern in excludes:
        command.extend(["--exclude", pattern])
    command.extend([source.rstrip("/") + "/", destination.rstrip("/") + "/"])
    return command


def _run_checked(
    command: Sequence[str],
    *,
    runner: Runner = subprocess.run,
    timeout: int = 3600,
) -> None:
    result = runner(
        list(command),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise SyncError(result.stderr.strip() or f"command failed: {command[0]}")


_REMOTE_SWAP_BODY = r"""
import hashlib
import json
import os
import pathlib
import shutil

root = pathlib.Path(PAYLOAD["root"])
stage_root = pathlib.Path(PAYLOAD["stage_root"])
backup_root = root / ".agentlab" / "sync" / "cloud_250" / "backups" / PAYLOAD["sync_id"]

def sha(payload):
    return hashlib.sha256(payload).hexdigest()

def tree_hash(path):
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        return sha(("symlink:" + os.readlink(path)).encode())
    if path.is_file():
        return sha(path.read_bytes())
    entries = []
    for current, dirnames, filenames in os.walk(path, followlinks=False):
        current_path = pathlib.Path(current)
        for name in sorted(tuple(dirnames)):
            child = current_path / name
            if child.is_symlink():
                entries.append({"path": child.relative_to(path).as_posix(), "kind": "symlink", "sha256": sha(os.readlink(child).encode())})
                dirnames.remove(name)
        for name in sorted(filenames):
            child = current_path / name
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                entries.append({"path": relative, "kind": "symlink", "sha256": sha(os.readlink(child).encode())})
            elif child.is_file():
                entries.append({"path": relative, "kind": "file", "sha256": sha(child.read_bytes())})
    return sha(json.dumps(sorted(entries, key=lambda item: (item["path"], item["kind"])), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode())

moved = []
try:
    for item in PAYLOAD["items"]:
        relative = pathlib.Path(item["relative"])
        staged = stage_root / relative
        destination = root / relative
        if tree_hash(staged) != item["sha256"]:
            raise RuntimeError("staged hash mismatch: " + item["relative"])
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            shutil.move(str(destination), str(backup))
        shutil.move(str(staged), str(destination))
        moved.append((destination, backup))
except Exception:
    for destination, backup in reversed(moved):
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if backup.exists() or backup.is_symlink():
            shutil.move(str(backup), str(destination))
    raise
print(json.dumps({"status": "swapped", "count": len(moved)}))
"""


def _atomic_replace_local(
    root: Path,
    stage_root: Path,
    items: Iterable[tuple[Path, str]],
    sync_id: str,
) -> None:
    backup_root = root / ".agentlab" / "sync" / "cloud_250" / "backups" / sync_id
    moved: list[tuple[Path, Path]] = []
    try:
        for relative, expected in items:
            staged = stage_root / relative
            destination = root / relative
            if tree_hash(staged) != expected:
                raise SyncError(f"staged hash mismatch: {relative}")
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                shutil.move(str(destination), str(backup))
            shutil.move(str(staged), str(destination))
            moved.append((destination, backup))
    except Exception:
        for destination, backup in reversed(moved):
            if destination.exists() or destination.is_symlink():
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            if backup.exists() or backup.is_symlink():
                shutil.move(str(backup), str(destination))
        raise


def _sync_projects_push(
    root: Path,
    profile: SyncProfile,
    hashes: Mapping[str, str | None],
    sync_id: str,
    *,
    runner: Runner = subprocess.run,
) -> None:
    stage = profile.remote_root.parent / ".agentlab_sync" / profile.name / sync_id
    _remote_python(
        profile,
        "import json\nimport pathlib\n"
        "base = pathlib.Path(PAYLOAD['stage_root'])\n"
        "for relative in PAYLOAD['parents']:\n"
        "    (base / relative).mkdir(parents=True, exist_ok=True)\n"
        "print(json.dumps({'status': 'ready'}))\n",
        {
            "stage_root": str(stage),
            "parents": sorted(
                {relative.parent.as_posix() for relative in profile.project_paths}
            ),
        },
        runner=runner,
    )
    items = []
    for relative in profile.project_paths:
        expected = hashes.get(relative.as_posix())
        if not expected:
            raise SyncError(f"missing local project: {relative}")
        destination = f"{profile.remote}:{stage / relative}"
        _run_checked(
            build_rsync_command(
                str(root / relative),
                destination,
                excludes=profile.never_sync,
            ),
            runner=runner,
        )
        items.append({"relative": relative.as_posix(), "sha256": expected})
    _remote_python(
        profile,
        _REMOTE_SWAP_BODY,
        {
            "root": str(profile.remote_root),
            "stage_root": str(stage),
            "sync_id": sync_id,
            "items": items,
        },
        runner=runner,
        timeout=600,
    )


def _sync_projects_pull(
    root: Path,
    profile: SyncProfile,
    hashes: Mapping[str, str | None],
    sync_id: str,
    *,
    runner: Runner = subprocess.run,
) -> None:
    stage = root / ".agentlab_sync" / profile.name / sync_id
    stage.mkdir(parents=True, exist_ok=True)
    items = []
    for relative in profile.project_paths:
        expected = hashes.get(relative.as_posix())
        if not expected:
            raise SyncError(f"missing remote project: {relative}")
        (stage / relative).parent.mkdir(parents=True, exist_ok=True)
        _run_checked(
            build_rsync_command(
                f"{profile.remote}:{profile.remote_root / relative}",
                str(stage / relative),
                excludes=profile.never_sync,
            ),
            runner=runner,
        )
        items.append((relative, expected))
    _atomic_replace_local(root, stage, items, sync_id)


def _seed_rag(
    root: Path,
    profile: SyncProfile,
    sync_id: str,
    *,
    runner: Runner = subprocess.run,
) -> None:
    source = root / profile.rag_path
    if not source.is_dir():
        raise SyncError("local RAG path is missing")
    stage = profile.remote_root.parent / ".agentlab_sync" / profile.name / sync_id
    _remote_python(
        profile,
        "import json\nimport pathlib\n"
        "(pathlib.Path(PAYLOAD['stage_root']) / PAYLOAD['parent']).mkdir("
        "parents=True, exist_ok=True)\n"
        "print(json.dumps({'status': 'ready'}))\n",
        {
            "stage_root": str(stage),
            "parent": profile.rag_path.parent.as_posix(),
        },
        runner=runner,
    )
    destination = f"{profile.remote}:{stage / profile.rag_path}"
    _run_checked(build_rsync_command(str(source), destination), runner=runner)
    expected = tree_hash(source)
    _remote_python(
        profile,
        _REMOTE_SWAP_BODY,
        {
            "root": str(profile.remote_root),
            "stage_root": str(stage),
            "sync_id": sync_id,
            "items": [{"relative": profile.rag_path.as_posix(), "sha256": expected}],
        },
        runner=runner,
        timeout=1200,
    )


_REMOTE_AGENTLAB_BODY = r"""
import json
import pathlib
import subprocess

root = pathlib.Path(PAYLOAD["root"])
result = subprocess.run(
    [str(root / "agentlab.sh"), *PAYLOAD["args"]],
    cwd=root,
    text=True,
    capture_output=True,
    check=False,
    timeout=PAYLOAD.get("timeout", 600),
)
print(json.dumps({
    "returncode": result.returncode,
    "stdout": result.stdout[-4000:],
    "stderr": result.stderr[-2000:],
}))
"""


def run_remote_agentlab(
    profile: SyncProfile,
    args: Sequence[str],
    *,
    runner: Runner = subprocess.run,
    timeout: int = 600,
) -> dict[str, Any]:
    result = _remote_python(
        profile,
        _REMOTE_AGENTLAB_BODY,
        {"root": str(profile.remote_root), "args": list(args), "timeout": timeout},
        runner=runner,
        timeout=timeout + 30,
    )
    if result.get("returncode") != 0:
        raise SyncError(
            f"remote agentlab command failed: {result.get('stderr') or result.get('stdout')}"
        )
    return result


def run_local_agentlab(root: Path, args: Sequence[str], *, runner: Runner = subprocess.run) -> None:
    _run_checked([str(root / "agentlab.sh"), *args], runner=runner, timeout=900)


_REMOTE_WRITE_RECEIPT_BODY = r"""
import json
import pathlib

root = pathlib.Path(PAYLOAD["root"])
base = root / PAYLOAD["receipt_path"]
receipts = base / "receipts"
receipts.mkdir(parents=True, exist_ok=True)
encoded = json.dumps(PAYLOAD["receipt"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
receipt_path = receipts / (PAYLOAD["receipt"]["sync_id"] + ".json")
if receipt_path.exists():
    if receipt_path.read_text(encoding="utf-8") != encoded:
        raise RuntimeError("immutable receipt collision: " + str(receipt_path))
else:
    with receipt_path.open("x", encoding="utf-8") as handle:
        handle.write(encoded)
temporary = base / (".current." + PAYLOAD["receipt"]["sync_id"] + ".tmp")
temporary.write_text(encoded, encoding="utf-8")
temporary.replace(base / "current.json")
print(json.dumps({"status": "written", "path": str(receipt_path)}))
"""


def write_receipt(
    root: Path,
    profile: SyncProfile,
    receipt: Mapping[str, Any],
    *,
    runner: Runner = subprocess.run,
) -> None:
    base = root / profile.receipt_path
    receipts = base / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    receipt_path = receipts / f"{receipt['sync_id']}.json"
    if receipt_path.exists():
        if receipt_path.read_text(encoding="utf-8") != encoded:
            raise SyncError(f"immutable receipt collision: {receipt_path}")
    else:
        with receipt_path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    temporary = base / f".current.{receipt['sync_id']}.tmp"
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(base / "current.json")
    _remote_python(
        profile,
        _REMOTE_WRITE_RECEIPT_BODY,
        {
            "root": str(profile.remote_root),
            "receipt_path": profile.receipt_path.as_posix(),
            "receipt": dict(receipt),
        },
        runner=runner,
    )


def execute_plan(
    root: Path,
    profile: SyncProfile,
    plan: Mapping[str, Any],
    *,
    seed_rag: bool,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    with execution_lock(root, profile):
        _validate_local_git_clean(root, profile)
        _assert_plan_current(root, profile, plan, runner=runner)
        sync_id = "sync_" + _sha256_bytes(
            json.dumps(
                {
                    "generated_at": _utc_now(),
                    "local": plan["local"],
                    "remote": plan["remote"],
                    "project_action": plan["project_action"],
                },
                sort_keys=True,
            ).encode()
        )
        code_deployed = plan["code_action"] != "synced"
        if code_deployed:
            deployed = deploy_remote_code(profile, runner=runner)
            if deployed.get("head") != plan["local"]["code_commit"]:
                raise SyncError("remote GitHub deployment did not reach the local commit")
        action = str(plan["project_action"])
        if action in {"push", "initial_push"}:
            _sync_projects_push(
                root,
                profile,
                plan["local"]["projects"],
                sync_id,
                runner=runner,
            )
            if seed_rag:
                _seed_rag(root, profile, sync_id, runner=runner)
                run_remote_agentlab(profile, ["knowledge", "doctor"], runner=runner)
            elif profile.rebuild_rag:
                run_remote_agentlab(
                    profile,
                    ["knowledge", "build", "--all-projects", "--seal-project-snapshot"],
                    runner=runner,
                )
        elif action == "pull":
            _sync_projects_pull(
                root,
                profile,
                plan["remote"]["projects"],
                sync_id,
                runner=runner,
            )
            if profile.rebuild_rag:
                run_local_agentlab(
                    root,
                    ["knowledge", "build", "--all-projects", "--seal-project-snapshot"],
                    runner=runner,
                )
        elif action != "synced":
            raise SyncError(f"project synchronization is blocked: {action}")
        if (
            code_deployed
            and not seed_rag
            and action not in {"push", "initial_push"}
            and profile.rebuild_rag
        ):
            run_remote_agentlab(
                profile,
                ["knowledge", "build", "--all-projects", "--seal-project-snapshot"],
                runner=runner,
            )
        final_local = local_state(root, profile)
        final_remote = remote_state(profile, runner=runner)
        if final_local["code_commit"] != final_remote["code_commit"]:
            raise SyncError("code commits differ after synchronization")
        if final_local["projects"] != final_remote["projects"]:
            raise SyncError("project hashes differ after synchronization")
        receipt = {
            "schema_version": 1,
            "sync_id": sync_id,
            "profile": profile.name,
            "completed_at": _utc_now(),
            "direction": action,
            "state": {
                "code_commit": final_local["code_commit"],
                "projects": final_local["projects"],
                "local_knowledge_marker": final_local["knowledge_marker"],
                "remote_knowledge_marker": final_remote["knowledge_marker"],
            },
        }
        write_receipt(root, profile, receipt, runner=runner)
        return receipt


def launch_agent_payload(root: Path, profile: SyncProfile) -> dict[str, Any]:
    python = Path(sys.executable).resolve()
    script = root / "scripts" / "sync_250_workspace.py"
    log_dir = Path.home() / "Library" / "Logs" / "AgentLab"
    return {
        "Label": "com.agentlab.cloud250-sync",
        "ProgramArguments": [
            str(python),
            str(script),
            "auto",
            "--execute",
        ],
        "WorkingDirectory": str(root),
        "StartInterval": profile.interval_seconds,
        "RunAtLoad": True,
        "StandardOutPath": str(log_dir / "cloud250-sync.log"),
        "StandardErrorPath": str(log_dir / "cloud250-sync.error.log"),
    }


def install_launch_agent(root: Path, profile: SyncProfile) -> Path:
    payload = launch_agent_payload(root, profile)
    destination = Path.home() / "Library" / "LaunchAgents" / f"{payload['Label']}.plist"
    destination.parent.mkdir(parents=True, exist_ok=True)
    Path(payload["StandardOutPath"]).parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".plist.tmp")
    temporary.write_bytes(plistlib.dumps(payload, sort_keys=True))
    temporary.replace(destination)
    return destination


def _root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=("status", "auto", "push", "pull", "install"))
    parser.add_argument("--execute", action="store_true", help="Perform the planned mutation.")
    parser.add_argument("--seed-rag", action="store_true", help="Copy the current RAG on this run.")
    parser.add_argument("--profile", default="cloud_250")
    parser.add_argument("--root", type=Path, default=_root_from_script())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    profile = load_profile(root, args.profile)
    if args.direction == "install":
        if not args.execute:
            print(json.dumps(launch_agent_payload(root, profile), ensure_ascii=False, indent=2))
            return 0
        print(install_launch_agent(root, profile))
        return 0
    local = local_state(root, profile)
    remote = remote_state(profile)
    receipt = load_local_receipt(root, profile) or remote.get("receipt")
    requested = "auto" if args.direction == "status" else args.direction
    plan = build_plan(root, profile, local, remote, receipt, requested)
    if args.direction == "status" or not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if plan["project_action"] != "conflict" else 2
    result = execute_plan(
        root,
        profile,
        plan,
        seed_rag=args.seed_rag or (profile.seed_rag and not receipt),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SyncError as exc:
        print(f"sync blocked: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
