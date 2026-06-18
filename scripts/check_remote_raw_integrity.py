#!/usr/bin/env python3
"""Check GitHub raw text integrity for critical AgentLab files."""

from __future__ import annotations

# text-integrity: keep this file as real physical lines in Git and GitHub raw.
import argparse
import hashlib
import sys
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from urllib.parse import quote

DEFAULT_REPO = "Kidrage/AgentLab"
ROOT = Path(__file__).resolve().parents[1]

CRITICAL_FILES = [
    ".github/workflows/ci.yml",
    "agentlab.sh",
    "agent_runtime/run_task.py",
    "agent_runtime/mcp_server.py",
    "agent_runtime/skills/registry.py",
    "agent_runtime/external_agents/ecc_inventory.py",
    "agent_runtime/external_agents/handoff.py",
    "agent_runtime/search/anysearch_adapter.py",
    "agent_runtime/search/local_url_reader.py",
    "agent_runtime/ingestion/repo_indexers/codegraph_adapter.py",
    "agent_runtime/repo_index_cli.py",
    "config/search_providers.yml",
    "config/repo_indexing.yml",
    "tests/test_repository_text_integrity.py",
]

MIN_LINES = {
    ".github/workflows/ci.yml": 25,
    "agentlab.sh": 20,
    "agent_runtime/run_task.py": 80,
    "agent_runtime/mcp_server.py": 80,
    "agent_runtime/skills/registry.py": 80,
    "agent_runtime/external_agents/ecc_inventory.py": 80,
    "agent_runtime/external_agents/handoff.py": 80,
    "agent_runtime/search/anysearch_adapter.py": 80,
    "agent_runtime/search/local_url_reader.py": 40,
    "agent_runtime/ingestion/repo_indexers/codegraph_adapter.py": 80,
    "agent_runtime/repo_index_cli.py": 60,
    "config/search_providers.yml": 10,
    "config/repo_indexing.yml": 10,
    "scripts/audit_text_integrity.py": 120,
    "scripts/check_remote_raw_integrity.py": 80,
    "tests/test_repository_text_integrity.py": 80,
}


@dataclass
class RawResult:
    path: str
    status: str
    lines: int = 0
    max_line: int = 0
    bytes: int = 0
    sha256: str = ""
    local_sha256: str = ""
    issue: str = ""


def local_git_blob_sha(ref: str, path: str) -> str | None:
    """Return the sha256 of the local git blob for a remote raw ref.

    For branch-like refs such as ``main``, prefer ``origin/main`` because raw
    GitHub content represents the remote branch, not a potentially stale local
    branch with the same name. Fall back to the literal ref for commit hashes,
    tags, or repositories without a matching remote-tracking branch.
    """

    candidate_refs = [ref]
    if "/" not in ref and not ref.startswith("origin/"):
        candidate_refs = [f"origin/{ref}", ref]
    try:
        for candidate_ref in candidate_refs:
            result = subprocess.run(
                ["git", "show", f"{candidate_ref}:{path}"],
                cwd=ROOT,
                capture_output=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                return hashlib.sha256(result.stdout).hexdigest()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def fetch_raw(repo: str, branch: str, path: str, timeout: int = 20, compare_local: bool = True) -> RawResult:
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
    remote_sha = hashlib.sha256(data).hexdigest()
    local_sha = local_git_blob_sha(branch, path) if compare_local else None
    issues: list[str] = []
    if len(data) > 1000 and len(lines) <= 10:
        issues.append(f"compressed: {len(lines)} physical lines for {len(data)} bytes")
    if max_line > 1000:
        issues.append(f"max line {max_line} > 1000")
    minimum = MIN_LINES.get(path)
    if minimum is not None and len(lines) < minimum:
        issues.append(f"critical file needs >= {minimum} lines, has {len(lines)}")
    if compare_local:
        if local_sha is None:
            issues.append(f"warning: local git ref {branch!r} does not contain {path}")
        elif local_sha != remote_sha:
            issues.append("sha256 mismatch with local git blob")
    return RawResult(
        path=path,
        status="OK" if not issues else "SUSPICIOUS",
        lines=len(lines),
        max_line=max_line,
        bytes=len(data),
        sha256=remote_sha,
        local_sha256=local_sha or "",
        issue="; ".join(issues),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check GitHub raw integrity for AgentLab critical files")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/repo, e.g. Kidrage/AgentLab")
    parser.add_argument(
        "--branch",
        "--ref",
        dest="branch",
        default="main",
        help="Git branch or ref to check",
    )
    parser.add_argument("--fail-on-suspicious", action="store_true")
    parser.add_argument("--no-local-sha", action="store_true", help="Skip local git blob sha256 comparison.")
    parser.add_argument("paths", nargs="*", help="Optional paths to check instead of default critical files")
    args = parser.parse_args(argv)

    paths = args.paths or CRITICAL_FILES
    results = [
        fetch_raw(args.repo, args.branch, path, compare_local=not args.no_local_sha)
        for path in paths
    ]
    suspicious = [r for r in results if r.status != "OK"]
    print(f"Remote raw integrity: repo={args.repo} branch={args.branch}")
    print("Path | Status | Lines | Max Line | Bytes | SHA256 | Local SHA256 | Issue")
    print("--- | --- | ---: | ---: | ---: | --- | --- | ---")
    for result in results:
        print(
            f"{result.path} | {result.status} | {result.lines} | "
            f"{result.max_line} | {result.bytes} | {result.sha256[:12]} | "
            f"{result.local_sha256[:12]} | {result.issue}"
        )
    print(f"Checked {len(results)} files; suspicious={len(suspicious)}")
    if suspicious and args.fail_on_suspicious:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
