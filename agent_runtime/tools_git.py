"""Safe git inspection helper skeletons."""

from pathlib import Path
import subprocess


def _run_git(repo_path: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return result.stderr.strip()
    return result.stdout.strip()


def git_status(repo_path: Path) -> str:
    """Return short status without modifying the repository."""
    return _run_git(repo_path, ["status", "--short"])


def git_diff(repo_path: Path) -> str:
    """Return unstaged diff without modifying the repository."""
    return _run_git(repo_path, ["diff", "--"])


def git_diff_cached(repo_path: Path) -> str:
    """Return staged diff without modifying the repository."""
    return _run_git(repo_path, ["diff", "--cached", "--"])
