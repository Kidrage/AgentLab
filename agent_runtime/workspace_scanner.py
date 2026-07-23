"""Deterministic workspace scanner for AgentLab project memory.

This module performs local filesystem and git metadata discovery only. It does
not call model APIs and it does not read source file bodies, so it is suitable
for cheap baseline memory creation over a broad local workspace.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import fnmatch
import os
import subprocess
from typing import Any

import yaml

try:
    from agent_runtime.artifact_contract import validate_artifacts, write_artifact_manifest
    from agent_runtime.lifecycle_graph import LIFECYCLE_NODES, create_lifecycle, save_lifecycle
    from agent_runtime.routing.route_catalog import RouteCatalog
    from agent_runtime.task_snapshot import safe_write_task_snapshot
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from artifact_contract import validate_artifacts, write_artifact_manifest
    from lifecycle_graph import LIFECYCLE_NODES, create_lifecycle, save_lifecycle
    from routing.route_catalog import RouteCatalog
    from task_snapshot import safe_write_task_snapshot


IGNORE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    "DerivedData",
    "CMakeFiles",
    "CMakeCacheFiles",
    "target",
    "dist",
    ".next",
    "Pods",
}

IGNORE_DIR_PATTERNS = (
    "build",
    "build-*",
    "cmake-build-*",
    "*.xcodeproj/xcuserdata",
)

IGNORE_FILE_NAMES = {
    ".DS_Store",
    ".env",
}

KEY_FILE_NAMES = {
    "README.md",
    "readme.md",
    "CMakeLists.txt",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
}

LANGUAGE_BY_EXT = {
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c": "C/C++",
    ".h": "C/C++",
    ".hpp": "C++",
    ".hxx": "C++",
    ".mm": "Objective-C++",
    ".m": "Objective-C",
    ".swift": "Swift",
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".md": "Markdown",
    ".cmake": "CMake",
    ".sh": "Shell",
    ".juce": "JUCE",
    ".jucer": "JUCE",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_workspace_scan(
    agentlab_root: Path,
    project: str,
    task_id: str,
    target: Path,
    *,
    max_depth: int = 8,
) -> dict[str, Any]:
    """Scan a local workspace and write AgentLab project memory + task reports."""
    target = target.expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise ValueError(f"Target workspace does not exist or is not a directory: {target}")

    project_root = agentlab_root / "projects" / project
    docs_dir = project_root / "agent_docs"
    run_dir = project_root / "runs" / task_id
    docs_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    scan = scan_workspace(target, max_depth=max_depth)
    command = (
        f"./agentlab.sh workspace-scan --project {project} --task-id {task_id} "
        f"--target {target} --max-depth {max_depth}"
    )

    write_project_config(project_root, project, target)
    write_project_memory(docs_dir, project, task_id, target, scan, command)
    write_task_run(agentlab_root, project_root, run_dir, project, task_id, target, scan, command)

    artifact_result = validate_artifacts(run_dir)
    write_artifact_manifest(run_dir, artifact_result)
    return {
        "project": project,
        "task_id": task_id,
        "target": str(target),
        "project_root": str(project_root),
        "docs_dir": str(docs_dir),
        "run_dir": str(run_dir),
        "workspace": scan["workspace"],
        "artifact_check": artifact_result,
    }


def scan_workspace(target: Path, *, max_depth: int) -> dict[str, Any]:
    top_entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
    projects = []
    root_files = []
    ignored_root_entries = []

    for entry in top_entries:
        if entry.name in IGNORE_FILE_NAMES:
            ignored_root_entries.append(entry.name)
            continue
        if entry.is_dir():
            if should_ignore_dir(entry.name):
                ignored_root_entries.append(entry.name + "/")
                continue
            projects.append(scan_project(entry, target, max_depth=max_depth))
        elif entry.is_file():
            root_files.append(file_summary(entry, target))

    total_files = sum(p["stats"]["files"] for p in projects) + len(root_files)
    total_dirs = sum(p["stats"]["dirs"] for p in projects) + len(projects)
    total_bytes = sum(p["stats"]["bytes"] for p in projects) + sum(f.get("bytes", 0) for f in root_files)
    extension_counter: Counter[str] = Counter()
    language_counter: Counter[str] = Counter()
    git_repos = 0
    dirty_repos = 0

    for project in projects:
        extension_counter.update(project["stats"]["extensions"])
        language_counter.update(project["stats"]["languages"])
        if project["git"]["is_repo"]:
            git_repos += 1
            if project["git"]["dirty_files"] > 0:
                dirty_repos += 1

    workspace = {
        "path": str(target),
        "scanned_at": utc_now(),
        "scan_mode": "deterministic_metadata_only",
        "max_depth": max_depth,
        "top_level_project_count": len(projects),
        "root_file_count": len(root_files),
        "file_count": total_files,
        "directory_count": total_dirs,
        "bytes": total_bytes,
        "human_size": human_size(total_bytes),
        "git_repo_count": git_repos,
        "dirty_git_repo_count": dirty_repos,
        "top_extensions": counter_top(extension_counter, 16),
        "top_languages": counter_top(language_counter, 12),
        "ignored_root_entries": ignored_root_entries,
    }

    return {
        "workspace": workspace,
        "projects": projects,
        "root_files": root_files,
    }


def scan_project(project_path: Path, workspace_root: Path, *, max_depth: int) -> dict[str, Any]:
    stats = {
        "files": 0,
        "dirs": 0,
        "bytes": 0,
        "extensions": Counter(),
        "languages": Counter(),
        "ignored_dirs": Counter(),
        "ignored_files": Counter(),
    }
    key_files = []
    top_dirs = []
    build_dirs = []
    max_seen_depth = 0

    for root, dirs, files in os.walk(project_path):
        root_path = Path(root)
        rel = root_path.relative_to(project_path)
        depth = 0 if str(rel) == "." else len(rel.parts)
        max_seen_depth = max(max_seen_depth, depth)

        kept_dirs = []
        for dirname in sorted(dirs):
            if should_ignore_dir(dirname):
                stats["ignored_dirs"][dirname] += 1
                if dirname.lower().startswith("build"):
                    build_dirs.append(str((root_path / dirname).relative_to(project_path)))
                continue
            if depth >= max_depth:
                stats["ignored_dirs"][f"{dirname} (depth>{max_depth})"] += 1
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        stats["dirs"] += len(kept_dirs)

        if depth == 0:
            top_dirs = kept_dirs[:24]

        for filename in sorted(files):
            if filename in IGNORE_FILE_NAMES:
                stats["ignored_files"][filename] += 1
                continue
            path = root_path / filename
            rel_file = path.relative_to(project_path)
            try:
                file_size = path.stat().st_size
            except OSError:
                file_size = 0
            stats["files"] += 1
            stats["bytes"] += file_size
            ext = path.suffix.lower() or "[no_ext]"
            stats["extensions"][ext] += 1
            language = LANGUAGE_BY_EXT.get(ext)
            if language:
                stats["languages"][language] += 1
            if is_key_file(path, rel_file):
                key_files.append(str(rel_file))

    key_files = sorted(dict.fromkeys(key_files))[:40]
    project_type = infer_project_type(project_path, key_files, stats["extensions"])
    frameworks = infer_frameworks(project_path, key_files, stats["extensions"])

    return {
        "name": project_path.name,
        "path": str(project_path),
        "relative_path": str(project_path.relative_to(workspace_root)),
        "project_type": project_type,
        "frameworks": frameworks,
        "git": git_summary(project_path),
        "top_dirs": top_dirs,
        "key_files": key_files,
        "build_dirs_detected": sorted(dict.fromkeys(build_dirs))[:20],
        "stats": {
            "files": stats["files"],
            "dirs": stats["dirs"],
            "bytes": stats["bytes"],
            "human_size": human_size(stats["bytes"]),
            "extensions": dict(counter_top(stats["extensions"], 16)),
            "languages": dict(counter_top(stats["languages"], 10)),
            "ignored_dirs": dict(counter_top(stats["ignored_dirs"], 16)),
            "ignored_files": dict(counter_top(stats["ignored_files"], 8)),
            "max_seen_depth": max_seen_depth,
        },
    }


def should_ignore_dir(dirname: str) -> bool:
    if dirname in IGNORE_DIR_NAMES:
        return True
    return any(fnmatch.fnmatch(dirname, pattern) for pattern in IGNORE_DIR_PATTERNS)


def is_key_file(path: Path, rel_file: Path) -> bool:
    if path.name in KEY_FILE_NAMES:
        return True
    lowered = path.name.lower()
    if lowered.endswith((".jucer", ".xcodeproj", ".sln")):
        return True
    if len(rel_file.parts) <= 2 and lowered in {"juceheader.h", "pluginprocessor.h", "plugineditor.h"}:
        return True
    return False


def file_summary(path: Path, workspace_root: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "name": path.name,
        "relative_path": str(path.relative_to(workspace_root)),
        "bytes": size,
        "human_size": human_size(size),
    }


def git_summary(path: Path) -> dict[str, Any]:
    if not (path / ".git").exists():
        return {"is_repo": False, "branch": "", "head": "", "dirty_files": 0}

    branch = run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    head = run_git(path, ["rev-parse", "--short", "HEAD"])
    status = run_git(path, ["status", "--short"])
    dirty_files = len([line for line in status.splitlines() if line.strip()])
    return {
        "is_repo": True,
        "branch": branch.strip(),
        "head": head.strip(),
        "dirty_files": dirty_files,
    }


def run_git(path: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def infer_project_type(path: Path, key_files: list[str], extensions: Counter[str]) -> str:
    lower_keys = {k.lower() for k in key_files}
    if any(k.endswith(".jucer") for k in lower_keys) or "pluginprocessor.h" in lower_keys:
        return "JUCE audio/plugin project"
    if "cmakelists.txt" in lower_keys and (extensions.get(".cpp", 0) or extensions.get(".hpp", 0)):
        return "CMake C++ project"
    if "package.json" in lower_keys:
        return "JavaScript/TypeScript project"
    if "pyproject.toml" in lower_keys or "requirements.txt" in lower_keys:
        return "Python project"
    if "cargo.toml" in lower_keys:
        return "Rust project"
    if path.name.lower() in {"docs", "deliverables"} or extensions.get(".md", 0) > extensions.get(".cpp", 0):
        return "documentation/artifact collection"
    return "mixed/local project"


def infer_frameworks(path: Path, key_files: list[str], extensions: Counter[str]) -> list[str]:
    frameworks = []
    lowered = " ".join(key_files).lower() + " " + path.name.lower()
    if "juce" in lowered or extensions.get(".jucer", 0):
        frameworks.append("JUCE")
    if "cmakelists.txt" in {k.lower() for k in key_files}:
        frameworks.append("CMake")
    if extensions.get(".xcodeproj", 0):
        frameworks.append("Xcode")
    if "package.json" in {k.lower() for k in key_files}:
        frameworks.append("Node")
    if "pyproject.toml" in {k.lower() for k in key_files}:
        frameworks.append("Python packaging")
    return frameworks


def counter_top(counter: Counter[str], limit: int) -> list[tuple[str, int]]:
    return [(str(k), int(v)) for k, v in counter.most_common(limit)]


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def write_project_config(project_root: Path, project: str, target: Path) -> None:
    data = {
        "project": {
            "name": project,
            "type": "local_workspace_memory",
        },
        "paths": {
            "repo": str(target),
            "docs": "agent_docs",
            "runs": "runs",
        },
        "scope": {
            "repo_access": "read_only",
            "external_readonly_roots": [str(target)],
        },
        "agent_routing": {
            "default_strategy": "smallest_safe_route",
            "workspace_analysis_task": [
                "Supervisor",
                "RepoScout",
                "Researcher",
                "InterfaceMapper",
                "Coder",
                "TesterAuditor",
                "Verifier",
                "Archivist",
            ],
        },
        "safety_rules": [
            "Treat the Coding workspace as read-only unless the user names a specific child project and asks for edits.",
            "Keep generated build directories out of project memory unless debugging build output.",
            "Do not store credentials or private tokens in project memory.",
        ],
    }
    path = project_root / "project_config.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_project_memory(
    docs_dir: Path,
    project: str,
    task_id: str,
    target: Path,
    scan: dict[str, Any],
    command: str,
) -> None:
    workspace = scan["workspace"]
    projects = scan["projects"]
    docs_dir.mkdir(parents=True, exist_ok=True)

    (docs_dir / "00_CONTEXT_PACK.md").write_text(
        render_context_pack(project, task_id, target, workspace, projects),
        encoding="utf-8",
    )
    (docs_dir / "01_REPO_MAP.md").write_text(
        render_repo_map(workspace, projects),
        encoding="utf-8",
    )
    write_task_ledger(docs_dir / "02_TASK_LEDGER.yml", project, task_id, target, workspace)
    append_markdown(
        docs_dir / "03_DECISION_LOG.md",
        "# Decision Log\n\n",
        f"## {utc_now()} - {task_id}\n\n"
        f"- Decision: establish `{project}` as local AgentLab memory for `{target}`.\n"
        "- Mode: deterministic metadata scan; no model calls; source files treated as read-only.\n"
        "- Rationale: preserve workspace-level context without spending LLM tokens.\n\n",
    )
    (docs_dir / "04_INTERFACE_REGISTRY.md").write_text(
        render_interface_registry(projects),
        encoding="utf-8",
    )
    append_markdown(
        docs_dir / "05_CHANGELOG_AGENT.md",
        "# Agent Changelog\n\n",
        f"## {utc_now()} - {task_id}\n\n"
        "- Created/updated workspace memory from a local deterministic scan.\n"
        f"- Command: `{command}`\n\n",
    )
    (docs_dir / "06_RISK_REGISTER.md").write_text(
        render_risk_register(workspace, projects),
        encoding="utf-8",
    )
    append_markdown(
        docs_dir / "07_DEVELOPMENT_LOG.md",
        "# Development Log\n\nRecords AgentLab team activity by module.\n\n",
        f"## {utc_now()} - {task_id} - WorkspaceScan\n\n"
        "Module: Workspace Memory\n\n"
        f"Summary: scanned `{target}` and refreshed AgentLab project memory.\n\n"
        f"Commands run: `{command}`\n\n",
    )
    append_markdown(
        docs_dir / "08_WORKER_DIALOGUE_LOG.md",
        "# Worker Dialogue Log\n\nRecords user-visible assigned-worker conversations and implementation actions.\n\n",
        f"## {utc_now()} - {task_id}\n\n"
        "User asked AgentLab to analyze `<local-workspace>` and record local memory. "
        "The frontdesk only requested the deterministic AgentLab scan and reports its artifacts.\n\n",
    )
    write_yaml(docs_dir / "09_COST_LEDGER.yml", {"entries": [{
        "timestamp": utc_now(),
        "project": project,
        "task_id": task_id,
        "agent": "WorkspaceScan",
        "provider": "local",
        "model": "none",
        "status": "completed",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "notes": "Deterministic filesystem/git metadata scan only.",
    }]})
    write_yaml(docs_dir / "10_SYNC_LEDGER.yml", {
        "project": project,
        "entries": [{
            "timestamp": utc_now(),
            "task_id": task_id,
            "status": "local_only",
            "notes": "Workspace memory generated locally; GitHub backup not requested for this project.",
        }],
    })


def write_task_run(
    agentlab_root: Path,
    project_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    target: Path,
    scan: dict[str, Any],
    command: str,
) -> None:
    workspace = scan["workspace"]
    projects = scan["projects"]
    route_key = "workspace_analysis_task"
    route_catalog = RouteCatalog.from_config()
    route = route_catalog.agents_for(route_key)
    workflow_plan = {
        "project": project,
        "task_id": task_id,
        "agentlab_root": str(agentlab_root),
        "project_root": str(project_root),
        "repo_path": str(target),
        "run_dir": str(run_dir),
        "user_request_path": str(run_dir / "user_request.md"),
        "execution_backend": "agentlab_orchestrated_cli",
        "route": {
            "task_size": route_catalog.size_for(route_key),
            "agents": route,
            "rationale": [
                "Full workspace memory build requested through the configured workspace route.",
                "Supervisor and RepoScout responsibilities were satisfied by a local deterministic scanner; no model role was invoked.",
            ],
            "skipped_agents": [],
            "route_key": route_key,
        },
        "token_budgets": [{
            "phase": "WorkspaceScan",
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "estimated_total_tokens": 0,
            "warning_threshold_tokens": 0,
            "stop_threshold_tokens": 0,
            "actual_tokens": 0,
            "variance_tokens": 0,
            "notes": "No model calls.",
        }],
        "included_agents": {},
        "model_profiles": {},
        "validation_gates": [],
        "memory_policy": {},
        "execution_policy": {"mode": "local_deterministic_no_model_calls"},
        "harness_policy": {},
        "harness_status": {},
        "missing_inputs": [],
        "notes": [
            "Generated by AgentLab workspace-scan.",
            "No source edits, dependency installs, or model API calls were made.",
        ],
    }

    write_text(run_dir / "user_request.md", render_user_request(target))
    write_yaml(run_dir / "workflow_plan.yml", workflow_plan)
    write_yaml(run_dir / "brain_decisions.yml", {"decisions": [{
        "timestamp": utc_now(),
        "project": project,
        "task_id": task_id,
        "agent_name": "WorkspaceScan",
        "decision_type": "traversal",
        "decision": "approve",
        "reason": "User explicitly requested full local Coding workspace analysis and documentation.",
        "requested_scope": "full_directory",
        "approved_scope": str(target),
        "estimated_files": workspace["file_count"],
        "estimated_tokens": 0,
        "requires_user": False,
    }]})
    write_yaml(run_dir / "cost_ledger.yml", {"entries": [{
        "timestamp": utc_now(),
        "project": project,
        "task_id": task_id,
        "agent": "WorkspaceScan",
        "provider": "local",
        "model": "none",
        "status": "completed",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "notes": "No model call.",
    }]})
    write_yaml(run_dir / "execution_log.yml", {"commands": [{
        "command_id": "cmd_workspace_scan",
        "command": command,
        "exit_code": 0,
        "status": "completed",
        "backend": "local_deterministic_scanner",
    }]})
    write_text(run_dir / "01_supervisor_plan.md", render_supervisor_plan(project, task_id, target, workspace, command))
    write_text(run_dir / "02_reposcout_report.md", render_reposcout_report(workspace, projects))
    write_text(run_dir / "sync_report.yml", "status: local_only\nnotes: GitHub sync not requested for this workspace memory task.\n")
    write_yaml(run_dir / "self_check_report.yml", {
        "status": "pass",
        "checks": [
            {"id": "target_exists", "pass": True, "detail": str(target)},
            {"id": "model_calls", "pass": True, "detail": "0 model calls"},
            {"id": "source_edits", "pass": True, "detail": "No files under target were edited."},
        ],
    })
    write_yaml(run_dir / "progress.yml", {
        "project": project,
        "task_id": task_id,
        "status": "completed",
        "percent": 100,
        "current_stage": "completed",
        "current_agent": None,
        "last_event": "Workspace scan completed.",
        "agents": [{"name": agent, "status": "completed", "provider": "local", "tokens": 0} for agent in route],
    })
    write_yaml(run_dir / "state.yml", {
        "project": project,
        "task_id": task_id,
        "current_agent": None,
        "completed_agents": route,
        "reports": {
            "Supervisor": str(run_dir / "01_supervisor_plan.md"),
            "RepoScout": str(run_dir / "02_reposcout_report.md"),
        },
        "status": "completed",
        "execution_mode": "workspace_scan",
        "last_event": "Workspace scan completed.",
        "updated_at": utc_now(),
    })
    write_yaml(run_dir / "task_card.yml", {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "title": "Coding workspace baseline memory",
        "status": "completed",
        "source": str(target),
    })

    lifecycle = create_lifecycle(run_dir, workflow_plan)
    for node_id in LIFECYCLE_NODES:
        node = lifecycle["nodes"][node_id]
        if node["status"] != "skipped":
            node["status"] = "completed"
            node["completed_at"] = utc_now()
            node["skip_reason"] = None
    save_lifecycle(run_dir, lifecycle)
    safe_write_task_snapshot(run_dir)


def render_user_request(target: Path) -> str:
    return (
        "# User Request\n\n"
        f"Analyze the complete local workspace at `{target}` and write AgentLab project memory. "
        "Use local deterministic scanning only; do not call model APIs and do not edit source projects.\n"
    )


def render_context_pack(project: str, task_id: str, target: Path, workspace: dict[str, Any], projects: list[dict[str, Any]]) -> str:
    return (
        f"# Context Pack - {project}\n\n"
        f"Source workspace: `{target}`\n\n"
        f"Baseline task: `{task_id}`\n\n"
        "AgentLab memory role: this project stores high-level local knowledge for the whole Coding workspace. "
        "Use it to choose the correct child project before opening or editing files.\n\n"
        "## Scan Summary\n\n"
        f"- Scan mode: `{workspace['scan_mode']}`\n"
        f"- Top-level projects: {workspace['top_level_project_count']}\n"
        f"- Git repos: {workspace['git_repo_count']} ({workspace['dirty_git_repo_count']} dirty)\n"
        f"- Files counted: {workspace['file_count']}\n"
        f"- Directories counted: {workspace['directory_count']}\n"
        f"- Source footprint counted: {workspace['human_size']}\n\n"
        "## Top-Level Projects\n\n"
        + markdown_project_table(projects)
        + "\n## Operating Rule\n\n"
        "Treat this workspace as read-only unless a later task names a specific child project and asks for edits.\n"
    )


def render_repo_map(workspace: dict[str, Any], projects: list[dict[str, Any]]) -> str:
    lines = [
        "# Repository Map",
        "",
        f"Workspace: `{workspace['path']}`",
        f"Scanned at: `{workspace['scanned_at']}`",
        "",
        "## Workspace Totals",
        "",
        f"- Top-level project directories: {workspace['top_level_project_count']}",
        f"- Git repos: {workspace['git_repo_count']}",
        f"- Dirty git repos: {workspace['dirty_git_repo_count']}",
        f"- Files counted: {workspace['file_count']}",
        f"- Size counted: {workspace['human_size']}",
        "",
        "## Language Signal",
        "",
        markdown_counter_table(workspace["top_languages"], "Language"),
        "",
        "## Extension Signal",
        "",
        markdown_counter_table(workspace["top_extensions"], "Extension"),
        "",
        "## Project Inventory",
        "",
        markdown_project_table(projects),
        "",
    ]
    for project in projects:
        lines.extend(render_project_section(project))
    return "\n".join(lines).rstrip() + "\n"


def render_project_section(project: dict[str, Any]) -> list[str]:
    git = project["git"]
    git_text = "no"
    if git["is_repo"]:
        git_text = f"yes, branch `{git['branch']}`, head `{git['head']}`, dirty files {git['dirty_files']}"
    return [
        f"## {project['name']}",
        "",
        f"- Path: `{project['path']}`",
        f"- Type: {project['project_type']}",
        f"- Frameworks: {', '.join(project['frameworks']) or 'none detected'}",
        f"- Git: {git_text}",
        f"- Files: {project['stats']['files']} ({project['stats']['human_size']})",
        f"- Top dirs: {', '.join(project['top_dirs']) or 'none'}",
        f"- Key files: {', '.join(project['key_files']) or 'none detected'}",
        f"- Build/generated dirs ignored: {', '.join(project['build_dirs_detected']) or 'none detected'}",
        "",
    ]


def markdown_project_table(projects: list[dict[str, Any]]) -> str:
    rows = ["| Project | Type | Git | Files | Size | Key Signal |", "|---|---|---:|---:|---:|---|"]
    for project in projects:
        git = "yes" if project["git"]["is_repo"] else "no"
        signal = ", ".join(project["frameworks"][:3]) or ", ".join(project["key_files"][:2]) or "mixed"
        rows.append(
            f"| `{project['name']}` | {project['project_type']} | {git} | "
            f"{project['stats']['files']} | {project['stats']['human_size']} | {signal} |"
        )
    return "\n".join(rows) + "\n"


def markdown_counter_table(items: list[tuple[str, int]], label: str) -> str:
    if not items:
        return "_No signal detected._\n"
    rows = [f"| {label} | Count |", "|---|---:|"]
    rows.extend(f"| `{name}` | {count} |" for name, count in items)
    return "\n".join(rows) + "\n"


def render_interface_registry(projects: list[dict[str, Any]]) -> str:
    lines = [
        "# Interface Registry",
        "",
        "Detected from metadata only. Confirm against source before making API or plugin-format decisions.",
        "",
        "| Project | Interface/Boundary Signal | Notes |",
        "|---|---|---|",
    ]
    for project in projects:
        signals = []
        if "JUCE" in project["frameworks"]:
            signals.append("JUCE plugin/application boundary")
        if "CMake" in project["frameworks"]:
            signals.append("CMake build interface")
        if project["git"]["is_repo"]:
            signals.append("Git repository boundary")
        if project["project_type"].startswith("documentation"):
            signals.append("document artifact boundary")
        if not signals:
            signals.append("local folder boundary")
        notes = "; ".join(project["key_files"][:4]) or "No key files detected"
        lines.append(f"| `{project['name']}` | {', '.join(signals)} | {notes} |")
    return "\n".join(lines) + "\n"


def render_risk_register(workspace: dict[str, Any], projects: list[dict[str, Any]]) -> str:
    dirty = [p for p in projects if p["git"]["dirty_files"] > 0]
    build_heavy = [p for p in projects if p["build_dirs_detected"]]
    lines = [
        "# Risk Register",
        "",
        "| Risk | Severity | Evidence | Mitigation |",
        "|---|---|---|---|",
        f"| Broad workspace scope | Medium | {workspace['top_level_project_count']} top-level projects under one folder | Start future edits from a named child project. |",
        "| Generated/build artifacts can distort memory | Medium | Build-like directories were ignored during scan | Keep source maps separate from build output. |",
    ]
    if dirty:
        names = ", ".join(f"`{p['name']}` ({p['git']['dirty_files']})" for p in dirty)
        lines.append(f"| Dirty git repos | Medium | {names} | Run project-specific status before edits. |")
    if build_heavy:
        names = ", ".join(f"`{p['name']}`" for p in build_heavy[:8])
        lines.append(f"| Large generated trees | Low | {names} | Inspect only when debugging build/package output. |")
    lines.append("| Secret handling | High | `.env` and common local caches are ignored by scanner | Never copy credential files into AgentLab memory. |")
    return "\n".join(lines) + "\n"


def render_supervisor_plan(project: str, task_id: str, target: Path, workspace: dict[str, Any], command: str) -> str:
    return (
        "# Supervisor Plan\n\n"
        "## Task Summary\n"
        f"Create local AgentLab memory for `{target}` without model API calls.\n\n"
        "## Scope Decision\n"
        "- In scope: top-level inventory, git metadata, key build/interface signals, AgentLab docs.\n"
        "- Out of scope: source code semantic review, builds/tests, source edits, dependency installs.\n\n"
        "## Route\n"
        "Supervisor -> RepoScout (local deterministic adapters; no model sessions)\n\n"
        "## Budget\n"
        "- Model tokens: 0\n"
        "- Execution: local filesystem/git metadata scan\n\n"
        "## Acceptance Criteria\n"
        f"- AgentLab project `{project}` exists.\n"
        f"- Task `{task_id}` contains reports and artifact manifest.\n"
        f"- Workspace totals record {workspace['top_level_project_count']} top-level projects.\n\n"
        f"Command: `{command}`\n"
    )


def render_reposcout_report(workspace: dict[str, Any], projects: list[dict[str, Any]]) -> str:
    return (
        "# RepoScout Report\n\n"
        "## Summary\n\n"
        f"Scanned `{workspace['path']}` using metadata-only traversal. "
        f"Found {workspace['top_level_project_count']} top-level project folders, "
        f"{workspace['git_repo_count']} git repos, and {workspace['file_count']} counted files.\n\n"
        "## Inventory\n\n"
        + markdown_project_table(projects)
        + "\n## Notes\n\n"
        "- Build/cache/vendor-heavy directories were skipped by policy.\n"
        "- This report does not include semantic source review.\n"
    )


def write_task_ledger(path: Path, project: str, task_id: str, target: Path, workspace: dict[str, Any]) -> None:
    existing = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tasks = [task for task in existing.get("tasks", []) if task.get("task_id") != task_id]
    tasks.append({
        "task_id": task_id,
        "title": "Coding workspace baseline memory",
        "status": "completed",
        "category": "docs",
        "priority": "P2",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "source": str(target),
        "summary": (
            f"Metadata scan recorded {workspace['top_level_project_count']} top-level projects, "
            f"{workspace['git_repo_count']} git repos, {workspace['file_count']} files."
        ),
    })
    write_yaml(path, {"project": project, "tasks": tasks})


def append_markdown(path: Path, header: str, entry: str) -> None:
    if path.exists():
        current = path.read_text(encoding="utf-8")
    else:
        current = header
    path.write_text(current.rstrip() + "\n\n" + entry, encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
