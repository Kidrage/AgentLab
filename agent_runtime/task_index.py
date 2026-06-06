"""AgentLab Task Discovery & Resume Index — Index Builder.

Scans project task run directories and builds:
- project-level task_index.yml
- per-task artifact_manifest.yml
- per-task task_card.yml

All operations are local-only; no LLM/API calls required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from atomic_io import atomic_write_yaml
from policies import assert_path_allowed, resolve_agentlab_root
from task_snapshot import build_task_snapshot, write_task_snapshot


# ─── Policy loading ───────────────────────────────────────────────────────

def _load_policy(agentlab_root: Path) -> dict:
    """Load task_index_policy.yml or return safe defaults."""
    policy_path = agentlab_root / "config" / "task_index_policy.yml"
    if policy_path.exists():
        try:
            return yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return _default_policy()


def _default_policy() -> dict:
    return {
        "scan": {"max_file_bytes": 65536, "max_artifact_summary_chars": 600, "ignore_dirs": [".git", ".venv", "node_modules", "__pycache__"], "ignore_files": [".env", "*.key", "*.pem"]},
        "search": {"default_limit": 10, "min_score": 1.0, "use_char_ngrams_for_cjk": True, "cjk_ngram_size": 2},
        "status": {"terminal_statuses": ["completed", "archived", "failed"], "resumable_statuses": ["paused", "blocked", "recoverable", "running"]},
    }


# ─── Path helpers ─────────────────────────────────────────────────────────

def project_root(agentlab_root: Path, project: str) -> Path:
    return assert_path_allowed(agentlab_root / "projects" / project, agentlab_root)


def run_dir_for_task(agentlab_root: Path, project: str, task_id: str) -> Path:
    return assert_path_allowed(agentlab_root / "projects" / project / "runs" / task_id, agentlab_root)


def list_task_run_dirs(project_root: Path) -> list[Path]:
    """List all task_* directories under the runs folder."""
    runs_dir = project_root / "runs"
    if not runs_dir.is_dir():
        return []
    return sorted([p for p in runs_dir.iterdir() if p.is_dir() and p.name.startswith("task_")], key=lambda p: p.name)


# ─── Safe file reading ────────────────────────────────────────────────────

def _read_safe_file(path: Path, max_bytes: int = 65536) -> Optional[str]:
    """Read file content or return None if unreadable/oversized."""
    try:
        if not path.exists() or not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_yaml_safe(path: Path) -> Optional[dict]:
    """Parse YAML or return None on error."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _extract_summary(text: str, max_chars: int = 600) -> str:
    """Extract first meaningful paragraph as summary."""
    if not text:
        return ""
    lines = text.split("\n")
    content_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(">"):
            if content_lines:
                break
            continue
        content_lines.append(stripped)
    result = " ".join(content_lines)
    if len(result) > max_chars:
        result = result[:max_chars - 3] + "..."
    return result


# ─── Status normalization ─────────────────────────────────────────────────

def _normalize_status(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    status = str(raw).strip().lower()
    aliases = {
        "complete": "completed",
        "done": "completed",
        "in_progress": "running",
        "in-progress": "running",
        "failed_recoverable": "recoverable",
    }
    status = aliases.get(status, status)
    valid = {"new", "planned", "running", "paused", "blocked", "recoverable", "completed", "failed", "archived"}
    return status if status in valid else "unknown"


def _resolve_resume_state(record: dict, run_dir: Path, policy: dict) -> str:
    """Determine resume state from available artifacts."""
    if (run_dir / "resume_plan.yml").exists():
        return "recoverable"
    user_decision = run_dir / "USER_DECISION_REQUIRED.md"
    if user_decision.exists():
        content = _read_safe_file(user_decision, 65536)
        if content and len(content.strip()) > 20:
            return "manual_decision_needed"
    incidents = run_dir / "provider_incidents.yml"
    if incidents.exists():
        return "provider_paused"
    progress = record.get("progress", {})
    if progress.get("provider_status", {}).get("paused_for_provider"):
        return "provider_paused"
    status = record.get("status_raw", "")
    if status in ("paused", "blocked", "recoverable"):
        return "recoverable"
    if status in ("completed", "archived"):
        return "completed"
    if status == "failed":
        return "not_recoverable"
    return "unknown"


def _can_resume(resume_state: str) -> bool:
    return resume_state in ("recoverable", "manual_decision_needed", "provider_paused", "blocked")


# ─── Query terms extraction ───────────────────────────────────────────────

def _extract_query_terms(user_request_text: str, title: str, summary: str) -> list[str]:
    """Build a list of searchable query terms from task content."""
    terms = set()
    source = f"{title} {summary} {user_request_text}"
    source_lower = source.lower()
    # Simple English keywords
    english_keywords = ["codex", "driver", "handoff", "resume", "backup", "api", "agent", "task",
                        "full", "model", "tier", "guard", "failover", "sync", "check", "chat",
                        "terminal", "web", "ui", "patch", "plugin", "config", "external"]
    for kw in english_keywords:
        if kw in source_lower:
            terms.add(kw)
    # Chinese CJK bigrams
    cjk_chars = [c for c in source if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff']
    for i in range(len(cjk_chars) - 1):
        terms.add(cjk_chars[i] + cjk_chars[i + 1])
    return sorted(list(terms))[:50]


# ─── Build artifact manifest ──────────────────────────────────────────────

_KIND_MAP = {
    "user_request": {"kind": "request", "agent": "user", "important": True},
    "supervisor_plan": {"kind": "plan", "agent": "Supervisor", "important": True},
    "reposcout_report": {"kind": "scout", "agent": "RepoScout", "important": False},
    "research_notes": {"kind": "research", "agent": "Researcher", "important": False},
    "interface_map": {"kind": "interface", "agent": "InterfaceMapper", "important": False},
    "codex_prompt": {"kind": "prompt", "agent": "CodexPromptGen", "important": False},
    "implementation_report": {"kind": "implementation", "agent": "Coder", "important": True},
    "validation_report": {"kind": "validation", "agent": "TesterAuditor", "important": True},
    "audit_report": {"kind": "audit", "agent": "TesterAuditor", "important": True},
    "archive_update": {"kind": "archive", "agent": "Archivist", "important": False},
    "handoff_packet": {"kind": "handoff", "agent": "system", "important": True},
    "workflow_plan": {"kind": "plan", "agent": "system", "important": True},
    "task_snapshot": {"kind": "snapshot", "agent": "system", "important": True},
}


def build_artifact_manifest(run_dir: Path, max_bytes: int = 65536, max_summary: int = 600) -> dict:
    """Build artifact_manifest.yml for a single task."""
    artifacts = []
    for filename, meta in _KIND_MAP.items():
        # Map to actual file
        file_map = {
            "user_request": "user_request.md",
            "supervisor_plan": "01_supervisor_plan.md",
            "reposcout_report": "02_reposcout_report.md",
            "research_notes": "03_research_notes.md",
            "interface_map": "04_interface_map.md",
            "codex_prompt": "05_codex_prompt.md",
            "implementation_report": "06_implementation_report.md",
            "validation_report": "07_validation_report.md",
            "audit_report": "08_audit_report.md",
            "archive_update": "09_archive_update.md",
            "handoff_packet": "handoff_packet.yml",
            "workflow_plan": "workflow_plan.yml",
            "task_snapshot": "task_snapshot.yml",
        }
        path = run_dir / file_map.get(filename, f"{filename}.md")
        exists = path.exists()
        summary = ""
        title = meta.get("kind", filename).title()
        if exists:
            content = _read_safe_file(path, max_bytes)
            if content:
                summary = _extract_summary(content, max_summary)
        artifacts.append({
            "kind": meta["kind"],
            "agent": meta["agent"],
            "path": path.name,
            "status": "present" if exists else "missing",
            "title": title,
            "summary": summary,
            "important": meta["important"],
        })

    # Count missing important artifacts
    present_count = sum(1 for a in artifacts if a["status"] == "present")
    missing_count = sum(1 for a in artifacts if a["status"] == "missing")
    important_missing = [a["path"] for a in artifacts if a["important"] and a["status"] == "missing"]

    return {
        "version": 1,
        "project": run_dir.parent.parent.name,
        "task_id": run_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "summary": {"present": present_count, "missing": missing_count, "important_missing": important_missing},
    }


# ─── Build task record ────────────────────────────────────────────────────

def build_task_record(agentlab_root: Path, project: str, run_dir: Path, policy: Optional[dict] = None) -> dict:
    """Build a complete task record for task_index.yml."""
    if policy is None:
        policy = _load_policy(agentlab_root)
    scan_cfg = policy.get("scan", {})
    max_bytes = scan_cfg.get("max_file_bytes", 65536)
    max_summary = scan_cfg.get("max_artifact_summary_chars", 600)

    task_id = run_dir.name

    # Load state
    state_data = _read_yaml_safe(run_dir / "state.yml") or {}
    progress_data = _read_yaml_safe(run_dir / "progress.yml") or {}
    plan_data = _read_yaml_safe(run_dir / "workflow_plan.yml") or {}
    user_req = _read_safe_file(run_dir / "user_request.md", max_bytes) or ""
    try:
        snapshot = build_task_snapshot(run_dir, project=project, task_id=task_id)
    except Exception:
        snapshot = {}

    # Extract title from user_request
    title = ""
    if user_req:
        for line in user_req.split("\n"):
            line = line.strip()
            if line.startswith("#") and "request" not in line.lower():
                title = line.lstrip("# ").strip()
                if len(title) > 3:
                    break
    if not title:
        title = task_id

    summary = _extract_summary(user_req, max_summary)
    status = _normalize_status(snapshot.get("status") or state_data.get("status") or progress_data.get("status"))
    percent = snapshot.get("percent_complete", progress_data.get("percent_complete") or progress_data.get("percent") or 0)
    route = snapshot.get("route") or (plan_data.get("route", {}).get("agents", []) if isinstance(plan_data.get("route"), dict) else [])
    current_agent = snapshot.get("current_agent") or state_data.get("current_agent") or progress_data.get("current_agent")
    current_stage = snapshot.get("current_stage") or progress_data.get("current_stage") or progress_data.get("current_agent")
    last_event = snapshot.get("last_event") or state_data.get("last_event") or progress_data.get("last_event", "")
    last_checkpoint = state_data.get("last_checkpoint")

    # Backup info
    sync_data = _read_yaml_safe(run_dir / "sync" / "github_sync_report.yml") or {}
    github_synced = sync_data.get("status") == "pushed" or sync_data.get("commit") is not None

    handoff_data = _read_yaml_safe(run_dir / "handoff_packet.yml") or {}
    github_commit = handoff_data.get("backup", {}).get("push_commit") or sync_data.get("commit")

    query_terms = _extract_query_terms(user_req, title, summary)
    resume_state = _resolve_resume_state({"status_raw": status, "progress": progress_data}, run_dir, policy)

    # Artifact manifest
    manifest = build_artifact_manifest(run_dir, max_bytes, max_summary)

    record = {
        "task_id": task_id,
        "title": title,
        "summary": summary,
        "status": status,
        "resume_state": resume_state,
        "can_resume": _can_resume(resume_state),
        "project": project,
        "created_at": state_data.get("created_at", ""),
        "updated_at": state_data.get("updated_at", ""),
        "priority": state_data.get("priority", "P2"),
        "category": state_data.get("category", ""),
        "risk_level": state_data.get("risk_level", ""),
        "route": route,
        "current_agent": current_agent,
        "current_stage": current_stage,
        "percent_complete": percent,
        "last_event": last_event,
        "last_checkpoint": last_checkpoint,
        "query_terms": query_terms,
        "paths": {
            "run_dir": str(run_dir),
            "user_request": "user_request.md",
            "workflow_plan": "workflow_plan.yml",
            "progress": "progress.yml",
            "state": "state.yml",
            "artifact_manifest": "artifact_manifest.yml",
            "task_card": "task_card.yml",
            "task_snapshot": "task_snapshot.yml",
        },
        "artifacts": manifest["artifacts"],
        "artifact_summary": manifest["summary"],
        "backup_status": {
            "github_synced": github_synced,
            "github_commit": github_commit,
            "truenas_synced": False,
            "last_sync_at": sync_data.get("sync_timestamp", ""),
        },
        "commands": {
            "open": f"./agentlab.sh task-open --project {project} --task-id {task_id}",
            "resume": f"./agentlab.sh resume --project {project} --task-id {task_id}",
            "chat_attach": f"./agentlab.sh chat --project {project} --task-id {task_id}",
        },
    }
    return record


# ─── Build project-level index ────────────────────────────────────────────

def build_project_task_index(agentlab_root: Path, project: str, rebuild: bool = False) -> dict:
    """Scan all task run dirs and build/update task_index.yml."""
    proot = project_root(agentlab_root, project)
    runs = list_task_run_dirs(proot)
    policy = _load_policy(agentlab_root)

    tasks = []
    for run_dir in runs:
        try:
            record = build_task_record(agentlab_root, project, run_dir, policy)
            tasks.append(record)
        except Exception:
            # Skip broken tasks; don't crash the whole index
            continue

    index = {
        "version": 1,
        "project": project,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(proot / "runs"),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    return index


def load_project_task_index(agentlab_root: Path, project: str) -> Optional[dict]:
    """Load the cached task_index.yml for a project."""
    path = agentlab_root / "projects" / project / "task_index.yml"
    if not path.exists():
        return None
    return _read_yaml_safe(path)


def save_project_task_index(agentlab_root: Path, project: str, index: dict) -> Path:
    """Write task_index.yml atomically."""
    path = agentlab_root / "projects" / project / "task_index.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(path, index)
    return path


def ensure_project_task_index(agentlab_root: Path, project: str) -> dict:
    """Return cached index or build a fresh one."""
    cached = load_project_task_index(agentlab_root, project)
    run_count = len(list_task_run_dirs(project_root(agentlab_root, project)))
    if cached and cached.get("tasks") and cached.get("task_count") == run_count:
        return cached
    index = rebuild_index(agentlab_root, project)
    return index


def generate_per_task_artifacts(agentlab_root: Path, project: str, task_id: str) -> tuple[Path, Path]:
    """Generate artifact_manifest.yml and task_card.yml for one task."""
    run_dir = run_dir_for_task(agentlab_root, project, task_id)
    policy = _load_policy(agentlab_root)
    write_task_snapshot(run_dir, project=project, task_id=task_id)

    # artifact_manifest
    manifest = build_artifact_manifest(run_dir)
    manifest_path = run_dir / "artifact_manifest.yml"
    atomic_write_yaml(manifest_path, manifest)

    # task_card
    record = build_task_record(agentlab_root, project, run_dir, policy)
    card = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "title": record["title"],
        "summary": record["summary"],
        "status": record["status"],
        "resume_state": record["resume_state"],
        "can_resume": record["can_resume"],
        "percent_complete": record["percent_complete"],
        "current_agent": record["current_agent"],
        "current_stage": record["current_stage"],
        "last_event": record["last_event"],
        "last_event_at": record["updated_at"],
        "important_paths": {
            "run_dir": str(run_dir),
            "user_request": "user_request.md",
            "progress": "progress.yml",
            "workflow_plan": "workflow_plan.yml",
            "task_snapshot": "task_snapshot.yml",
            "handoff_packet": "handoff_packet.yml",
        },
        "commands": record["commands"],
        "artifact_summary": record["artifact_summary"],
        "backup_status": record["backup_status"],
    }
    card_path = run_dir / "task_card.yml"
    atomic_write_yaml(card_path, card)

    return manifest_path, card_path


def sync_task_ledger(agentlab_root: Path, project: str, index: dict | None = None) -> Path:
    """Synchronize agent_docs/02_TASK_LEDGER.yml from real run folders.

    This keeps the long-term task ledger aligned with the local source of truth
    (`runs/task_*`) while preserving existing custom fields such as subtasks and
    dependencies.
    """
    proot = project_root(agentlab_root, project)
    docs = proot / "agent_docs"
    docs.mkdir(parents=True, exist_ok=True)
    ledger_path = docs / "02_TASK_LEDGER.yml"
    ledger = _read_yaml_safe(ledger_path) or {
        "version": 1,
        "project": project,
        "description": "",
        "tasks": [],
    }
    index = index or build_project_task_index(agentlab_root, project)
    existing_by_id = {
        str(task.get("task_id")): dict(task)
        for task in ledger.get("tasks", []) or []
        if task.get("task_id")
    }

    synced_tasks = []
    seen = set()
    for record in index.get("tasks", []) or []:
        task_id = str(record.get("task_id"))
        if not task_id:
            continue
        seen.add(task_id)
        previous = existing_by_id.get(task_id, {})
        entry = dict(previous)
        entry.update({
            "task_id": task_id,
            "title": record.get("title") or previous.get("title") or task_id,
            "description": record.get("summary") or previous.get("description", ""),
            "status": record.get("status") or previous.get("status") or "unknown",
            "priority": previous.get("priority", record.get("priority", "P2")),
            "category": previous.get("category", record.get("category", "")),
            "depends_on": previous.get("depends_on", []),
            "subtasks": previous.get("subtasks", []),
            "created_at": previous.get("created_at", record.get("created_at", "")),
            "updated_at": record.get("updated_at") or previous.get("updated_at", ""),
            "source_run_dir": record.get("paths", {}).get("run_dir", ""),
            "can_resume": bool(record.get("can_resume", False)),
            "artifact_summary": record.get("artifact_summary", {}),
        })
        synced_tasks.append(entry)

    # Preserve legacy ledger-only tasks after run-backed tasks.
    for task_id, task in existing_by_id.items():
        if task_id not in seen:
            synced_tasks.append(task)

    ledger["version"] = ledger.get("version", 1)
    ledger["project"] = project
    ledger["generated_from_runs_at"] = datetime.now(timezone.utc).isoformat()
    ledger["task_count"] = len(synced_tasks)
    ledger["tasks"] = synced_tasks
    atomic_write_yaml(ledger_path, ledger)
    return ledger_path


def rebuild_index(agentlab_root: Path, project: str) -> dict:
    """Full rebuild: index + per-task manifests + cards."""
    proot = project_root(agentlab_root, project)
    runs = list_task_run_dirs(proot)

    for run_dir in runs:
        try:
            generate_per_task_artifacts(agentlab_root, project, run_dir.name)
        except Exception:
            pass

    index = build_project_task_index(agentlab_root, project)
    save_project_task_index(agentlab_root, project, index)
    sync_task_ledger(agentlab_root, project, index)
    return index