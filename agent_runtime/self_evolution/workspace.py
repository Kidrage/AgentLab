"""Git-isolated workspace operations for self-evolution candidates."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import yaml

from .models import ComponentManifest


class EvolutionWorkspaceError(RuntimeError):
    pass


def _run(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise EvolutionWorkspaceError(
            f"command failed ({' '.join(args)}): {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def _workspace_identity(root: Path, evolution_id: str, component_id: str) -> tuple[str, Path]:
    suffix = sha256(f"{root}:{evolution_id}".encode("utf-8")).hexdigest()[:10]
    root_identity = f"{root.name}-{sha256(str(root).encode('utf-8')).hexdigest()[:10]}"
    branch = f"agentlab-evolution/{component_id}-{suffix}"
    worktree = (
        Path(tempfile.gettempdir())
        / "agentlab-self-evolution-worktrees"
        / root_identity
        / evolution_id
    )
    return branch, worktree


def _resolved_git_path(value: str, cwd: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def validate_candidate_worktree(
    root: Path,
    workspace_receipt: dict[str, Any],
    *,
    evolution_id: str,
    component_id: str,
) -> tuple[Path, str]:
    """Fail closed unless a receipt names the exact managed Git worktree."""

    root = Path(root).resolve()
    expected_branch, expected_worktree = _workspace_identity(
        root,
        evolution_id,
        component_id,
    )
    worktree = Path(str(workspace_receipt.get("worktree") or "")).resolve()
    branch = str(workspace_receipt.get("branch") or "")
    if str(workspace_receipt.get("source_root") or "") != str(root):
        raise EvolutionWorkspaceError("candidate receipt source_root does not match AgentLab root")
    if workspace_receipt.get("evolution_id") != evolution_id:
        raise EvolutionWorkspaceError("candidate receipt evolution_id does not match")
    if workspace_receipt.get("component_id") != component_id:
        raise EvolutionWorkspaceError("candidate receipt component_id does not match")
    if worktree != expected_worktree.resolve() or branch != expected_branch:
        raise EvolutionWorkspaceError("candidate receipt is outside the managed worktree identity")
    if not worktree.exists():
        raise EvolutionWorkspaceError("candidate worktree receipt is missing or stale")

    actual_root = _resolved_git_path(
        _run(["git", "rev-parse", "--show-toplevel"], cwd=worktree).stdout.strip(),
        worktree,
    )
    if actual_root != worktree:
        raise EvolutionWorkspaceError("candidate path is not the registered worktree root")
    source_common = _resolved_git_path(
        _run(["git", "rev-parse", "--git-common-dir"], cwd=root).stdout.strip(),
        root,
    )
    candidate_common = _resolved_git_path(
        _run(["git", "rev-parse", "--git-common-dir"], cwd=worktree).stdout.strip(),
        worktree,
    )
    if candidate_common != source_common:
        raise EvolutionWorkspaceError("candidate worktree is not attached to the AgentLab repository")
    actual_branch = _run(
        ["git", "branch", "--show-current"],
        cwd=worktree,
    ).stdout.strip()
    if actual_branch != expected_branch:
        raise EvolutionWorkspaceError("candidate worktree branch identity changed")
    base_head = str(workspace_receipt.get("base_head") or "")
    source_head = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    candidate_head = _run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if not base_head or base_head != source_head or candidate_head != base_head:
        raise EvolutionWorkspaceError(
            "candidate worktree must remain on the current recorded base_head before review"
        )
    return worktree, branch


def assert_candidate_worktree_scope(worktree: Path, *, component_id: str) -> None:
    """Reject candidate-tree changes outside the one generated component."""

    manifest_path = f"config/components/agents/{component_id}.yml"
    generated_path = f"config/generated/roles/{component_id}"
    dirty_paths: set[str] = set()
    for command in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        dirty_paths.update(
            path
            for path in _run(command, cwd=worktree).stdout.splitlines()
            if path
        )
    unexpected = sorted(
        path
        for path in dirty_paths
        if path != manifest_path and not path.startswith(generated_path + "/")
    )
    if unexpected:
        raise EvolutionWorkspaceError(
            "candidate worktree contains paths outside the component allowlist: "
            + ", ".join(unexpected)
        )


def assert_candidate_bundle_unchanged(
    worktree: Path,
    *,
    component_id: str,
    manifest_fingerprint: str,
    bridge_bundle: Path,
) -> None:
    manifest_path = worktree / "config" / "components" / "agents" / f"{component_id}.yml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvolutionWorkspaceError("candidate component manifest must be a regular file")
    candidate_manifest = ComponentManifest.load(manifest_path)
    if candidate_manifest.fingerprint != manifest_fingerprint:
        raise EvolutionWorkspaceError("candidate component manifest changed after validation")
    generated = worktree / "config" / "generated" / "roles" / component_id
    if bridge_bundle.is_symlink() or generated.is_symlink():
        raise EvolutionWorkspaceError("generated bridge roots must not be symlinks")

    def regular_file_inventory(directory: Path, *, label: str) -> dict[Path, tuple[str, bool]]:
        inventory: dict[Path, tuple[str, bool]] = {}
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise EvolutionWorkspaceError(f"{label} contains a symlink: {path}")
            if path.is_file():
                inventory[path.relative_to(directory)] = (
                    sha256(path.read_bytes()).hexdigest(),
                    bool(path.stat().st_mode & 0o111),
                )
        return inventory

    compatibility_path = bridge_bundle / "compatibility_manifest.yml"
    if compatibility_path.is_symlink() or not compatibility_path.is_file():
        raise EvolutionWorkspaceError("bridge compatibility manifest must be a regular file")
    compatibility = yaml.safe_load(
        compatibility_path.read_text(encoding="utf-8")
    ) or {}
    declared_hashes = {
        Path(str(item.get("path") or "")): str(item.get("sha256") or "")
        for item in compatibility.get("generated_files") or []
        if isinstance(item, dict)
    }
    actual_declared_files = {
        path.relative_to(bridge_bundle): sha256(path.read_bytes()).hexdigest()
        for path in bridge_bundle.rglob("*")
        if path.is_file() and path != compatibility_path and not path.is_symlink()
    }
    if declared_hashes != actual_declared_files:
        raise EvolutionWorkspaceError("bridge bundle no longer matches its compatibility manifest")
    expected_files = regular_file_inventory(bridge_bundle, label="bridge bundle")
    candidate_files = regular_file_inventory(generated, label="candidate bridge bundle")
    if candidate_files != expected_files:
        raise EvolutionWorkspaceError("candidate generated bridge bundle changed after validation")


def _expected_review_blobs(
    worktree: Path,
    *,
    component_id: str,
    bridge_bundle: Path,
) -> dict[str, tuple[str, str]]:
    manifest_relative = f"config/components/agents/{component_id}.yml"
    manifest_file = worktree / manifest_relative
    expected = {
        manifest_relative: (
            "100755" if manifest_file.stat().st_mode & 0o111 else "100644",
            _run(
                ["git", "hash-object", "--", manifest_relative],
                cwd=worktree,
            ).stdout.strip(),
        )
    }
    for path in bridge_bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(bridge_bundle).as_posix()
        target = f"config/generated/roles/{component_id}/{relative}"
        expected[target] = (
            "100755" if path.stat().st_mode & 0o111 else "100644",
            _run(
                ["git", "hash-object", "--", str(path)],
                cwd=worktree,
            ).stdout.strip(),
        )
    return expected


def _tree_blobs(
    worktree: Path,
    *,
    treeish: str,
    manifest_path: str,
    generated_path: str,
) -> dict[str, tuple[str, str]]:
    if treeish == ":":
        lines = _run(
            ["git", "ls-files", "--stage", "--", manifest_path, generated_path],
            cwd=worktree,
        ).stdout.splitlines()
    else:
        lines = _run(
            ["git", "ls-tree", "-r", treeish, "--", manifest_path, generated_path],
            cwd=worktree,
        ).stdout.splitlines()
    result: dict[str, tuple[str, str]] = {}
    for line in lines:
        metadata, separator, path = line.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) < 3:
            raise EvolutionWorkspaceError("unable to parse candidate Git object inventory")
        mode = fields[0]
        if treeish == ":":
            blob = fields[1]
            if fields[2] != "0":
                raise EvolutionWorkspaceError("candidate contains a non-zero index stage")
        else:
            if fields[1] != "blob":
                raise EvolutionWorkspaceError("candidate contains a non-blob Git object")
            blob = fields[2]
        result[path] = (mode, blob)
    return result


def _assert_git_objects_match_bundle(
    worktree: Path,
    *,
    treeish: str,
    component_id: str,
    bridge_bundle: Path,
    expected: dict[str, tuple[str, str]] | None = None,
) -> None:
    manifest_path = f"config/components/agents/{component_id}.yml"
    generated_path = f"config/generated/roles/{component_id}"
    if expected is None:
        expected = _expected_review_blobs(
            worktree,
            component_id=component_id,
            bridge_bundle=bridge_bundle,
        )
    actual = _tree_blobs(
        worktree,
        treeish=treeish,
        manifest_path=manifest_path,
        generated_path=generated_path,
    )
    if set(actual) != set(expected):
        raise EvolutionWorkspaceError("candidate Git object set differs from the validated bundle")
    invalid = [path for path, value in actual.items() if value != expected[path]]
    if invalid:
        raise EvolutionWorkspaceError(
            "candidate Git objects differ from the validated regular files: "
            + ", ".join(sorted(invalid))
        )


def create_candidate_worktree(
    root: Path,
    *,
    evolution_id: str,
    manifest: ComponentManifest,
    bridge_bundle: Path,
) -> dict[str, Any]:
    """Create an isolated branch and copy only generated component files into it."""

    root = Path(root).resolve()
    source_status = _run(["git", "status", "--porcelain"], cwd=root).stdout.splitlines()
    protected_dirty = [
        item
        for item in source_status
        if not item[3:].startswith("projects/")
    ]
    if protected_dirty:
        raise EvolutionWorkspaceError(
            "source worktree has non-task changes; commit or isolate them before self-evolution"
        )
    if bridge_bundle.is_symlink() or any(
        path.is_symlink() for path in bridge_bundle.rglob("*")
    ):
        raise EvolutionWorkspaceError("bridge bundle must contain regular files only")
    branch, worktree = _workspace_identity(
        root,
        evolution_id,
        manifest.component_id,
    )
    if worktree.exists():
        raise EvolutionWorkspaceError(f"evolution worktree already exists: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"], cwd=root)

    manifest_path = worktree / "config" / "components" / "agents" / f"{manifest.component_id}.yml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump(manifest.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    generated_path = worktree / "config" / "generated" / "roles" / manifest.component_id
    shutil.copytree(bridge_bundle, generated_path)
    assert_candidate_bundle_unchanged(
        worktree,
        component_id=manifest.component_id,
        manifest_fingerprint=manifest.fingerprint,
        bridge_bundle=bridge_bundle,
    )
    return {
        "status": "created",
        "source_root": str(root),
        "evolution_id": evolution_id,
        "component_id": manifest.component_id,
        "branch": branch,
        "worktree": str(worktree),
        "base_head": _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip(),
        "source_worktree_clean": not source_status,
        "source_dirty_paths": source_status,
        "changed_paths": [
            str(manifest_path.relative_to(worktree)),
            str(generated_path.relative_to(worktree)),
        ],
        "main_branch_modified": False,
    }


def prepare_draft_review(
    root: Path,
    workspace_receipt: dict[str, Any],
    *,
    evolution_id: str,
    component_id: str,
    manifest_fingerprint: str,
    bridge_bundle: Path,
    publish: bool = False,
) -> dict[str, Any]:
    worktree, branch = validate_candidate_worktree(
        root,
        workspace_receipt,
        evolution_id=evolution_id,
        component_id=component_id,
    )
    assert_candidate_worktree_scope(worktree, component_id=component_id)
    assert_candidate_bundle_unchanged(
        worktree,
        component_id=component_id,
        manifest_fingerprint=manifest_fingerprint,
        bridge_bundle=bridge_bundle,
    )
    expected_review_blobs = _expected_review_blobs(
        worktree,
        component_id=component_id,
        bridge_bundle=bridge_bundle,
    )
    manifest_path = f"config/components/agents/{component_id}.yml"
    generated_path = f"config/generated/roles/{component_id}"
    _run(["git", "add", "--", manifest_path, generated_path], cwd=worktree)
    _assert_git_objects_match_bundle(
        worktree,
        treeish=":",
        component_id=component_id,
        bridge_bundle=bridge_bundle,
        expected=expected_review_blobs,
    )
    staged = _run(["git", "diff", "--cached", "--quiet"], cwd=worktree, check=False)
    if staged.returncode == 0:
        raise EvolutionWorkspaceError("candidate worktree has no staged component changes")
    if staged.returncode not in {0, 1}:
        raise EvolutionWorkspaceError("unable to inspect staged component changes")
    staged_paths = _run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=worktree,
    ).stdout.splitlines()
    unexpected = [
        path
        for path in staged_paths
        if path != manifest_path and not path.startswith(generated_path + "/")
    ]
    if unexpected:
        raise EvolutionWorkspaceError(
            "candidate review contains paths outside the component allowlist: "
            + ", ".join(unexpected)
        )
    _run(
        ["git", "commit", "-m", f"feat: register AgentLab component {component_id}"],
        cwd=worktree,
    )
    commit = _run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    assert_candidate_bundle_unchanged(
        worktree,
        component_id=component_id,
        manifest_fingerprint=manifest_fingerprint,
        bridge_bundle=bridge_bundle,
    )
    _assert_git_objects_match_bundle(
        worktree,
        treeish=commit,
        component_id=component_id,
        bridge_bundle=bridge_bundle,
        expected=expected_review_blobs,
    )
    base_head = str(workspace_receipt.get("base_head") or "")
    commit_count = int(
        _run(["git", "rev-list", "--count", f"{base_head}..{commit}"], cwd=worktree)
        .stdout.strip()
        or "0"
    )
    outgoing_paths = _run(
        ["git", "diff", "--name-only", f"{base_head}..{commit}"],
        cwd=worktree,
    ).stdout.splitlines()
    unexpected_outgoing = [
        path
        for path in outgoing_paths
        if path != manifest_path and not path.startswith(generated_path + "/")
    ]
    if commit_count != 1 or unexpected_outgoing:
        raise EvolutionWorkspaceError(
            "candidate branch outgoing range is not one allowlisted component commit"
        )
    remaining_changes = _run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=worktree,
    ).stdout.splitlines()
    if remaining_changes:
        raise EvolutionWorkspaceError(
            "candidate worktree is not clean after the allowlisted component commit"
        )
    result: dict[str, Any] = {
        "status": "local_review_ready",
        "branch": branch,
        "commit": commit,
        "base_head": base_head,
        "commit_count": commit_count,
        "outgoing_paths": outgoing_paths,
        "worktree": str(worktree),
        "human_merge_required": True,
        "auto_merge": False,
    }
    if not publish:
        return result
    remote = _run(["git", "remote", "get-url", "origin"], cwd=worktree, check=False)
    if remote.returncode != 0:
        result["publish_status"] = "skipped_no_origin"
        return result
    _run(["git", "push", "-u", "origin", branch], cwd=worktree)
    gh = shutil.which("gh")
    if not gh:
        result["status"] = "branch_published_review_bundle"
        result["publish_status"] = "gh_unavailable"
        return result
    pr = _run(
        [gh, "pr", "create", "--draft", "--fill", "--head", branch],
        cwd=worktree,
        check=False,
    )
    result["status"] = "draft_pr_created" if pr.returncode == 0 else "branch_published_review_bundle"
    result["publish_status"] = "pass" if pr.returncode == 0 else "gh_pr_create_failed"
    result["pull_request"] = pr.stdout.strip() or None
    result["publish_error"] = pr.stderr.strip() or None
    return result
