"""Repository hygiene checks for maintainable source and fixture layout."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml"}
MAX_HUMAN_LINE_LENGTH = 2000
KEY_MULTILINE_FILES = [
    "README.md",
    ".gitignore",
    "agent_runtime/run_task.py",
    "agent_runtime/external_skill_importer.py",
    "docs/AGENTLAB_SKILL_FEEDBACK_ROADMAP.md",
]
ALLOWED_PROJECT_FILES = {"projects/README.md", "projects/.gitkeep"}
RUNTIME_AUDIO_SUFFIXES = {".wav", ".aiff", ".flac"}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_repo_hygiene_policy_accepts_registered_local_cli_runtime_dirs(tmp_path: Path) -> None:
    from agent_runtime.project_ops.repo_hygiene import scan_repository_root

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "repository_hygiene.yml").write_text(
        (ROOT / "config" / "repository_hygiene.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in (".agentlab_runtime", ".agy", ".claude", ".codex", ".hermes"):
        (tmp_path / name).mkdir()
    local_runtime_path = Path("/").joinpath("Users", "local", "private")
    (tmp_path / ".claude.json").write_text(
        f'{{"path": "{local_runtime_path}"}}',
        encoding="utf-8",
    )

    report = scan_repository_root(tmp_path)

    assert report.hard_violation_count == 0
    assert not report.findings


def test_tracked_text_files_do_not_have_extreme_lines() -> None:
    offenders: list[str] = []
    for relpath in _tracked_files():
        path = ROOT / relpath
        if not path.exists() or path.suffix not in TEXT_SUFFIXES:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if len(line) > MAX_HUMAN_LINE_LENGTH:
                offenders.append(f"{relpath}:{lineno}:{len(line)}")
    assert not offenders, "Extreme long lines in tracked text files: " + ", ".join(offenders[:20])


def test_key_human_edited_files_are_multiline() -> None:
    for relpath in KEY_MULTILINE_FILES:
        lines = (ROOT / relpath).read_text(encoding="utf-8").splitlines()
        assert len(lines) > 10, f"{relpath} looks collapsed or minified"


def test_project_runtime_artifacts_are_not_tracked() -> None:
    offenders: list[str] = []
    for relpath in _tracked_files():
        parts = relpath.split("/")
        if relpath.startswith("projects/") and relpath not in ALLOWED_PROJECT_FILES:
            offenders.append(relpath)
        if len(parts) >= 4 and parts[0] == "projects" and parts[2] in {"runs", "agent_docs"}:
            offenders.append(relpath)
        if Path(relpath).suffix.lower() in RUNTIME_AUDIO_SUFFIXES:
            offenders.append(relpath)
    assert not sorted(set(offenders)), "Runtime artifacts tracked: " + ", ".join(sorted(set(offenders))[:20])
