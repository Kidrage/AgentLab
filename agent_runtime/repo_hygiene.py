from __future__ import annotations

"""Repository hygiene checks for AgentLab's own checkout.

The checker is intentionally read-only. It reports root pollution and common
text-integrity problems so external IDE agents have a safe place to stop before
turning scratch files into project truth.
"""

from dataclasses import dataclass
import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Any


ALLOWED_ROOT_NAMES = {
    ".github",
    ".gitignore",
    "AGENTS.md",
    "CLI_ROADMAP.md",
    "DRIVER_PROTOCOL.md",
    "OPERATING_MODEL.md",
    "README.md",
    "acceptance_runs",
    "agent_runtime",
    "agent_templates",
    "agentlab.sh",
    "agentlab_app.py",
    "atomic_io.py",
    "config",
    "docs",
    "examples",
    "governance_runs",
    "projects",
    "pytest.ini",
    "requirements.txt",
    "scripts",
    "skills",
    "state_store.py",
    "tests",
    "web_ui",
}

FORBIDDEN_ROOT_PATTERNS = [
    "*draft*.md",
    "*handoff*.md",
    "*scratch*",
    "*untitled*",
    "*pasted*",
    "*粘贴*",
    "*主线修复任务*",
]

TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

HOME_PATH_PATTERN = r"/" + r"Users/" + r"[^\\s:'\")]+"
PRIVATE_PATH_PATTERN = r"/private/(?:tmp|var)/[^\\s:'\")]+"
ABSOLUTE_PATH_RE = re.compile(f"({HOME_PATH_PATTERN}|{PRIVATE_PATH_PATTERN})")


@dataclass(frozen=True)
class HygieneIssue:
    severity: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


def _git_lines(root: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _root_name(path_text: str) -> str:
    return path_text.split("/", 1)[0]


def _is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES and path.is_file()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def check_repo_hygiene(root: Path) -> dict[str, Any]:
    root = root.resolve()
    issues: list[HygieneIssue] = []

    gitignore = root / ".gitignore"
    gitignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".agentlab/" not in gitignore_text:
        issues.append(
            HygieneIssue(
                "error",
                "agentlab_runtime_not_ignored",
                ".gitignore",
                ".agentlab/ must be gitignored for external agent scratch space.",
            )
        )

    tracked = set(_git_lines(root, ["ls-files"]))
    untracked = set(_git_lines(root, ["ls-files", "--others", "--exclude-standard"]))
    known_paths = tracked | untracked

    for path_text in sorted(known_paths):
        if path_text in tracked and not (root / path_text).exists():
            continue
        root_name = _root_name(path_text)
        if root_name == ".git":
            continue
        if root_name == ".agentlab":
            issues.append(
                HygieneIssue(
                    "error",
                    "runtime_file_in_git_view",
                    path_text,
                    ".agentlab runtime files must stay ignored and untracked.",
                )
            )
        if "/" not in path_text and root_name not in ALLOWED_ROOT_NAMES:
            issues.append(
                HygieneIssue(
                    "error",
                    "unknown_root_entry",
                    path_text,
                    "Root entry is not part of the AgentLab repository constitution.",
                )
            )
        if "/" not in path_text:
            for pattern in FORBIDDEN_ROOT_PATTERNS:
                if fnmatch.fnmatch(path_text.lower(), pattern.lower()):
                    issues.append(
                        HygieneIssue(
                            "error",
                            "forbidden_root_artifact",
                            path_text,
                            f"Root file matches forbidden external-agent artifact pattern: {pattern}",
                        )
                    )
                    break

    for path_text in sorted(tracked):
        path = root / path_text
        if not _is_text_candidate(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if ABSOLUTE_PATH_RE.search(text):
            issues.append(
                HygieneIssue(
                    "warning",
                    "absolute_local_path",
                    path_text,
                    "Text file contains a local absolute path; verify it is intentional.",
                )
            )
        if "\n" not in text and len(text) > 8000:
            issues.append(
                HygieneIssue(
                    "warning",
                    "suspicious_single_line_text",
                    path_text,
                    "Text file is unusually large and has no newline; possible corruption or minified artifact.",
                )
            )

    return {
        "status": "pass" if not any(issue.severity == "error" for issue in issues) else "fail",
        "root": str(root),
        "issue_count": len(issues),
        "errors": sum(1 for issue in issues if issue.severity == "error"),
        "warnings": sum(1 for issue in issues if issue.severity == "warning"),
        "issues": [issue.as_dict() for issue in issues],
        "runtime_inbox": str(root / ".agentlab" / "inbox"),
    }


def render_hygiene_report(report: dict[str, Any]) -> str:
    lines = [
        "# AgentLab Repo Hygiene",
        "",
        f"status: {report['status']}",
        f"errors: {report['errors']}",
        f"warnings: {report['warnings']}",
        f"runtime_inbox: {report['runtime_inbox']}",
        "",
    ]
    if not report["issues"]:
        lines.append("No issues found.")
        return "\n".join(lines)
    lines.append("## Issues")
    for issue in report["issues"]:
        lines.append(
            f"- [{issue['severity']}] {issue['code']} :: {issue['path']} :: {issue['message']}"
        )
    return "\n".join(lines)
