from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from git_utils import get_changed_files, parse_porcelain_z
import rule_self_check


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_parse_porcelain_z_keeps_punctuation_and_spaces() -> None:
    raw = "?? tests/test_external_result_submission.py<\0 M docs/file with spaces.md\0"

    assert parse_porcelain_z(raw) == [
        "tests/test_external_result_submission.py<",
        "docs/file with spaces.md",
    ]


def test_parse_porcelain_z_uses_rename_destination() -> None:
    raw = "R  old name.py\0new name.py\0"

    assert parse_porcelain_z(raw) == ["new name.py"]


def test_get_changed_files_handles_odd_filenames(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "agentlab@example.test")
    _git(tmp_path, "config", "user.name", "AgentLab Test")
    odd = tmp_path / "tests" / "test_external_result_submission.py<"
    spaced = tmp_path / "docs" / "file with spaces.md"
    odd.parent.mkdir(parents=True)
    spaced.parent.mkdir(parents=True)
    odd.write_text("x = 1\n", encoding="utf-8")
    spaced.write_text("hello\n", encoding="utf-8")

    changed = get_changed_files(tmp_path)

    assert "tests/test_external_result_submission.py<" in changed
    assert "docs/file with spaces.md" in changed


def test_self_check_uses_nul_safe_git_status_parser(tmp_path: Path) -> None:
    changed_path = "tests/test_external_result_submission.py<"
    (tmp_path / "tests").mkdir()
    (tmp_path / changed_path).write_text("x = 1\n", encoding="utf-8")

    def fake_run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, "true\n", ""
        if cmd == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]:
            return 0, f"?? {changed_path}\0", ""
        if cmd[:2] == ["git", "diff"]:
            return 0, "", ""
        if cmd[1:3] == ["-m", "py_compile"]:
            return 0, "", ""
        return 0, "", ""

    with patch.object(rule_self_check, "_run", side_effect=fake_run):
        report = rule_self_check.run_self_check(tmp_path, "Demo", "task_status_parse")

    assert changed_path in report["artifacts"]["changed_files"]
