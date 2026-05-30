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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ────────── API handlers ──────────

def handle_get_projects():
    """List all projects."""
    projects_dir = AGENTLAB_ROOT / "projects"
    if not projects_dir.exists():
        return {"projects": []}
    projects = sorted([
        d.name for d in projects_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != ".DS_Store"
    ])
    return {"projects": projects}


def handle_get_tasks(project: str):
    """List all tasks for a project with titles and descriptions from ledger."""
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
    run_dir = AGENTLAB_ROOT / "projects" / project / "runs" / task_id
    project_root = AGENTLAB_ROOT / "projects" / project

    if not run_dir.exists():
        return {"error": f"Task {project}/{task_id} not found"}

    # Load state
    state = load_yaml_safe(run_dir / "state.yml")
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
    route_agents = plan.get("route", {}).get("agents", [])
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
    brain_policy = exec_policy.get("brain_policy", {})
    coder_policy = exec_policy.get("coder_policy", {})

    return {
        "generatedAt": utc_now_iso(),
        "project": project,
        "taskId": task_id,
        "taskStatus": state.get("status", "new"),
        "stage": state.get("last_event", ""),
        "userRequest": user_request[:2000] if user_request else "",
        "coderProvider": "codex-plus",
        "coderQuotaRemaining": coder_policy.get("codex_quota_remaining", 0),
        "coderQuotaWarningThreshold": 2000,
        "brainProvider": brain_policy.get("required_provider", "deepseek"),
        "qwenFallback": {
            "provider": "Qwen",
            "enabled": bool(os.getenv("QWEN_API_KEY")),
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


def handle_post_decision(data: dict):
    """Handle user decision submission."""
    project = data.get("project", "AgentLab")
    task_id = data.get("taskId", "task_0004")
    action = data.get("action", "yes")  # yes / no / later

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
    project = data.get("project", "AgentLab")
    task_id = data.get("taskId", "task_0004")
    agent_name = data.get("agentName", "")
    action = data.get("action", "run")  # run, pause, stop, execute

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
    project = data.get("project", "AgentLab")
    task_id = data.get("taskId", "")
    request_text = data.get("requestText", "")
    backend = data.get("backend", "codex")  # codex or qwen

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
            "message": result.stdout[:500],
        }
    except Exception as e:
        return {"success": False, "taskId": task_id, "error": str(e)}


def handle_natural_language_task(data: dict):
    """Create a task from natural language description and optionally start execution."""
    project = data.get("project", "AgentLab")
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
    project = data.get("project", "AgentLab")
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


# ────────── HTTP server ──────────

class AgentLabAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for AgentLab API."""

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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
            task_id = params.get("task", ["task_0004"])[0]
            return self._json_response(handle_get_status(project, task_id))

        if path == "/api/config":
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

        if path == "/api/decision":
            return self._json_response(handle_post_decision(data))

        if path == "/api/agent/action":
            return self._json_response(handle_run_agent(data))

        if path == "/api/task/create":
            return self._json_response(handle_create_task(data))

        if path == "/api/task/nl":
            return self._json_response(handle_natural_language_task(data))

        if path == "/api/task/run-next":
            return self._json_response(handle_run_next_agents(data))

        # Unknown
        self._json_response({"error": "Unknown endpoint"}, 404)

    def log_message(self, format, *args):
        """Suppress default logging to stdout."""
        pass


def main():
    port = int(os.getenv("AGENTLAB_PORT", "8765"))
    server = HTTPServer(("0.0.0.0", port), AgentLabAPIHandler)
    print(f"\n  AgentLab Web UI 后端服务已启动")
    print(f"  → http://localhost:{port}\n")
    print(f"  按 Ctrl+C 停止服务\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()