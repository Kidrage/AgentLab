"""Thin git helpers for AgentLab — status, diff, commit, push."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(cmd: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["git"] + cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def is_inside_work_tree(cwd: Path) -> bool:
    rc, _, _ = run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return rc == 0


def parse_porcelain_z(output: str) -> list[str]:
    """Parse ``git status --porcelain=v1 -z`` paths.

    The NUL form is the only safe status format for filenames with spaces,
    quotes, or punctuation. For rename/copy entries, return the destination
    path because that is the path Git should stage for the resulting commit.
    """
    if "\0" not in output:
        files: list[str] = []
        for line in output.splitlines():
            if not line:
                continue
            if len(line) >= 4:
                files.append(line[3:].strip())
        return [item for item in files if item]

    files = []
    entries = output.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            if index < len(entries) and entries[index]:
                path = entries[index]
                index += 1
        if path:
            files.append(path)
    return files


def get_changed_files(cwd: Path) -> list[str]:
    rc, stdout, _ = run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd)
    if rc != 0:
        return []
    return parse_porcelain_z(stdout)


def stage_files(cwd: Path, files: list[str]) -> bool:
    if not files:
        return True
    rc, _, stderr = run_git(["add", "--"] + files, cwd)
    return rc == 0


def commit(cwd: Path, message: str) -> tuple[bool, str]:
    rc, stdout, stderr = run_git(["commit", "-m", message], cwd)
    if rc == 0:
        # Extract commit sha
        sha_rc, sha_out, _ = run_git(["rev-parse", "HEAD"], cwd)
        return True, sha_out.strip() if sha_rc == 0 else ""
    return False, stderr.strip()


def push(cwd: Path, remote: str = "origin", branch: str = "main") -> tuple[bool, str]:
    rc, stdout, stderr = run_git(["push", remote, branch], cwd, timeout=120)
    return rc == 0, (stdout + stderr).strip()
