#!/usr/bin/env python3
"""AgentLab Web UI Backend API Server.

Serves a REST API that bridges the Web UI to AgentLab's project filesystem.
Reads real task state, user decisions, and triggers agent execution via CLI.
No external dependencies beyond Python stdlib.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# AgentLab root — resolve from this file's location
AGENTLAB_ROOT = Path(os.getenv("AGENTLAB_ROOT", Path(__file__).resolve().parents[1]))
if str(AGENTLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTLAB_ROOT))
AGENTLAB_RUNTIME = AGENTLAB_ROOT / "agent_runtime"
if str(AGENTLAB_RUNTIME) not in sys.path:
    sys.path.insert(0, str(AGENTLAB_RUNTIME))


# ────────── helpers ──────────

def load_yaml_safe(path: Path) -> dict:
    """Load a YAML file, returning {} on error."""
    try:
        import yaml
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data or {}
    except Exception:
        pass
    return {}


def write_yaml_safe(path: Path, data: dict) -> bool:
    """Write YAML, returning False on error."""
    try:
        import yaml
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return True
    except Exception:
        return False


def read_text(path: Path) -> str:
    """Read a text file, returning '' on error."""
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


def list_dirs(path: Path) -> list[str]:
    """List subdirectory names."""
    try:
        return sorted([d.name for d in path.iterdir() if d.is_dir() and d.name.startswith("task_")])
    except Exception:
        return []


def safe_project_name(name: str) -> str:
    """Restrict project names to local folder-safe identifiers."""
    name = (name or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not name or any(ch not in allowed for ch in name):
        raise ValueError("Project name may only contain letters, numbers, underscore, and hyphen")
    return name


def first_line_title(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:80]
    return fallback


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def ensure_project_memory_files(project_root: Path, project_name: str, description: str = "") -> None:
    """Create the minimal AgentLab project memory files if missing."""
    docs = project_root / "agent_docs"
    docs.mkdir(parents=True, exist_ok=True)
    defaults = {
        "00_CONTEXT_PACK.md": f"# {project_name} Context Pack\n\n{description or 'Project context will be maintained here.'}\n",
        "01_REPO_MAP.md": f"# {project_name} Repo Map\n\nTBD\n",
        "02_TASK_LEDGER.yml": {
            "version": 1,
            "project": project_name,
            "description": description,
            "tasks": [],
        },
        "03_DECISION_LOG.md": "# Decision Log\n\n",
        "04_INTERFACE_REGISTRY.md": "# Interface Registry\n\n",
        "05_CHANGELOG_AGENT.md": "# Agent Changelog\n\n",
        "06_RISK_REGISTER.md": "# Risk Register\n\n",
        "07_DEVELOPMENT_LOG.md": "# Development Log\n\n",
        "08_CODEX_DIALOGUE_LOG.md": "# Codex Dialogue Log\n\n",
        "09_COST_LEDGER.yml": {"entries": []},
        "10_SYNC_LEDGER.yml": {"version": 1, "project": project_name, "entries": []},
    }
    for filename, content in defaults.items():
        path = docs / filename
        if path.exists():
            continue
        if isinstance(content, dict):
            write_yaml_safe(path, content)
        else:
            path.write_text(content, encoding="utf-8")


def run_cli_json(args: list[str], timeout: int = 30) -> dict:
    """Run AgentLab CLI JSON command and parse stdout safely."""
    try:
        result = subprocess.run(
            [sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(AGENTLAB_ROOT),
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            data = {"status": "fail", "error": "invalid json output", "stdout": result.stdout[:500]}
        data.setdefault("returncode", result.returncode)
        if result.stderr:
            data.setdefault("stderr", result.stderr[:500])
        return data
    except subprocess.TimeoutExpired:
        return {"status": "fail", "error": "command timeout"}
    except Exception as exc:
        return {"status": "fail", "error": str(exc)}


def upsert_task_ledger_entry(project: str, task_id: str, request_text: str, status: str = "planned") -> None:
    """Keep the project task ledger aligned with real run folders."""
    project = safe_project_name(project)
    ledger_path = AGENTLAB_ROOT / "projects" / project / "agent_docs" / "02_TASK_LEDGER.yml"
    ledger = load_yaml_safe(ledger_path) or {"version": 1, "project": project, "tasks": []}
    tasks = ledger.setdefault("tasks", [])
    existing = next((t for t in tasks if t.get("task_id") == task_id), None)
    title = first_line_title(request_text, task_id)
    if existing:
        existing.setdefault("title", title)
        existing.setdefault("description", request_text[:240])
        existing["status"] = existing.get("status") or status
    else:
        tasks.append({
            "task_id": task_id,
            "title": title,
            "description": request_text[:500],
            "status": status,
            "priority": "P2",
            "category": "feature",
            "depends_on": [],
            "subtasks": [],
            "created_at": today_date(),
        })
    write_yaml_safe(ledger_path, ledger)


# ────────── API handlers ──────────

def handle_get_projects():
    """List all projects."""
    projects_dir = AGENTLAB_ROOT / "projects"
    if not projects_dir.exists():
        return {"projects": []}
    projects = []
    for d in sorted(projects_dir.iterdir(), key=lambda p: p.name):
        if not d.is_dir() or d.name.startswith(".") or d.name == ".DS_Store":
            continue
        cfg = load_yaml_safe(d / "project_config.yml")
        ledger = load_yaml_safe(d / "agent_docs" / "02_TASK_LEDGER.yml")
        github = cfg.get("github", {})
        projects.append({
            "name": d.name,
            "type": (cfg.get("project") or {}).get("type", ""),
            "description": ledger.get("description", ""),
            "taskCount": len(ledger.get("tasks", [])),
            "github": github,
            "backupEnabled": bool((github.get("backup") or {}).get("enabled", False)),
            "backupRepo": (github.get("backup") or {}).get("repo", ""),
            "backupVisibility": (github.get("backup") or {}).get("visibility", "private"),
        })
    return {"projects": projects}


def handle_get_system_status(project: str = "AgentLab", task_id: str = ""):
    """Return a redacted system/migration/backup status snapshot for Web UI."""
    project = safe_project_name(project)
    migration = run_cli_json(["migration-doctor", "--project", project, "--json-output", "--no-write-probe"], timeout=30)
    backup_args = ["backup-status", "--project", project, "--json-output"]
    if task_id:
        backup_args.extend(["--task-id", task_id])
    backup = run_cli_json(backup_args, timeout=20)
    truenas = run_cli_json(["truenas-status", "--project", project, "--json-output", "--no-write-probe"], timeout=20)
    return {
        "generatedAt": utc_now_iso(),
        "project": project,
        "taskId": task_id,
        "migration": migration,
        "backup": backup,
        "truenas": truenas,
        "webUi": {
            "host": os.getenv("AGENTLAB_WEB_UI_BIND", "127.0.0.1"),
            "port": int(os.getenv("AGENTLAB_PORT", "8765")),
            "authTokenEnv": "AGENTLAB_WEB_UI_TOKEN",
            "authTokenConfigured": bool(os.getenv("AGENTLAB_WEB_UI_TOKEN")),
        },
    }


def _web_execute_authorized(headers, data: dict) -> tuple[bool, str]:
    """Authorize sensitive Web UI actions without exposing token values."""
    required_token = os.getenv("AGENTLAB_WEB_UI_TOKEN")
    if not required_token:
        return False, "AGENTLAB_WEB_UI_TOKEN is not configured; execute from Web UI is disabled."
    supplied = headers.get("X-AgentLab-Token") or data.get("authToken") or ""
    if supplied != required_token:
        return False, "Invalid or missing AgentLab Web UI token."
    return True, "authorized"


def handle_post_truenas_sync(data: dict, headers) -> dict:
    """Run TrueNAS dry-run from Web UI; execute requires local token."""
    project = safe_project_name(data.get("project", "AgentLab"))
    task_id = data.get("taskId") or data.get("task_id") or "task_0001"
    execute = bool(data.get("execute", False))
    if execute:
        ok, reason = _web_execute_authorized(headers, data)
        if not ok:
            return {"success": False, "status": "blocked", "error": reason}
    args = ["truenas-sync", "--project", project, "--task-id", task_id, "--json-output"]
    if execute:
        args.append("--execute")
    else:
        args.append("--dry-run")
    report = run_cli_json(args, timeout=120)
    report["success"] = report.get("status") in {"synced", "dry_run_completed"}
    return report


def handle_get_tasks(project: str):
    """List all tasks for a project with titles and descriptions from ledger."""
    project = safe_project_name(project)
    run_dir = AGENTLAB_ROOT / "projects" / project / "runs"
    ledger_path = AGENTLAB_ROOT / "projects" / project / "agent_docs" / "02_TASK_LEDGER.yml"

    # Build a map of task_id -> {title, description} from ledger
    task_info = {}
    if ledger_path.exists():
        ledger = load_yaml_safe(ledger_path)
        for t in ledger.get("tasks", []):
            tid = t.get("task_id", "")
            task_info[tid] = {
                "title": t.get("title", ""),
                "description": t.get("description", ""),
                "status": t.get("status", ""),
                "priority": t.get("priority", ""),
                "category": t.get("category", ""),
                "depends_on": t.get("depends_on", []),
                "subtasks": t.get("subtasks", []),
            }

    task_ids = list_dirs(run_dir)
    tasks = []
    for tid in task_ids:
        info = task_info.get(tid, {})
        tasks.append({
            "task_id": tid,
            "title": info.get("title", tid),
            "description": info.get("description", ""),
            "status": info.get("status", ""),
            "priority": info.get("priority", ""),
            "category": info.get("category", ""),
            "depends_on": info.get("depends_on", []),
            "subtasks": info.get("subtasks", []),
        })

    return {"project": project, "tasks": tasks}


def handle_get_status(project: str, task_id: str):
    """Get full status snapshot for a task."""
    project = safe_project_name(project)
    run_dir = AGENTLAB_ROOT / "projects" / project / "runs" / task_id
    project_root = AGENTLAB_ROOT / "projects" / project

    if not task_id or not run_dir.exists():
        project_config = load_yaml_safe(project_root / "project_config.yml")
        github_policy = load_yaml_safe(AGENTLAB_ROOT / "config" / "github_policy.yml")
        harness_policy = load_yaml_safe(AGENTLAB_ROOT / "config" / "harness_policy.yml")
        github_config = project_config.get("github", {})
        backup_config = github_config.get("backup", {})
        return {
            "generatedAt": utc_now_iso(),
            "project": project,
            "taskId": "",
            "taskStatus": "no_task",
            "stage": "Project overview",
            "userRequest": "",
            "coderProvider": "codex-plus",
            "brainProvider": "deepseek",
            "projectConfig": project_config,
            "githubPolicy": github_policy,
            "harnessPolicy": harness_policy,
            "githubBackup": {
                "enabled": bool(backup_config.get("enabled", False)),
                "owner": backup_config.get("owner", ""),
                "repo": backup_config.get("repo", ""),
                "visibility": backup_config.get("visibility", github_policy.get("defaults", {}).get("visibility", "private")),
                "branch": backup_config.get("branch", github_policy.get("defaults", {}).get("backup_branch", "main")),
                "lastSyncCommit": backup_config.get("last_sync_commit"),
                "mode": github_policy.get("defaults", {}).get("sync_mode", "local_first_manual_push"),
                "tokenConfigured": bool(os.getenv(github_policy.get("auth", {}).get("token_env", "GITHUB_TOKEN"))),
            },
            "route": [],
            "agents": [],
            "events": [{"time": "--", "level": "info", "agent": "Project", "text": "项目已创建，尚未创建任务"}],
            "costLedger": [],
            "decisions": [],
            "hasUserDecision": False,
            "userDecisionText": "",
        }

    # Load state
    state = load_yaml_safe(run_dir / "state.yml")
    snapshot = load_yaml_safe(run_dir / "task_snapshot.yml")
    if not snapshot:
        try:
            from task_snapshot import build_task_snapshot
            snapshot = build_task_snapshot(run_dir, project=project, task_id=task_id)
        except Exception:
            snapshot = {}
    plan = load_yaml_safe(run_dir / "workflow_plan.yml")
    brain = load_yaml_safe(run_dir / "brain_decisions.yml")
    cost = load_yaml_safe(run_dir / "cost_ledger.yml")
    user_request = read_text(run_dir / "user_request.md")

    # Load user decision if exists
    decision_text = read_text(run_dir / "USER_DECISION_REQUIRED.md")
    has_decision = bool(decision_text)
    blocked_agents = []

    # Check for blocked agent files
    for f in sorted(run_dir.glob("blocked_*.md")):
        blocked_agents.append(f.stem.replace("blocked_", ""))

    # Build agents from registry config
    reg = load_yaml_safe(AGENTLAB_ROOT / "config" / "agent_registry.yml")
    registry_agents = reg.get("agents", {})

    # Build agents list
    route_agents = snapshot.get("route") or plan.get("route", {}).get("agents", [])
    agents = []
    status_labels = {"active": "进行中", "complete": "已完成", "waiting": "等待中", "skipped": "已跳过", "blocked": "已阻塞", "new": "新建"}

    for agent_name in route_agents:
        agent_cfg = registry_agents.get(agent_name, {})
        agent_state = (state.get("reports") or {}).get(agent_name, None)
        status = "waiting"
        if state.get("status") == "blocked" and agent_name in blocked_agents:
            status = "blocked"
        elif agent_state:
            status = "complete" if agent_state else "active"
        elif state.get("current_agent") == agent_name:
            status = "active"

        # Token budget from plan
        token_budget = 0
        for tb in plan.get("token_budgets", []):
            phase = tb.get("phase", "").lower()
            if agent_name.lower() in phase or (
                ("intake" in phase and agent_name == "Supervisor") or
                ("coder" in phase and agent_name == "Coder") or
                ("tester" in phase and agent_name == "TesterAuditor") or
                ("archivist" in phase and agent_name == "Archivist") or
                ("reposcout" in phase and agent_name == "RepoScout") or
                ("interface" in phase and agent_name == "InterfaceMapper")
            ):
                token_budget = tb.get("estimated_total_tokens", 0)
                break

        # Token usage from cost ledger
        used_tokens = 0
        for entry in cost.get("entries", []):
            if entry.get("agent") == agent_name or entry.get("agent_name") == agent_name:
                used_tokens += int(entry.get("total_tokens") or 0)

        agents.append({
            "name": agent_name,
            "role": agent_cfg.get("role", ""),
            "status": status,
            "provider": "DeepSeek" if agent_name != "Coder" else "Codex Plus",
            "model": "deepseek-v4-pro" if agent_name != "Coder" else "Codex",
            "owner": agent_cfg.get("execution_owner", "管理层").replace("codex_plus", "执行层"),
            "canEdit": agent_cfg.get("can_edit_source", False),
            "budgetTokens": token_budget,
            "usedTokens": used_tokens,
        })

    # Build events
    events = []
    for entry in cost.get("entries", []):
        agent = entry.get("agent") or entry.get("agent_name") or "Unknown"
        ts = entry.get("timestamp") or utc_now_iso()
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
        except Exception:
            time_str = ts[:16] if len(ts) >= 16 else ts
        status = entry.get("status", "ok")
        level = "info"
        if status == "blocked_user_decision":
            level = "decision"
        elif status in ("error", "provider_error"):
            level = "error"
        elif "error" in (entry.get("notes") or ""):
            level = "warn"

        events.append({
            "time": time_str,
            "level": level,
            "agent": agent,
            "text": f"{agent}: {entry.get('notes', status)}",
        })

    # Add decision events
    for dec in brain.get("decisions", []):
        events.append({
            "time": dec.get("timestamp", "")[:16] if dec.get("timestamp") else "",
            "level": "decision",
            "agent": dec.get("agent_name", ""),
            "text": dec.get("reason", ""),
        })

    # Add blocked status events
    for ba in blocked_agents:
        events.append({
            "time": datetime.now().strftime("%H:%M"),
            "level": "error",
            "agent": ba,
            "text": f"{ba} 已阻塞：DeepSeek API 超时，等待用户决策",
        })

    # Sort events by time (newest first)
    events.sort(key=lambda e: e.get("time", ""), reverse=True)

    # Config summary
    exec_policy = load_yaml_safe(AGENTLAB_ROOT / "config" / "execution_policy.yml")
    project_config = load_yaml_safe(project_root / "project_config.yml")
    github_policy = load_yaml_safe(AGENTLAB_ROOT / "config" / "github_policy.yml")
    harness_policy = load_yaml_safe(AGENTLAB_ROOT / "config" / "harness_policy.yml")
    brain_policy = exec_policy.get("brain_policy", {})
    coder_policy = exec_policy.get("coder_policy", {})
    github_config = project_config.get("github", {})
    backup_config = github_config.get("backup", {})

    return {
        "generatedAt": utc_now_iso(),
        "project": project,
        "taskId": task_id,
        "taskStatus": snapshot.get("status") or state.get("status", "new"),
        "stage": snapshot.get("last_event") or state.get("last_event", ""),
        "snapshot": snapshot,
        "userRequest": user_request[:2000] if user_request else "",
        "coderProvider": "codex-plus",
        "coderQuotaRemaining": coder_policy.get("codex_quota_remaining", 0),
        "coderQuotaWarningThreshold": 2000,
        "brainProvider": brain_policy.get("required_provider", "deepseek"),
        "projectConfig": project_config,
        "githubPolicy": github_policy,
        "harnessPolicy": harness_policy,
        "githubBackup": {
            "enabled": bool(backup_config.get("enabled", False)),
            "owner": backup_config.get("owner", ""),
            "repo": backup_config.get("repo", ""),
            "visibility": backup_config.get("visibility", github_policy.get("defaults", {}).get("visibility", "private")),
            "branch": backup_config.get("branch", github_policy.get("defaults", {}).get("backup_branch", "main")),
            "lastSyncCommit": backup_config.get("last_sync_commit"),
            "mode": github_policy.get("defaults", {}).get("sync_mode", "local_first_manual_push"),
            "tokenConfigured": bool(os.getenv(github_policy.get("auth", {}).get("token_env", "GITHUB_TOKEN"))),
        },
        "qwenFallback": {
            "provider": "Qwen",
            "enabled": bool(os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")),
            "model": os.getenv("QWEN_MODEL", "qwen-plus"),
            "modelOptions": ["qwen-coder-aux", "qwen-coder-plus", "qwen-coder-turbo", "qwen-max"],
        },
        "route": route_agents,
        "agents": agents,
        "events": events or [{"time": "--", "level": "info", "agent": "System", "text": "暂无事件"}],
        "costLedger": cost.get("entries", []),
        "decisions": [
            {
                "id": f"dec_{i:03d}",
                "title": d.get("decision_type", "决策").replace("_", " ").title(),
                "question": d.get("reason", ""),
                "recommendations": [
                    "1. 暂停并重试（DeepSeek 恢复后）",
                    "2. 显式更改策略，允许 Codex 手动模拟大脑阶段"
                ],
                "default": "重试",
                "status": "pending" if has_decision else "resolved",
            }
            for i, d in enumerate(brain.get("decisions", []))
        ],
        "hasUserDecision": has_decision,
        "userDecisionText": decision_text[:500] if decision_text else "",
    }


def task_run_dir(project: str, task_id: str) -> Path:
    project = safe_project_name(project)
    return AGENTLAB_ROOT / "projects" / project / "runs" / task_id


def handle_get_task_events(project: str, task_id: str) -> dict:
    """Return structured task events from task_events.jsonl."""
    run_dir = task_run_dir(project, task_id)
    if not run_dir.exists():
        return {"success": False, "error": "Task not found", "events": []}
    from task_events import load_task_events

    events = load_task_events(run_dir)
    return {
        "success": True,
        "project": project,
        "task_id": task_id,
        "events": events,
        "latest_event": events[-1] if events else None,
    }


def _ui_event(event: dict) -> dict:
    severity = event.get("severity") or "INFO"
    level = {
        "ACTION_REQUIRED": "decision",
        "BUDGET_WARNING": "warn",
        "RISK_WARNING": "warn",
        "BLOCKED": "error",
        "FAILED_RECOVERABLE": "error",
        "COMPLETED": "info",
        "MILESTONE": "info",
    }.get(severity, "info")
    return {
        "time": event.get("time", ""),
        "level": level,
        "agent": event.get("stage") or event.get("event") or "System",
        "text": event.get("message") or event.get("event") or "",
        "raw": event,
    }


def handle_get_task_decisions(project: str, task_id: str, *, all_statuses: bool = False) -> dict:
    """Return decision cards for a task."""
    run_dir = task_run_dir(project, task_id)
    if not run_dir.exists():
        return {"success": False, "error": "Task not found", "decisions": []}
    from atomic_io import safe_read_yaml
    from feedback_manager import decision_cards_dir, load_pending_decision_cards

    if all_statuses:
        root = decision_cards_dir(run_dir)
        cards = []
        if root.exists():
            for card_path in sorted(root.glob("*.yml")):
                card = safe_read_yaml(card_path, default={}) or {}
                if isinstance(card, dict):
                    card.setdefault("_path", str(card_path))
                    cards.append(card)
    else:
        cards = load_pending_decision_cards(run_dir)
    return {
        "success": True,
        "project": project,
        "task_id": task_id,
        "decisions": cards,
        "pending_count": len([c for c in cards if c.get("status") in {"pending", "pending_user_approval", "waiting_for_approval"}]),
    }


def handle_resolve_task_decision(project: str, task_id: str, decision_id: str, resolution: str, data: dict) -> dict:
    """Approve or reject a decision card through the shared feedback manager."""
    run_dir = task_run_dir(project, task_id)
    if not run_dir.exists():
        return {"success": False, "error": "Task not found"}
    option = data.get("option") or data.get("option_id")
    if not option:
        option = "approve_resume" if resolution == "approved" else "stop_task"
    try:
        from feedback_manager import resolve_decision_card

        card = resolve_decision_card(run_dir, decision_id, option_id=option, resolution=resolution, actor="web_ui")
        return {
            "success": True,
            "project": project,
            "task_id": task_id,
            "decision": card,
            "next_recommended_action": "resume" if resolution == "approved" else None,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _write_task_state(run_dir: Path, *, status: str, stage: str, message: str) -> None:
    state = load_yaml_safe(run_dir / "state.yml")
    state["status"] = status
    state["last_event"] = message
    state["updated_at"] = utc_now_iso()
    write_yaml_safe(run_dir / "state.yml", state)

    progress = load_yaml_safe(run_dir / "progress.yml")
    progress["status"] = status
    progress["current_stage"] = stage
    progress["last_event"] = message
    progress["last_event_at"] = utc_now_iso()
    write_yaml_safe(run_dir / "progress.yml", progress)


def handle_task_control(project: str, task_id: str, action: str, data: dict | None = None) -> dict:
    """Pause/resume/stop a task from the Decision Center."""
    run_dir = task_run_dir(project, task_id)
    if not run_dir.exists():
        return {"success": False, "error": "Task not found"}
    from feedback_manager import load_pending_decision_cards, write_feedback_status
    from task_events import append_task_event

    data = data or {}
    reason = data.get("reason") or f"web_ui_{action}"
    if action == "resume" and load_pending_decision_cards(run_dir):
        return {"success": False, "error": "Task still has pending decision cards."}

    mapping = {
        "pause": ("paused", "paused", "TASK_PAUSED", "WAITING_FOR_APPROVAL", "ACTION_REQUIRED"),
        "resume": ("running", "running", "TASK_RESUMED", "RUNNING", "MILESTONE"),
        "stop": ("failed", "stopped", "TASK_STOPPED", "FAILED_FINAL", "FAILED_RECOVERABLE"),
    }
    if action not in mapping:
        return {"success": False, "error": f"Unsupported action: {action}"}

    state_status, stage, event_name, fine_status, severity = mapping[action]
    message = f"Task {action} requested from Web UI: {reason}."
    _write_task_state(run_dir, status=state_status, stage=stage, message=message)
    event = append_task_event(
        run_dir,
        event_name,
        stage=stage,
        status=fine_status,
        severity=severity,
        message=message,
        payload={"actor": "web_ui", "reason": reason},
    )
    feedback_path = write_feedback_status(run_dir)
    return {
        "success": True,
        "project": project,
        "task_id": task_id,
        "action": action,
        "event": event,
        "feedback_status": str(feedback_path),
    }


def handle_post_decision(data: dict):
    """Handle user decision submission."""
    project = safe_project_name(data.get("project", "AgentLab"))
    task_id = data.get("taskId", "")
    action = data.get("action", "yes")  # yes / no / later
    if not task_id:
        return {"error": "taskId is required", "success": False}

    run_dir = AGENTLAB_ROOT / "projects" / project / "runs" / task_id

    if not run_dir.exists():
        return {"error": "Task not found", "success": False}

    # Read the decision file
    decision_path = run_dir / "USER_DECISION_REQUIRED.md"
    decision_text = read_text(decision_path)

    # Record the decision in brain_decisions
    brain_path = run_dir / "brain_decisions.yml"
    brain = load_yaml_safe(brain_path)
    decisions = brain.get("decisions", [])
    if decisions:
        decisions[-1]["decision"] = "approved" if action == "yes" else ("deferred" if action == "later" else "rejected")
        decisions[-1]["user_resolution"] = action
    brain["decisions"] = decisions

    try:
        import yaml
        brain_path.write_text(yaml.safe_dump(brain, sort_keys=False), encoding="utf-8")
    except Exception:
        pass

    # Append to events
    event_text = f"用户{'批准' if action == 'yes' else ('推迟' if action == 'later' else '拒绝')}了决策"
    timestamp = utc_now_iso()
    cost_path = run_dir / "cost_ledger.yml"
    cost = load_yaml_safe(cost_path)
    entries = cost.get("entries", [])
    entries.append({
        "timestamp": timestamp,
        "agent": "User",
        "agent_name": "User",
        "provider": "manual",
        "model": "N/A",
        "status": "ok",
        "total_tokens": 0,
        "usage_source": "manual_entry",
        "exact_usage_available": True,
        "exact_cost_available": True,
        "estimated_cost": 0.0,
        "notes": event_text,
    })
    cost["entries"] = entries
    try:
        import yaml
        cost_path.write_text(yaml.safe_dump(cost, sort_keys=False), encoding="utf-8")
    except Exception:
        pass

    # If user approved, try to re-run the blocked agent
    action_result = ""
    if action == "yes":
        # Find which agent is blocked
        blocked_files = list(run_dir.glob("blocked_*.md"))
        for bf in blocked_files:
            agent_name = bf.stem.replace("blocked_", "")
            try:
                result = subprocess.run(
                    [
                        sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                        "run-agent", agent_name,
                        "--task-id", task_id,
                        "--project", project,
                        "--execute", "--overwrite-report",
                    ],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(AGENTLAB_ROOT),
                )
                action_result += f"\n{agent_name}: {result.stdout[:200]}"
                if result.returncode != 0:
                    action_result += f"\nError: {result.stderr[:200]}"
            except subprocess.TimeoutExpired:
                action_result += f"\n{agent_name}: 命令超时"
            except Exception as e:
                action_result += f"\n{agent_name}: {str(e)}"

    return {
        "success": True,
        "action": action,
        "message": event_text,
        "actionResult": action_result.strip() if action_result else "",
    }


def handle_run_agent(data: dict):
    """Handle running a specific agent."""
    project = safe_project_name(data.get("project", "AgentLab"))
    task_id = data.get("taskId", "")
    agent_name = data.get("agentName", "")
    action = data.get("action", "run")  # run, pause, stop, execute
    if not task_id:
        return {"success": False, "agentName": agent_name, "error": "taskId is required"}

    if action == "execute":
        # Actual API execution via CLI
        try:
            result = subprocess.run(
                [
                    sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                    "run-agent", agent_name,
                    "--task-id", task_id,
                    "--project", project,
                    "--execute", "--overwrite-report",
                ],
                capture_output=True, text=True, timeout=60,
                cwd=str(AGENTLAB_ROOT),
            )
            return {
                "success": result.returncode == 0,
                "agentName": agent_name,
                "action": action,
                "stdout": result.stdout[:500],
                "stderr": result.stderr[:500],
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "agentName": agent_name, "error": "执行超时"}
        except Exception as e:
            return {"success": False, "agentName": agent_name, "error": str(e)}

    # Manual status update
    run_dir = AGENTLAB_ROOT / "projects" / project / "runs" / task_id
    timestamp = utc_now_iso()

    # Log the action
    cost_path = run_dir / "cost_ledger.yml"
    cost = load_yaml_safe(cost_path)
    entries = cost.get("entries", [])
    status_map = {"run": "active", "pause": "waiting", "stop": "blocked"}
    entries.append({
        "timestamp": timestamp,
        "agent": agent_name,
        "agent_name": agent_name,
        "provider": "manual",
        "status": status_map.get(action, action),
        "total_tokens": 0,
        "usage_source": "manual_entry",
        "exact_usage_available": True,
        "exact_cost_available": True,
        "estimated_cost": 0.0,
        "notes": f"用户操作: {action}",
    })
    cost["entries"] = entries
    try:
        import yaml
        cost_path.write_text(yaml.safe_dump(cost, sort_keys=False), encoding="utf-8")
    except Exception:
        pass

    return {
        "success": True,
        "agentName": agent_name,
        "action": action,
        "message": f"Agent {agent_name} {action}",
    }


def handle_create_task(data: dict):
    """Create a new task via CLI."""
    project = safe_project_name(data.get("project", "AgentLab"))
    task_id = data.get("taskId", "")
    request_text = data.get("requestText", "")
    backend = data.get("backend", "codex")  # codex or qwen
    if not task_id:
        return {"success": False, "error": "taskId is required"}

    try:
        result = subprocess.run(
            [
                sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                "init-task", "--task-id", task_id,
                "--project", project,
                "--request-text", request_text,
            ],
            capture_output=True, text=True, timeout=15,
            cwd=str(AGENTLAB_ROOT),
        )
        if result.returncode == 0:
            upsert_task_ledger_entry(project, task_id, request_text, "planned")
            # Also prepare
            subprocess.run(
                [
                    sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                    "prepare", "--task-id", task_id,
                    "--project", project,
                    "--write-plan",
                ],
                capture_output=True, text=True, timeout=15,
                cwd=str(AGENTLAB_ROOT),
            )
        return {
            "success": result.returncode == 0,
            "taskId": task_id,
            "project": project,
            "message": result.stdout[:500],
        }
    except Exception as e:
        return {"success": False, "taskId": task_id, "error": str(e)}


def handle_natural_language_task(data: dict):
    """Create a task from natural language description and optionally start execution."""
    project = safe_project_name(data.get("project", "AgentLab"))
    request_text = data.get("text", "").strip()
    auto_execute = data.get("autoExecute", True)

    if not request_text:
        return {"success": False, "error": "任务描述不能为空"}

    # Auto-generate task ID
    run_dir = AGENTLAB_ROOT / "projects" / project / "runs"
    existing = list_dirs(run_dir)
    max_num = 0
    for t in existing:
        try:
            num = int(t.replace("task_", ""))
            max_num = max(max_num, num)
        except ValueError:
            pass
    task_id = f"task_{max_num + 1:04d}"

    # Step 1: init-task
    try:
        result = subprocess.run(
            [
                sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                "init-task", "--task-id", task_id,
                "--project", project,
                "--request-text", request_text,
            ],
            capture_output=True, text=True, timeout=15,
            cwd=str(AGENTLAB_ROOT),
        )
        if result.returncode != 0:
            return {"success": False, "taskId": task_id, "error": f"init-task failed: {result.stderr[:300]}"}
        upsert_task_ledger_entry(project, task_id, request_text, "active" if auto_execute else "planned")
    except Exception as e:
        return {"success": False, "taskId": task_id, "error": f"init-task exception: {str(e)}"}

    # Step 2: prepare
    try:
        result = subprocess.run(
            [
                sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                "prepare", "--task-id", task_id,
                "--project", project,
                "--write-plan",
            ],
            capture_output=True, text=True, timeout=15,
            cwd=str(AGENTLAB_ROOT),
        )
        if result.returncode != 0:
            return {"success": False, "taskId": task_id, "error": f"prepare failed: {result.stderr[:300]}", "stage": "prepared"}
    except Exception as e:
        return {"success": False, "taskId": task_id, "error": f"prepare exception: {str(e)}", "stage": "inited"}

    # Step 3: Run Supervisor (brain agent) if auto-execute
    supervisor_result = ""
    if auto_execute:
        try:
            result = subprocess.run(
                [
                    sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                    "run-agent", "Supervisor",
                    "--task-id", task_id,
                    "--project", project,
                    "--execute", "--overwrite-report",
                ],
                capture_output=True, text=True, timeout=90,
                cwd=str(AGENTLAB_ROOT),
            )
            supervisor_result = result.stdout[:500]
            if "blocked_user_decision" in result.stdout:
                return {
                    "success": True,
                    "taskId": task_id,
                    "project": project,
                    "stage": "awaiting_decision",
                    "message": f"任务 {task_id} 已创建，Supervisor 执行后需要用户决策",
                    "supervisorOutput": supervisor_result,
                }
        except subprocess.TimeoutExpired:
            supervisor_result = "Supervisor 执行超时（>90s）"
        except Exception as e:
            supervisor_result = f"Supervisor error: {str(e)}"

    return {
        "success": True,
        "taskId": task_id,
        "project": project,
        "stage": "supervisor_completed" if "completed" in supervisor_result else "task_created",
        "message": f"任务 {task_id} 已创建并开始执行",
        "supervisorOutput": supervisor_result,
    }


def handle_run_next_agents(data: dict):
    """Run all waiting agents in sequence for a task (RepoScout, InterfaceMapper, etc.)."""
    project = safe_project_name(data.get("project", "AgentLab"))
    task_id = data.get("taskId", "")

    run_dir = AGENTLAB_ROOT / "projects" / project / "runs" / task_id
    if not run_dir.exists():
        return {"success": False, "error": "Task not found"}

    # Read workflow plan to get agent order
    plan = load_yaml_safe(run_dir / "workflow_plan.yml")
    agents = plan.get("route", {}).get("agents", [])
    state = load_yaml_safe(run_dir / "state.yml")
    completed = state.get("completed_agents", [])

    results = []
    for agent_name in agents:
        if agent_name == "Coder":
            continue  # Skip Coder — manual Codex Plus execution
        if agent_name in completed:
            continue

        try:
            result = subprocess.run(
                [
                    sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"),
                    "run-agent", agent_name,
                    "--task-id", task_id,
                    "--project", project,
                    "--execute", "--overwrite-report",
                ],
                capture_output=True, text=True, timeout=60,
                cwd=str(AGENTLAB_ROOT),
            )
            results.append({
                "agent": agent_name,
                "success": result.returncode == 0 or "User decision required" in result.stdout,
                "output": result.stdout[:300],
            })
            if "blocked_user_decision" in result.stdout:
                return {
                    "success": True,
                    "stage": "awaiting_decision",
                    "message": f"{agent_name} 需要用户决策",
                    "results": results,
                }
        except subprocess.TimeoutExpired:
            results.append({"agent": agent_name, "success": False, "output": "Timeout"})
        except Exception as e:
            results.append({"agent": agent_name, "success": False, "output": str(e)})

    return {"success": True, "stage": "all_done", "results": results}


def handle_create_subtask(data: dict):
    """Append a subtask to the selected task ledger entry."""
    project = safe_project_name(data.get("project", "AgentLab"))
    task_id = data.get("taskId", "")
    text = data.get("text", "").strip()
    if not task_id:
        return {"success": False, "error": "taskId is required"}
    if not text:
        return {"success": False, "error": "子任务描述不能为空"}

    ledger_path = AGENTLAB_ROOT / "projects" / project / "agent_docs" / "02_TASK_LEDGER.yml"
    ledger = load_yaml_safe(ledger_path)
    tasks = ledger.get("tasks", [])
    task = next((t for t in tasks if t.get("task_id") == task_id), None)
    if not task:
        return {"success": False, "error": f"Task {task_id} not found in ledger"}

    subtasks = task.setdefault("subtasks", [])
    max_num = 0
    for item in subtasks:
        raw = str(item.get("id", "")).replace("sub_", "")
        try:
            max_num = max(max_num, int(raw))
        except ValueError:
            pass
    subtask_id = f"sub_{max_num + 1:03d}"
    subtasks.append({
        "id": subtask_id,
        "description": text,
        "status": "pending",
        "created_at": today_date(),
    })
    task["status"] = task.get("status") or "active"
    ok = write_yaml_safe(ledger_path, ledger)
    return {
        "success": ok,
        "project": project,
        "taskId": task_id,
        "subtaskId": subtask_id,
        "message": f"子任务 {subtask_id} 已追加到 {task_id}",
    }


def handle_create_project(data: dict):
    """Create a local AgentLab project shell with GitHub backup placeholders."""
    raw_name = data.get("projectName") or data.get("name") or ""
    try:
        project = safe_project_name(raw_name)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    description = data.get("description", "").strip()
    github_owner = data.get("githubOwner", "").strip()
    github_repo = data.get("githubRepo", "").strip() or project

    project_root = AGENTLAB_ROOT / "projects" / project
    if project_root.exists():
        return {"success": False, "project": project, "error": "Project already exists"}

    try:
        (project_root / "runs").mkdir(parents=True, exist_ok=True)
        (project_root / "repo").mkdir(parents=True, exist_ok=True)
        ensure_project_memory_files(project_root, project, description)
        config = {
            "project": {
                "name": project,
                "type": "local_agent_workflow",
            },
            "paths": {
                "repo": "repo",
                "docs": "agent_docs",
                "runs": "runs",
            },
            "global_config": {
                "agent_registry": "../../config/agent_registry.yml",
                "model_profiles": "../../config/model_profiles.yml",
                "routing_rules": "../../config/routing_rules.yml",
                "budget_profiles": "../../config/budget_profiles.yml",
                "validation_gates": "../../config/validation_gates.yml",
                "memory_policy": "../../config/memory_policy.yml",
                "github_policy": "../../config/github_policy.yml",
                "harness_policy": "../../config/harness_policy.yml",
            },
            "github": {
                "backup": {
                    "enabled": False,
                    "owner": github_owner,
                    "repo": github_repo,
                    "visibility": "private",
                    "branch": "main",
                    "last_sync_commit": None,
                },
                "source": {
                    "owner": github_owner,
                    "repo": github_repo,
                    "default_branch": "main",
                },
                "cloud": {
                    "enabled": False,
                    "runner": "github_actions_workflow_dispatch",
                },
            },
            "safety_rules": [
                "Keep AgentLab local-first and transparent.",
                "Default GitHub backups must be private.",
                "Do not create or expose real secrets.",
            ],
        }
        write_yaml_safe(project_root / "project_config.yml", config)
    except Exception as exc:
        return {"success": False, "project": project, "error": str(exc)}

    return {
        "success": True,
        "scope": "workspace",
        "project": project,
        "projectPath": str(project_root),
        "message": f"项目 {project} 已创建，GitHub 私有备份占位已写入 project_config.yml",
    }


# ────────── HTTP server ──────────

class AgentLabAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for AgentLab API."""

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-AgentLab-Token")

    @staticmethod
    def _json_default(obj):
        """Handle non-serializable types (date, etc.)."""
        import datetime as _dt
        if isinstance(obj, (_dt.date, _dt.datetime)):
            return obj.isoformat()
        return str(obj)

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2, default=self._json_default).encode("utf-8"))

    def _serve_static(self, path: str):
        """Serve static files from web_ui directory."""
        web_dir = Path(__file__).parent
        file_path = web_dir / (path.lstrip("/") or "index.html")
        if not file_path.exists() or not file_path.is_file():
            file_path = web_dir / "index.html"

        mime_map = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }
        content_type = mime_map.get(file_path.suffix, "application/octet-stream")

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_error(404)

    def _task_route(self, path: str) -> tuple[str, str] | None:
        """Parse /api/tasks/<task_id>/<suffix>; project comes from query/body."""
        prefix = "/api/tasks/"
        if not path.startswith(prefix):
            return None
        rest = path[len(prefix):].strip("/")
        if "/" not in rest:
            return None
        task_id, suffix = rest.split("/", 1)
        if not task_id or not task_id.startswith("task_"):
            return None
        return task_id, suffix

    def _sse_task_events(self, project: str, task_id: str):
        """Stream the current task event log as Server-Sent Events."""
        run_dir = task_run_dir(project, task_id)
        if not run_dir.exists():
            self._json_response({"success": False, "error": "Task not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors_headers()
        self.end_headers()

        from task_events import load_task_events

        events = load_task_events(run_dir)
        if not events:
            events = [{
                "time": utc_now_iso(),
                "event": "NO_EVENTS",
                "stage": None,
                "status": None,
                "severity": "INFO",
                "message": "No task events recorded yet.",
                "payload": {},
            }]
        try:
            for index, event in enumerate(events):
                self.wfile.write(f"id: {index}\n".encode("utf-8"))
                self.wfile.write(f"event: {event.get('event', 'task_event')}\n".encode("utf-8"))
                data = json.dumps(event, ensure_ascii=False, default=self._json_default)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # API routes
        if path == "/api/projects":
            return self._json_response(handle_get_projects())

        if path == "/api/tasks":
            project = params.get("project", ["AgentLab"])[0]
            return self._json_response(handle_get_tasks(project))

        if path == "/api/status":
            project = params.get("project", ["AgentLab"])[0]
            task_id = params.get("task", [""])[0]
            return self._json_response(handle_get_status(project, task_id))

        if path == "/api/health":
            return self._json_response({"status": "ok", "timestamp": utc_now_iso()})

        if path == "/api/system/doctor":
            try:
                result = subprocess.run(
                    [sys.executable, str(AGENTLAB_ROOT / "agent_runtime" / "run_task.py"), "doctor", "--json-output"],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(AGENTLAB_ROOT),
                )
                return self._json_response(json.loads(result.stdout))
            except Exception:
                return self._json_response({"status": "fail", "error": "doctor command failed"})

        if path == "/api/system/status":
            project = params.get("project", ["AgentLab"])[0]
            task_id = params.get("task", [""])[0]
            return self._json_response(handle_get_system_status(project, task_id))

        task_route = self._task_route(path)
        if task_route:
            task_id, suffix = task_route
            project = params.get("project", ["AgentLab"])[0]
            if suffix == "events":
                return self._json_response(handle_get_task_events(project, task_id))
            if suffix == "events/stream":
                return self._sse_task_events(project, task_id)
            if suffix == "decisions":
                all_statuses = params.get("all", ["false"])[0].lower() in {"1", "true", "yes"}
                return self._json_response(handle_get_task_decisions(project, task_id, all_statuses=all_statuses))
            return self._json_response({"error": "Unknown task endpoint"}, 404)

        if path == "/api/system/migration-doctor":
            project = params.get("project", ["AgentLab"])[0]
            return self._json_response(run_cli_json(["migration-doctor", "--project", project, "--json-output", "--no-write-probe"]))

        if path == "/api/backup/status":
            project = params.get("project", ["AgentLab"])[0]
            task_id = params.get("task", [""])[0]
            args = ["backup-status", "--project", project, "--json-output"]
            if task_id:
                args.extend(["--task-id", task_id])
            return self._json_response(run_cli_json(args))

        if path == "/api/backup/truenas-status":
            project = params.get("project", ["AgentLab"])[0]
            return self._json_response(run_cli_json(["truenas-status", "--project", project, "--json-output", "--no-write-probe"]))

        # /api/tasks/<project>/<task_id>/snapshot
        if "/api/tasks/" in path and "/snapshot" in path:
            parts = path.replace("/api/tasks/", "").rsplit("/snapshot", 1)
            if len(parts) == 2:
                proj_task = parts[0].split("/", 1)
                if len(proj_task) == 2:
                    snapshot = handle_get_status(proj_task[0], proj_task[1])
                    return self._json_response(snapshot)
            return self._json_response({"error": "invalid path"}, 400)

        # /api/tasks/<project>/<task_id>/artifact/<filename>
        if "/api/tasks/" in path and "/artifact/" in path:
            parts = path.replace("/api/tasks/", "").rsplit("/artifact/", 1)
            if len(parts) == 2:
                proj_task = parts[0].split("/", 1)
                filename = parts[1]
                if len(proj_task) == 2 and filename:
                    run_dir = AGENTLAB_ROOT / "projects" / proj_task[0] / "runs" / proj_task[1]
                    artifact_path = run_dir / filename
                    if artifact_path.exists():
                        return self._json_response({
                            "filename": filename,
                            "size": artifact_path.stat().st_size,
                            "content": read_text(artifact_path)[:5000],
                        })
                    return self._json_response({"filename": filename, "error": "not found"}, 404)
            return self._json_response({"error": "invalid path"}, 400)

        if path == "/api/config":
            if not self._require_web_auth():
                return
            from agent_runtime.config_loader import load_agentlab_configs
            import os as _os
            configs = load_agentlab_configs(AGENTLAB_ROOT)
            # Redact API keys
            for provider in configs.get("model_providers", {}).get("providers", {}).values():
                if "api_key" in provider:
                    provider["api_key"] = "env:REDACTED"
            return self._json_response(configs)

        # Static files
        if path == "/" or path == "":
            return self._serve_static("index.html")

        return self._serve_static(path)

    def _require_web_auth(self) -> bool:
        """Require AGENTLAB_WEB_UI_TOKEN for sensitive endpoints.

        Returns True if authorized, False if not (sends 401 response).
        """
        required_token = os.getenv("AGENTLAB_WEB_UI_TOKEN")
        if not required_token:
            self._json_response({"error": "AGENTLAB_WEB_UI_TOKEN is not configured; Web UI execution is disabled.", "success": False}, 403)
            return False
        supplied = self.headers.get("X-AgentLab-Token") or ""
        if supplied != required_token:
            self._json_response({"error": "Invalid or missing AgentLab Web UI token.", "success": False}, 401)
            return False
        return True

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            data = {}

        # ── All POST endpoints require token auth ──
        if not self._require_web_auth():
            return

        if path == "/api/decision":
            return self._json_response(handle_post_decision(data))

        if path == "/api/agent/action":
            return self._json_response(handle_run_agent(data))

        if path == "/api/task/create":
            return self._json_response(handle_create_task(data))

        if path == "/api/task/nl":
            return self._json_response(handle_natural_language_task(data))

        if path == "/api/subtask/create":
            return self._json_response(handle_create_subtask(data))

        if path == "/api/project/create":
            return self._json_response(handle_create_project(data))

        if path == "/api/task/run-next":
            return self._json_response(handle_run_next_agents(data))

        if path == "/api/backup/truenas-sync":
            return self._json_response(handle_post_truenas_sync(data, self.headers))

        task_route = self._task_route(path)
        if task_route:
            task_id, suffix = task_route
            project = data.get("project", "AgentLab")
            if suffix.startswith("decisions/"):
                parts = suffix.split("/")
                if len(parts) == 3 and parts[2] in {"approve", "reject"}:
                    resolution = "approved" if parts[2] == "approve" else "rejected"
                    return self._json_response(handle_resolve_task_decision(project, task_id, parts[1], resolution, data))
            if suffix in {"resume", "pause", "stop"}:
                return self._json_response(handle_task_control(project, task_id, suffix, data))
            return self._json_response({"error": "Unknown task endpoint"}, 404)

        # Unknown
        self._json_response({"error": "Unknown endpoint"}, 404)

    def log_message(self, format, *args):
        """Suppress default logging to stdout."""
        pass


def main():
    port = int(os.getenv("AGENTLAB_PORT", "8765"))
    bind_host = os.getenv("AGENTLAB_WEB_UI_BIND", "127.0.0.1")
    server = HTTPServer((bind_host, port), AgentLabAPIHandler)
    print(f"\n  AgentLab Web UI 后端服务已启动")
    print(f"  → http://localhost:{port}")
    print(f"  Bind: {bind_host}:{port}")
    if bind_host != "127.0.0.1":
        print(f"  ⚠  WARNING: binding to {bind_host}. Ensure AGENTLAB_WEB_UI_TOKEN is configured.")
    print(f"\n  按 Ctrl+C 停止服务\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
