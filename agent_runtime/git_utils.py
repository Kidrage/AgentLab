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


def get_changed_files(cwd: Path) -> list[str]:
    rc, stdout, _ = run_git(["status", "--porcelain"], cwd)
    if rc != 0:
        return []
    files = []
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            files.append(parts[1])
        elif parts:
            files.append(parts[0])
    return files


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