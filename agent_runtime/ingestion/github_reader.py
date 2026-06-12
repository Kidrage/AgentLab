"""GitHub API-first repository reader."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import fnmatch
import json
import os
import re
from typing import Any
from urllib import parse, request

from .repo_manifest import RepoManifest
from .repo_manifest import write_repo_manifest
from .repo_policy import load_repo_ingestion_policy
from .resource_ledger import ResourceLedger, write_resource_ledger

GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"

KEY_FILE_NAMES = {
    "CMakeLists.txt",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
}


@dataclass
class GitHubRepoRef:
    owner: str
    repo: str
    ref: str = "main"
    repo_url: str = ""
    kind: str | None = None
    path: str | None = None


@dataclass
class RepoTree:
    entries: list[dict[str, Any]]
    truncated: bool = False


@dataclass
class RawFileResult:
    path: str
    content: str | None
    bytes_downloaded: int = 0
    skipped: bool = False
    reason: str | None = None


GITHUB_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/(?:tree|blob)/[^\s)\]}>\"']+)?")


def extract_github_urls(text: str) -> list[str]:
    """Extract unique github.com owner/repo URLs from free text.

    Supports plain repository URLs and tree/blob URLs. Trailing punctuation from
    prose/Markdown is stripped while preserving path components.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for match in GITHUB_URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;:")
        try:
            parse_github_url(url)
        except ValueError:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_github_url(url: str) -> GitHubRepoRef:
    parsed = parse.urlparse(url)
    if parsed.netloc.lower() != "github.com":
        raise ValueError("only github.com URLs are supported")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitHub URL must include owner and repo")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    ref = "main"
    kind = None
    subpath = None
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        kind = parts[2]
        ref = parts[3]
        if len(parts) > 4:
            subpath = "/".join(parts[4:])
    return GitHubRepoRef(owner=owner, repo=repo, ref=ref, repo_url=f"https://github.com/{owner}/{repo}", kind=kind, path=subpath)


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "AgentLab-RepoManifest",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(url: str) -> dict[str, Any]:
    req = request.Request(url, headers=_headers())
    with request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def fetch_repo_tree(repo_ref: GitHubRepoRef, recursive: bool = True) -> RepoTree:
    recursive_flag = "1" if recursive else "0"
    url = f"{GITHUB_API}/repos/{repo_ref.owner}/{repo_ref.repo}/git/trees/{repo_ref.ref}?recursive={recursive_flag}"
    data = _request_json(url)
    return RepoTree(entries=list(data.get("tree") or []), truncated=bool(data.get("truncated", False)))


def fetch_resolved_commit(repo_ref: GitHubRepoRef) -> str | None:
    """Resolve a branch/tag ref to a commit sha via GitHub API.

    Tree URLs may provide a tree SHA elsewhere; this function only returns a
    commit SHA when the ref API exposes one. Callers must warn rather than guess.
    """
    ref = parse.quote(repo_ref.ref, safe="/")
    url = f"{GITHUB_API}/repos/{repo_ref.owner}/{repo_ref.repo}/git/ref/heads/{ref}"
    data = _request_json(url)
    obj = data.get("object") if isinstance(data, dict) else {}
    sha = obj.get("sha") if isinstance(obj, dict) else None
    return str(sha) if sha else None


def _raw_url(repo_ref: GitHubRepoRef, path: str) -> str:
    quoted_path = "/".join(parse.quote(part) for part in path.split("/"))
    return f"https://raw.githubusercontent.com/{repo_ref.owner}/{repo_ref.repo}/{repo_ref.ref}/{quoted_path}"


def fetch_raw_file(repo_ref: GitHubRepoRef, path: str) -> RawFileResult:
    req = request.Request(_raw_url(repo_ref, path), headers={"User-Agent": "AgentLab-RepoManifest"})
    with request.urlopen(req, timeout=30) as response:
        raw = response.read()
    try:
        return RawFileResult(path=path, content=raw.decode("utf-8"), bytes_downloaded=len(raw))
    except UnicodeDecodeError:
        return RawFileResult(path=path, content=None, bytes_downloaded=len(raw), skipped=True, reason="binary")


def _is_key_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    lower = path.lower()
    if name.startswith("README."):
        return True
    if name in KEY_FILE_NAMES:
        return True
    if fnmatch.fnmatch(path, ".github/workflows/*"):
        return True
    if fnmatch.fnmatch(path, "docs/*.md"):
        return True
    return lower == "readme"


def _matches_exclude(path: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return pattern
    return None


def _entry_size(entry: dict[str, Any]) -> int | None:
    try:
        return int(entry.get("size"))
    except (TypeError, ValueError):
        return None


def build_repo_manifest(
    repo_url: str,
    mode: str = "repo_profile",
    *,
    agentlab_root: Any = None,
    policy: dict[str, Any] | None = None,
) -> RepoManifest:
    """Build an API-only RepoManifest with targeted key-file fetches."""
    repo_ref = parse_github_url(repo_url)
    policy = policy or load_repo_ingestion_policy(agentlab_root)
    limits = policy.get("limits", {})
    excludes = list(policy.get("default_excludes") or [])
    max_files = int(limits.get("max_files_read") or 100)
    max_single_bytes = int(limits.get("max_single_file_kb") or 256) * 1024
    max_total_bytes = int(limits.get("max_total_text_mb") or 5) * 1024 * 1024
    max_tree_entries = int(limits.get("max_api_tree_entries") or 100000)

    manifest = RepoManifest(repo_url=repo_ref.repo_url, owner=repo_ref.owner, repo=repo_ref.repo, ref=repo_ref.ref)
    if mode == "repo_profile":
        manifest.clone_performed = False

    try:
        manifest.resolved_commit = fetch_resolved_commit(repo_ref)
    except Exception:
        manifest.resolved_commit = None
    if not manifest.resolved_commit:
        manifest.warnings.append("resolved_commit_unavailable")

    tree = fetch_repo_tree(repo_ref, recursive=True)
    manifest.tree_truncated = tree.truncated
    manifest.files_seen = len(tree.entries)
    if len(tree.entries) > max_tree_entries:
        manifest.tree_truncated = True
        manifest.warnings.append("API tree entry limit exceeded; targeted fetch list was truncated.")

    for entry in tree.entries[:max_tree_entries]:
        if entry.get("type") != "blob":
            continue
        path = str(entry.get("path") or "")
        if not path:
            continue
        pattern = _matches_exclude(path, excludes)
        if pattern:
            manifest.files_skipped_by_policy.append({"path": path, "reason": f"excluded by {pattern}"})
            continue
        if not _is_key_file(path):
            continue
        size = _entry_size(entry)
        if size is not None and size > max_single_bytes:
            manifest.files_skipped_by_policy.append({"path": path, "reason": "max_single_file_kb exceeded", "size": size})
            continue
        if len(manifest.files_read) >= max_files:
            manifest.warnings.append("max_files_read reached; remaining key files were skipped.")
            break
        if manifest.bytes_downloaded >= max_total_bytes:
            manifest.warnings.append("max_total_text_mb reached; remaining key files were skipped.")
            break
        result = fetch_raw_file(repo_ref, path)
        if result.skipped:
            manifest.files_skipped_by_policy.append({"path": path, "reason": result.reason or "skipped"})
            manifest.bytes_downloaded += result.bytes_downloaded
            continue
        if result.bytes_downloaded > max_single_bytes:
            manifest.files_skipped_by_policy.append({"path": path, "reason": "max_single_file_kb exceeded", "size": result.bytes_downloaded})
            manifest.bytes_downloaded += result.bytes_downloaded
            continue
        manifest.files_read.append({"path": path, "bytes": result.bytes_downloaded})
        manifest.bytes_downloaded += result.bytes_downloaded

    if mode != "repo_profile":
        manifest.warnings.append("Manifest was built API-first; clone decisions must pass clone_guard separately.")
    return manifest


def write_repo_ingestion_artifacts(run_dir: Any, task_id: str, manifest: RepoManifest) -> tuple[Any, Any]:
    """Write repo_manifest.json and matching resource_ledger.yml."""
    manifest_path = write_repo_manifest(run_dir, manifest)
    ledger = ResourceLedger.from_manifest(task_id, manifest)
    ledger_path = write_resource_ledger(run_dir, ledger)
    return manifest_path, ledger_path
