from __future__ import annotations

"""Repository hygiene checks for AgentLab S2.5.

The checker is intentionally conservative and local-only. It reports root-level
artifacts that should be moved into `.agentlab/`, `projects/`, or
`acceptance_runs/` instead of silently deleting anything.
"""

import fnmatch
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .models import HygieneFinding, HygieneReport

DEFAULT_ALLOWED_ROOT_FILES = {
    ".gitignore",
    "README.md",
    "agentlab.sh",
    "agentlab_app.py",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
    "tox.ini",
    "mypy.ini",
}

DEFAULT_ALLOWED_ROOT_DIRS = {
    ".git",
    ".github",
    ".agentlab",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "acceptance_runs",
    "agent_runtime",
    "config",
    "docs",
    "examples",
    "memory",
    "outputs",
    "projects",
    "scripts",
    "skills",
    "tests",
}

DEFAULT_FORBIDDEN_PATTERNS = [
    "*.tmp",
    "*handoff*.md",
    "*draft*.md",
    "粘贴的*",
    "untitled*",
    "scratch*",
]

MACOS_USERS_PREFIX = "/" + "Users"
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(" + re.escape(MACOS_USERS_PREFIX) + r"/[^\s'\"]+|/home/[^\s'\"]+)"
)


def load_hygiene_policy(repo_root: Path) -> dict[str, Any]:
    """Load repository hygiene policy with safe defaults."""

    path = repo_root / "config" / "repository_hygiene.yml"
    if not path.exists():
        return {
            "root_policy": {
                "allowed_root_files": sorted(DEFAULT_ALLOWED_ROOT_FILES),
                "allowed_root_dirs": sorted(DEFAULT_ALLOWED_ROOT_DIRS),
                "forbidden_root_patterns": DEFAULT_FORBIDDEN_PATTERNS,
                "ignored_runtime_dirs": [".agentlab", ".venv", "__pycache__", ".pytest_cache"],
            }
        }
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _policy_set(policy: dict[str, Any], key: str, default: set[str] | list[str]) -> set[str]:
    values = policy.get("root_policy", {}).get(key, list(default))
    return {str(item) for item in values}


def scan_repository_root(repo_root: Path, policy: dict[str, Any] | None = None) -> HygieneReport:
    """Scan the repository root for unclassified artifacts."""

    repo_root = repo_root.resolve()
    policy = policy or load_hygiene_policy(repo_root)
    allowed_files = _policy_set(policy, "allowed_root_files", DEFAULT_ALLOWED_ROOT_FILES)
    allowed_dirs = _policy_set(policy, "allowed_root_dirs", DEFAULT_ALLOWED_ROOT_DIRS)
    ignored_dirs = _policy_set(policy, "ignored_runtime_dirs", {".agentlab", ".venv", "__pycache__", ".pytest_cache"})
    ignored_files = _policy_set(policy, "ignored_root_files", set())
    forbidden_patterns = list(policy.get("root_policy", {}).get("forbidden_root_patterns", DEFAULT_FORBIDDEN_PATTERNS))

    findings: list[HygieneFinding] = []
    for child in sorted(repo_root.iterdir(), key=lambda p: p.name):
        name = child.name
        if name in {".", ".."}:
            continue
        if name in ignored_files:
            continue

        if child.is_dir():
            if name in ignored_dirs:
                continue
            if name not in allowed_dirs:
                findings.append(
                    HygieneFinding(
                        severity="error",
                        path=name,
                        code="unknown_root_dir",
                        message="Directory is not part of the repository root constitution.",
                        suggested_destination=".agentlab/ or projects/<project_id>/",
                    )
                )
            continue

        if name not in allowed_files:
            for pattern in forbidden_patterns:
                if fnmatch.fnmatch(name, pattern):
                    findings.append(
                        HygieneFinding(
                            severity="error",
                            path=name,
                            code="forbidden_root_pattern",
                            message=f"Root file matches forbidden runtime/scratch pattern: {pattern}",
                            suggested_destination=".agentlab/inbox/",
                        )
                    )
                    break

        if name not in allowed_files and not name.endswith((".md", ".txt")):
            findings.append(
                HygieneFinding(
                    severity="warning",
                    path=name,
                    code="unknown_root_file",
                    message="Root file is not explicitly allowed by repository_hygiene.yml.",
                    suggested_destination="docs/, config/, scripts/, examples/, or .agentlab/",
                )
            )

        if child.suffix in {".md", ".txt", ".yml", ".yaml", ".json", ".py", ".sh"}:
            try:
                text = child.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            text_without_urls = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", "", text)
            if ABSOLUTE_PATH_PATTERN.search(text_without_urls):
                findings.append(
                    HygieneFinding(
                        severity="warning",
                        path=name,
                        code="possible_absolute_path_leak",
                        message="File contains a local absolute path pattern.",
                        suggested_destination="redact path or move local-only material to .agentlab/",
                    )
                )

    hard_count = sum(1 for finding in findings if finding.severity == "error")
    warning_count = sum(1 for finding in findings if finding.severity == "warning")
    return HygieneReport(
        root=str(repo_root),
        hard_violation_count=hard_count,
        warning_count=warning_count,
        findings=findings,
    )


def hygiene_report_to_dict(report: HygieneReport) -> dict[str, Any]:
    return {
        "root": report.root,
        "ok": report.ok,
        "hard_violation_count": report.hard_violation_count,
        "warning_count": report.warning_count,
        "findings": [asdict(finding) for finding in report.findings],
    }


def render_hygiene_report(report: HygieneReport) -> str:
    lines = [
        "# Repository Hygiene Report",
        "",
        f"- Root: `{report.root}`",
        f"- Verdict: {'PASS' if report.ok else 'FAIL'}",
        f"- Hard violations: {report.hard_violation_count}",
        f"- Warnings: {report.warning_count}",
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("No root hygiene findings.")
    else:
        for finding in report.findings:
            lines.append(f"- **{finding.severity.upper()}** `{finding.path}` [{finding.code}]: {finding.message}")
            if finding.suggested_destination:
                lines.append(f"  - Suggested destination: `{finding.suggested_destination}`")
    lines.append("")
    return "\n".join(lines)


def print_hygiene_report(report: HygieneReport, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(hygiene_report_to_dict(report), indent=2, ensure_ascii=False))
    else:
        print(render_hygiene_report(report))
