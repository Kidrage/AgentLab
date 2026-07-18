"""Thin AgentLab MCP-style tool server.

The module has no mandatory MCP SDK dependency. It exposes tool schemas and
structured handlers for tests and local stdio JSON-RPC smoke usage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import argparse
import json
import subprocess
import sys

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from atomic_io import safe_read_yaml
from feedback_manager import load_pending_decision_cards, resolve_decision_card
from skill_evolution import (
    approve_skill_request,
    build_skill_adoption_request,
    load_skill_requests,
    reject_skill_request,
    write_skill_adoption_request,
)
from task_events import load_task_events
from skills.incubation import load_incubation_policy, propose_internal_skill_candidates
from skills.registry import load_skill_registry as load_external_skill_registry
from skills.usage_ledger import load_skill_usage_ledger

PROTOCOL_VERSION = "2025-06-18"
SERVER_VERSION = "0.1.0"


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_policy(agentlab_root: Path) -> dict[str, Any]:
    policy = safe_read_yaml(agentlab_root / "config" / "mcp_policy.yml", default={}) or {}
    policy.setdefault("enabled", False)
    profiles = policy.get("profiles") or {}
    default_profile = policy.get("default_profile")
    if default_profile and default_profile in profiles:
        merged = dict(profiles[default_profile] or {})
        for key, value in policy.items():
            if key not in {"profiles", "default_profile"} and key not in merged:
                merged[key] = value
        policy = merged
    policy.setdefault("allow_task_creation", True)
    policy.setdefault("allow_decision_approval", True)
    policy.setdefault("allow_skill_approval", True)
    policy.setdefault("allow_stop_task", False)
    return policy


def _schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "required": required, "properties": properties, "additionalProperties": False}


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "agentlab_create_task": _schema(["project", "task_id", "request_text"], {
        "project": {"type": "string"},
        "task_id": {"type": "string"},
        "request_text": {"type": "string"},
    }),
    "agentlab_get_task_status": _schema(["project", "task_id"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_get_task_events": _schema(["project", "task_id"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_get_task_report": _schema(["project", "task_id"], {
        "project": {"type": "string"},
        "task_id": {"type": "string"},
        "report": {"type": "string", "default": "07_validation_report.md"},
    }),
    "agentlab_list_decisions": _schema(["project", "task_id"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_approve_decision": _schema(["project", "task_id", "decision_id"], {
        "project": {"type": "string"},
        "task_id": {"type": "string"},
        "decision_id": {"type": "string"},
        "option": {"type": "string", "default": "approve_resume"},
    }),
    "agentlab_reject_decision": _schema(["project", "task_id", "decision_id"], {
        "project": {"type": "string"},
        "task_id": {"type": "string"},
        "decision_id": {"type": "string"},
        "option": {"type": "string", "default": "stop_task"},
    }),
    "agentlab_resume_task": _schema(["project", "task_id"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_pause_task": _schema(["project", "task_id"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_stop_task": _schema(["project", "task_id"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_list_skill_requests": _schema(["project"], {"project": {"type": "string"}, "status": {"type": "string"}}),
    "agentlab_request_skill_learning": _schema(["project", "skill_name", "source", "purpose"], {
        "project": {"type": "string"},
        "skill_name": {"type": "string"},
        "source": {"type": "string"},
        "purpose": {"type": "string"},
        "source_type": {"type": "string", "default": "manual"},
    }),
    "agentlab_approve_skill_request": _schema(["project", "request_id"], {"project": {"type": "string"}, "request_id": {"type": "string"}}),
    "agentlab_reject_skill_request": _schema(["project", "request_id"], {
        "project": {"type": "string"},
        "request_id": {"type": "string"},
        "reason": {"type": "string", "default": "Rejected through MCP tool."},
    }),
    "agentlab_list_active_skills": _schema([], {"project": {"type": "string"}}),
    "agentlab_get_skill_usage": _schema(["skill_id"], {"skill_id": {"type": "string"}, "project": {"type": "string"}}),
    "agentlab_webhook_status": _schema(["project"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_watchdog_scan": _schema(["project"], {"project": {"type": "string"}, "task_id": {"type": "string"}}),
    "agentlab_list_external_skills": _schema([], {"source": {"type": "string"}, "enabled_only": {"type": "boolean", "default": False}}),
    "agentlab_get_skill_registry": _schema([], {}),
    "agentlab_get_skill_incubation_candidates": _schema([], {"task_id": {"type": "string"}}),
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "agentlab_create_task": "State-changing. Use this to create a new AgentLab task only when the user explicitly asks to start tracked work. Requires project, task_id, and request_text. Creates local task files and returns structured JSON with command output and task identifiers.",
    "agentlab_get_task_status": "Read-only. Use this to inspect the current lifecycle status, feedback state, and pending action summary for an AgentLab task. Requires project and task_id. Returns structured JSON with status, stage, latest event, cost ledger, and pending decisions.",
    "agentlab_get_task_events": "Read-only. Use this to review the timeline of recorded AgentLab task events. Requires project and task_id. Returns structured JSON containing the task event list.",
    "agentlab_get_task_report": "Read-only. Use this to fetch a bounded AgentLab task report for inspection. Requires project and task_id, with optional report filename. Returns structured JSON with existence, report name, and report content.",
    "agentlab_list_decisions": "Read-only. Use this to list pending AgentLab decision cards before asking the user what to do. Requires project and task_id. Returns structured JSON with pending decision card details.",
    "agentlab_approve_decision": "State-changing. Use this only after the user explicitly approves a pending AgentLab decision card. Requires project, task_id, decision_id, and option. Records the user decision and returns the recommended next action.",
    "agentlab_reject_decision": "State-changing. Use this only after the user explicitly rejects or stops a pending AgentLab decision card. Requires project, task_id, decision_id, and optional option. Records the rejection and returns structured JSON with the selected option.",
    "agentlab_resume_task": "State-changing. Use this only after the user explicitly wants a paused or approved AgentLab task to resume. Requires project and task_id. Updates local task control state and returns the control result.",
    "agentlab_pause_task": "State-changing. Use this only after the user explicitly asks to pause an AgentLab task. Requires project and task_id. Updates local task control state and returns the control result.",
    "agentlab_stop_task": "State-changing. Use this only after the user explicitly asks to stop an AgentLab task. Requires project and task_id. Updates local task control state when policy allows stop actions and returns the control result.",
    "agentlab_list_skill_requests": "Read-only. Use this to inspect pending or historical AgentLab skill adoption requests. Requires project, with optional status filter. Returns structured JSON with matching skill requests.",
    "agentlab_request_skill_learning": "State-changing. Use this only when the user asks AgentLab to learn or track a reusable skill. Requires project, skill_name, source, purpose, and optional source_type. Creates a local skill adoption request and returns its id and status.",
    "agentlab_approve_skill_request": "State-changing. Use this only after the user explicitly approves a pending AgentLab skill request. Requires project and request_id. Updates local skill lifecycle state and returns the request status.",
    "agentlab_reject_skill_request": "State-changing. Use this only after the user explicitly rejects a pending AgentLab skill request. Requires project, request_id, and optional reason. Updates local skill lifecycle state and returns the request status.",
    "agentlab_list_active_skills": "Read-only. Use this to inspect currently active AgentLab skills available for retrieval and injection. Requires no input, with optional project accepted for clients that pass one. Returns structured JSON with active skill registry entries.",
    "agentlab_get_skill_usage": "Read-only. Use this to inspect usage history for one active AgentLab skill. Requires skill_id, with optional project accepted for clients that pass one. Returns structured JSON with the skill usage ledger.",
    "agentlab_webhook_status": "Read-only. Use this to inspect local webhook delivery status for AgentLab feedback events. Requires project and optional task_id. Returns structured JSON with delivery log metadata and entries.",
    "agentlab_watchdog_scan": "State-changing. Use this only when the user explicitly asks to scan AgentLab tasks for stale or blocked state. Requires project and optional task_id. May update feedback status or decision cards and returns scan results.",
    "agentlab_list_external_skills": "Read-only. Lists metadata for registered external skills. Does not enable, dispatch, or execute any external skill.",
    "agentlab_get_skill_registry": "Read-only. Returns the external skill registry metadata. Does not mutate registry state or execute external providers.",
    "agentlab_get_skill_incubation_candidates": "Read-only. Returns existing internal_skill_candidates.yml if present, or computes in-memory candidates from registry and an optional skill_usage_ledger.yml without writing files.",
}


def list_tools() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": TOOL_DESCRIPTIONS[name], "inputSchema": schema}
        for name, schema in TOOL_SCHEMAS.items()
    ]


def _run_dir(agentlab_root: Path, project: str, task_id: str) -> Path:
    return agentlab_root / "projects" / project / "runs" / task_id


def _latest_event(run_dir: Path) -> dict[str, Any] | None:
    events = load_task_events(run_dir, limit=1)
    return events[-1] if events else None


def _tool_create_task(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    policy = load_policy(agentlab_root)
    if not policy.get("allow_task_creation", True):
        return {"ok": False, "error": "Task creation is disabled by mcp_policy.yml"}
    cmd = [
        sys.executable,
        str(agentlab_root / "agent_runtime" / "run_task.py"),
        "init-task",
        "--project",
        args["project"],
        "--task-id",
        args["task_id"],
        "--request-text",
        args["request_text"],
    ]
    result = subprocess.run(cmd, cwd=str(agentlab_root), capture_output=True, text=True, timeout=30)
    return {"ok": result.returncode == 0, "project": args["project"], "task_id": args["task_id"], "stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]}


def _tool_get_task_status(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_dir = _run_dir(agentlab_root, args["project"], args["task_id"])
    state = safe_read_yaml(run_dir / "state.yml", default={}) or {}
    progress = safe_read_yaml(run_dir / "progress.yml", default={}) or {}
    pending = load_pending_decision_cards(run_dir)
    latest = _latest_event(run_dir)
    status = progress.get("status") or state.get("status") or "unknown"
    return {
        "project": args["project"],
        "task_id": args["task_id"],
        "status": status,
        "stage": progress.get("current_stage") or state.get("last_event"),
        "requires_action": bool(pending),
        "pending_decisions": len(pending),
        "latest_event": latest,
        "cost": safe_read_yaml(run_dir / "cost_ledger.yml", default={"entries": []}) or {"entries": []},
    }


def _tool_get_task_events(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_dir = _run_dir(agentlab_root, args["project"], args["task_id"])
    return {"project": args["project"], "task_id": args["task_id"], "events": load_task_events(run_dir)}


def _tool_get_task_report(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    report = args.get("report") or "07_validation_report.md"
    safe_name = Path(report).name
    path = _run_dir(agentlab_root, args["project"], args["task_id"]) / safe_name
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    return {"project": args["project"], "task_id": args["task_id"], "report": safe_name, "exists": path.exists(), "content": content[:5000]}


def _tool_list_decisions(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    run_dir = _run_dir(agentlab_root, args["project"], args["task_id"])
    return {"project": args["project"], "task_id": args["task_id"], "decisions": load_pending_decision_cards(run_dir)}


def _resolve_decision(agentlab_root: Path, args: dict[str, Any], resolution: str) -> dict[str, Any]:
    policy = load_policy(agentlab_root)
    if not policy.get("allow_decision_approval", True):
        return {"ok": False, "error": "Decision approval is disabled by mcp_policy.yml"}
    run_dir = _run_dir(agentlab_root, args["project"], args["task_id"])
    option = args.get("option") or ("approve_resume" if resolution == "approved" else "stop_task")
    card = resolve_decision_card(run_dir, args["decision_id"], option_id=option, resolution=resolution, actor="mcp")
    return {"ok": True, "decision_id": args["decision_id"], "selected_option": card.get("selected_option"), "next_recommended_action": "agentlab_resume_task" if resolution == "approved" else None}


def _task_control(agentlab_root: Path, args: dict[str, Any], action: str) -> dict[str, Any]:
    policy = load_policy(agentlab_root)
    if action == "stop" and not policy.get("allow_stop_task", True):
        return {"ok": False, "error": "Stop task is disabled by mcp_policy.yml"}
    from web_ui.server import handle_task_control
    import web_ui.server as web_server

    old_root = web_server.AGENTLAB_ROOT
    web_server.AGENTLAB_ROOT = agentlab_root
    try:
        result = handle_task_control(args["project"], args["task_id"], action, {"reason": "mcp_tool"})
    finally:
        web_server.AGENTLAB_ROOT = old_root
    return {"ok": bool(result.get("success")), **result}


def _tool_list_skill_requests(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    return {"project": args["project"], "requests": load_skill_requests(agentlab_root, args["project"], status=args.get("status"))}


def _tool_request_skill_learning(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    request = build_skill_adoption_request(
        agentlab_root,
        project=args["project"],
        skill_name=args["skill_name"],
        source=args["source"],
        purpose=args["purpose"],
        source_type=args.get("source_type") or "manual",
    )
    path = write_skill_adoption_request(agentlab_root, request)
    return {"ok": True, "request_id": request["id"], "status": request["status"], "request": request, "path": str(path)}


def _skill_approval(agentlab_root: Path, args: dict[str, Any], approve: bool) -> dict[str, Any]:
    policy = load_policy(agentlab_root)
    if not policy.get("allow_skill_approval", True):
        return {"ok": False, "error": "Skill approval is disabled by mcp_policy.yml"}
    if approve:
        request = approve_skill_request(agentlab_root, args["project"], args["request_id"])
    else:
        request = reject_skill_request(agentlab_root, args["project"], args["request_id"], args.get("reason", "Rejected through MCP tool."))
    return {"ok": True, "request_id": args["request_id"], "status": request.get("status"), "request": request}


def _tool_list_active_skills(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    registry = safe_read_yaml(agentlab_root / "skills" / "registry.yml", default={}) or {}
    skills = [item for item in registry.get("skills", []) if item.get("status") == "active"]
    return {"skills": skills}


def _tool_get_skill_usage(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    path = agentlab_root / "skills" / "active" / args["skill_id"] / "usage_ledger.yml"
    return {"skill_id": args["skill_id"], "usage": safe_read_yaml(path, default={"entries": []}) or {"entries": []}}


def _tool_webhook_status(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from webhook_dispatcher import webhook_status

    return webhook_status(agentlab_root, args["project"], args.get("task_id"))


def _tool_watchdog_scan(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from watchdog import scan_project

    return scan_project(agentlab_root, args["project"], task_id=args.get("task_id"))


def _redact_registry_paths(registry: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(registry, default=str))
    for skill in redacted.get("external_skills", []) or []:
        for key in ("source_path", "local_path"):
            if key in skill and skill[key]:
                skill[key] = Path(str(skill[key])).name
    return redacted


def _redact_candidate_paths(data: Any, agentlab_root: Path) -> Any:
    redacted = json.loads(json.dumps(data, default=str))

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            if str(agentlab_root) in value:
                try:
                    return str(Path(value).resolve().relative_to(agentlab_root.resolve()))
                except Exception:
                    return Path(value).name
        return value

    return scrub(redacted)


def _tool_list_external_skills(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    registry = load_external_skill_registry(agentlab_root)
    skills = registry.get("external_skills", []) or []
    source = args.get("source")
    if source:
        skills = [skill for skill in skills if skill.get("source") == source]
    if args.get("enabled_only", False):
        skills = [skill for skill in skills if skill.get("enabled") is True]
    return {"skills": skills, "count": len(skills), "readonly": True}


def _tool_get_skill_registry(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    return {"registry": _redact_registry_paths(load_external_skill_registry(agentlab_root)), "readonly": True}


def _tool_get_skill_incubation_candidates(agentlab_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    project = args.get("project") or "AgentLab"
    task_id = args.get("task_id")
    if not task_id:
        return {
            "candidates": [],
            "readonly": True,
            "source": "task_id_required",
            "reason": "skill incubation evidence is run-local",
        }
    run_dir = agentlab_root / "projects" / str(project) / "runs" / str(task_id)
    existing = run_dir / "artifacts" / "internal_skill_candidates.yml"
    if existing.exists():
        data = safe_read_yaml(existing, default={"candidates": []})
        return {"candidates": _redact_candidate_paths(data, agentlab_root), "readonly": True, "source": "file"}
    usage_path = run_dir / "skill_usage_ledger.yml"
    if not usage_path.exists() and (run_dir / "skill_usage.yml").exists():
        usage_path = run_dir / "skill_usage.yml"
    registry = load_external_skill_registry(agentlab_root)
    usage = load_skill_usage_ledger(usage_path)
    policy = load_incubation_policy(agentlab_root)
    candidates = [candidate.to_dict() for candidate in propose_internal_skill_candidates(registry, usage, policy)]
    return {"candidates": _redact_candidate_paths(candidates, agentlab_root), "readonly": True, "source": "computed_in_memory"}


HANDLERS: dict[str, Callable[[Path, dict[str, Any]], dict[str, Any]]] = {
    "agentlab_create_task": _tool_create_task,
    "agentlab_get_task_status": _tool_get_task_status,
    "agentlab_get_task_events": _tool_get_task_events,
    "agentlab_get_task_report": _tool_get_task_report,
    "agentlab_list_decisions": _tool_list_decisions,
    "agentlab_approve_decision": lambda root, args: _resolve_decision(root, args, "approved"),
    "agentlab_reject_decision": lambda root, args: _resolve_decision(root, args, "rejected"),
    "agentlab_resume_task": lambda root, args: _task_control(root, args, "resume"),
    "agentlab_pause_task": lambda root, args: _task_control(root, args, "pause"),
    "agentlab_stop_task": lambda root, args: _task_control(root, args, "stop"),
    "agentlab_list_skill_requests": _tool_list_skill_requests,
    "agentlab_request_skill_learning": _tool_request_skill_learning,
    "agentlab_approve_skill_request": lambda root, args: _skill_approval(root, args, True),
    "agentlab_reject_skill_request": lambda root, args: _skill_approval(root, args, False),
    "agentlab_list_active_skills": _tool_list_active_skills,
    "agentlab_get_skill_usage": _tool_get_skill_usage,
    "agentlab_webhook_status": _tool_webhook_status,
    "agentlab_watchdog_scan": _tool_watchdog_scan,
    "agentlab_list_external_skills": _tool_list_external_skills,
    "agentlab_get_skill_registry": _tool_get_skill_registry,
    "agentlab_get_skill_incubation_candidates": _tool_get_skill_incubation_candidates,
}


def call_tool(name: str, arguments: dict[str, Any], *, agentlab_root: Path | None = None) -> dict[str, Any]:
    if name not in HANDLERS:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    root = agentlab_root or _default_root()
    return HANDLERS[name](root, dict(arguments or {}))


def mcp_tool_call_result(name: str, arguments: dict[str, Any], *, agentlab_root: Path | None = None) -> dict[str, Any]:
    try:
        result = call_tool(name, arguments, agentlab_root=agentlab_root)
        is_error = bool(isinstance(result, dict) and result.get("ok") is False and result.get("error"))
        text = json.dumps(result, ensure_ascii=False, default=str)
        if is_error:
            text = str(result.get("error") or text)
        return {"content": [{"type": "text", "text": text}], "isError": is_error}
    except Exception as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}


def list_resources() -> list[dict[str, str]]:
    return [
        {"uri": "agentlab://tasks/<project>/<task_id>/status", "name": "Task status"},
        {"uri": "agentlab://tasks/<project>/<task_id>/events", "name": "Task events"},
        {"uri": "agentlab://tasks/<project>/<task_id>/report", "name": "Task report"},
        {"uri": "agentlab://skills/active", "name": "Active skills"},
    ]


def read_resource(uri: str, *, agentlab_root: Path | None = None) -> dict[str, Any]:
    root = agentlab_root or _default_root()
    parts = uri.replace("agentlab://", "").split("/")
    if parts[:1] == ["skills"] and parts[1:] == ["active"]:
        return _tool_list_active_skills(root, {})
    if len(parts) >= 4 and parts[0] == "tasks":
        project, task_id, kind = parts[1], parts[2], parts[3]
        if kind == "status":
            return _tool_get_task_status(root, {"project": project, "task_id": task_id})
        if kind == "events":
            return _tool_get_task_events(root, {"project": project, "task_id": task_id})
        if kind == "report":
            return _tool_get_task_report(root, {"project": project, "task_id": task_id})
    return {"ok": False, "error": f"Unknown resource: {uri}"}


def serve_stdio(agentlab_root: Path | None = None) -> None:
    root = agentlab_root or _default_root()
    for line in sys.stdin:
        request: dict[str, Any] | None = None
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            method = request.get("method")
            request_id = request.get("id")
            if request_id is None:
                if method in {"notifications/initialized", "initialized"}:
                    continue
            if method == "initialize":
                requested_version = (request.get("params") or {}).get("protocolVersion")
                result = {
                    "protocolVersion": requested_version or PROTOCOL_VERSION,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "agentlab", "version": SERVER_VERSION},
                }
            elif method == "tools/list":
                result = {"tools": list_tools()}
            elif method == "tools/call":
                params = request.get("params", {})
                result = mcp_tool_call_result(params.get("name", ""), params.get("arguments", {}), agentlab_root=root)
            elif method == "resources/list":
                result = {"resources": list_resources()}
            elif method == "resources/read":
                result = read_resource((request.get("params") or {}).get("uri", ""), agentlab_root=root)
            else:
                response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
                print(json.dumps(response, ensure_ascii=False), flush=True)
                continue
            response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc.msg}"}}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id") if request else None, "error": {"code": -32000, "message": str(exc)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentLab MCP-style stdio tool server.")
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--list-resources", action="store_true")
    parser.add_argument("--call-tool")
    parser.add_argument("--args-json", default="{}")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    root = _default_root()
    if args.list_tools:
        print(json.dumps({"tools": list_tools()}, ensure_ascii=False, indent=2))
        return
    if args.list_resources:
        print(json.dumps({"resources": list_resources()}, ensure_ascii=False, indent=2))
        return
    if args.call_tool:
        print(json.dumps(call_tool(args.call_tool, json.loads(args.args_json), agentlab_root=root), ensure_ascii=False, indent=2))
        return
    serve_stdio(root)


if __name__ == "__main__":
    main()
