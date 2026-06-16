#!/usr/bin/env python3
"""Check GitHub raw text integrity for critical AgentLab files."""

from __future__ import annotations

# text-integrity: keep this file as real physical lines in Git and GitHub raw.
import argparse
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import time_ns
from urllib.parse import quote

CRITICAL_FILES = [
    "agent_runtime/skill_distiller.py",
    "agent_runtime/skill_vault.py",
    "agent_runtime/skill_backup.py",
    "agent_runtime/post_task_learning.py",
    "agent_runtime/external_skill_importer.py",
    "agent_runtime/pipeline_runner.py",
    "agent_runtime/search_cli.py",
    "agent_runtime/search/provider.py",
    "agent_runtime/search/policy.py",
    "agent_runtime/skill_evolution.py",
    "config/skill_distillation.yml",
    "config/skill_vault.yml",
    "config/backup_policy.yml",
    "config/search_providers.yml",
    "config/external_skill_import_policy.yml",
    "docs/SKILL_DISTILLATION.md",
    "docs/SKILL_DISCOVERY_ROADMAP.md",
    "docs/SKILL_VAULT.md",
    "scripts/audit_text_integrity.py",
    "scripts/check_remote_raw_integrity.py",
    "tests/test_repository_text_integrity.py",
    "tests/test_text_integrity_audit.py",
    "README.md",
    "agentlab.sh",
]

MIN_LINES = {
    "agent_runtime/skill_distiller.py": 200,
    "agent_runtime/skill_vault.py": 200,
    "agent_runtime/skill_backup.py": 100,
    "config/skill_vault.yml": 20,
    "config/backup_policy.yml": 200,
    "docs/SKILL_VAULT.md": 40,
    "scripts/audit_text_integrity.py": 120,
    "scripts/check_remote_raw_integrity.py": 80,
    "tests/test_repository_text_integrity.py": 80,
    "tests/test_text_integrity_audit.py": 60,
    "agentlab.sh": 20,
}


@dataclass
class RawResult:
    path: str
    status: str
    lines: int = 0
    max_line: int = 0
    bytes: int = 0
    issue: str = ""


def fetch_raw(repo: str, branch: str, path: str, timeout: int = 20) -> RawResult:
    encoded_path = quote(path, safe="/")
    cache_bust = time_ns()
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{encoded_path}?cache_bust={cache_bust}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        return RawResult(path=path, status=str(exc.code), issue=f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return RawResult(path=path, status="ERROR", issue=str(exc.reason))
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    max_line = max((len(line) for line in lines), default=0)
    issues: list[str] = []
    if len(data) > 1000 and len(lines) <= 10:
        issues.append(f"compressed: {len(lines)} physical lines for {len(data)} bytes")
    if max_line > 1000:
        issues.append(f"max line {max_line} > 1000")
    minimum = MIN_LINES.get(path)
    if minimum is not None and len(lines) < minimum:
        issues.append(f"critical file needs >= {minimum} lines, has {len(lines)}")
    return RawResult(
        path=path,
        status="OK" if not issues else "SUSPICIOUS",
        lines=len(lines),
        max_line=max_line,
        bytes=len(data),
        issue="; ".join(issues),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check GitHub raw integrity for AgentLab critical files")
    parser.add_argument("--repo", required=True, help="owner/repo, e.g. Kidrage/AgentLab")
    parser.add_argument(
        "--branch",
        "--ref",
        dest="branch",
        default="main",
        help="Git branch or ref to check",
    )
    parser.add_argument("--fail-on-suspicious", action="store_true")
    parser.add_argument("paths", nargs="*", help="Optional paths to check instead of default critical files")
    args = parser.parse_args(argv)

    paths = args.paths or CRITICAL_FILES
    results = [fetch_raw(args.repo, args.branch, path) for path in paths]
    suspicious = [r for r in results if r.status != "OK"]
    print(f"Remote raw integrity: repo={args.repo} branch={args.branch}")
    print("Path | Status | Lines | Max Line | Bytes | Issue")
    print("--- | --- | ---: | ---: | ---: | ---")
    for result in results:
        print(
            f"{result.path} | {result.status} | {result.lines} | "
            f"{result.max_line} | {result.bytes} | {result.issue}"
        )
    print(f"Checked {len(results)} files; suspicious={len(suspicious)}")
    if suspicious and args.fail_on_suspicious:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
