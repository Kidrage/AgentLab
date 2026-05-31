"""AgentLab Terminal Chat REPL.

Provides a rule-based chat loop that understands slash commands and
free-text task creation / follow-up instructions.  No LLM is needed
to parse intents — chat_router handles that deterministically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from chat_router import ChatIntent, parse_input
from policies import ensure_safe_task_id, generate_slug_from_request, resolve_agentlab_root
from state_store import load_state, mark_planned, save_state, utc_now

_HELP_TEXT = """
Available commands:
  /help                 Show this help
  /new <text>           Create a new task from text
  /task <task_id>       Attach to an existing task
  /status               Show task status
  /progress             Show route and agent progress
  /plan                 Show workflow plan summary
  /run <AgentName>      Run a specific agent (dry-run unless --execute)
  /run-next             Run the next pending agent
  /check                Run rule-based self-check
  /push /sync           Self-check then commit & push to GitHub
  /pause                Pause the current task
  /resume               Resume a paused task
  /providers            Show provider status
  /models               Show configured models
  /open                 Print task run directory path
  /exit                 Close chat session

Free text (no slash) → create a new task or add a follow-up instruction.
""".strip()


def _prompt(project: str, task_id: str = "no-task") -> str:
    return f"AgentLab[{project}/{task_id}]> "


def _write_transcript(run_dir: Path, role: str, message: str) -> None:
    """Append a turn to chat_transcript.md."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    transcript = run_dir / "chat_transcript.md"
    run_dir.mkdir(parents=True, exist_ok=True)
    entry = f"## {ts} — {role}\n\n{message}\n\n"
    if transcript.exists():
        transcript.write_text(transcript.read_text(encoding="utf-8") + entry, encoding="utf-8")
    else:
        transcript.write_text(f"# Chat Transcript\n\n{entry}", encoding="utf-8")


def chat_main(
    agentlab_root: str,
    project: str,
    *,
    task_id: Optional[str] = None,
    new_task: bool = False,
    execute: bool = False,
    auto_sync: bool = True,
) -> None:
    """Run the Terminal chat REPL.

    Parameters:
        agentlab_root: resolved AgentLab root directory path
        project: project name
        task_id: attach to an existing task if provided
        new_task: start in new-task mode
        execute: allow executing model API calls
        auto_sync: enable auto-push after successful runs (still requires self-check pass)
    """
    print(f"\nAgentLab Terminal Chat — {project}")
    if execute:
        print("[execute mode: API calls allowed]")
    else:
        print("[dry-run mode: API calls require confirmation]")
    if not auto_sync:
        print("[auto-sync disabled]")
    print(f"Type /help for commands, /exit to quit.\n")

    active_task_id = task_id
    root = Path(agentlab_root)
    run_dir: Optional[Path] = None
    if active_task_id:
        run_dir = root / "projects" / project / "runs" / active_task_id

    while True:
        try:
            line = input(_prompt(project, active_task_id or "no-task"))
        except (EOFError, KeyboardInterrupt):
            print("\n[/exit]")
            break

        has_active = active_task_id is not None and run_dir is not None
        intent, payload = parse_input(line, has_active_task=has_active)

        match intent:
            case ChatIntent.EXIT:
                print("[/exit] Session closed.")
                break

            case ChatIntent.HELP:
                print(_HELP_TEXT)

            case ChatIntent.UNKNOWN:
                if not line.strip():
                    continue
                print("Unknown command. Type /help for available commands.")

            case ChatIntent.NEW_TASK:
                text = payload or ""
                slug = generate_slug_from_request(text) if text else "chat-task"
                new_id = _next_task_id(root, project)
                if slug:
                    new_id = f"{new_id}_{slug}"
                print(f"Creating task: {new_id}")
                active_task_id = new_id
                run_dir = root / "projects" / project / "runs" / new_id
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "user_request.md").write_text(f"# User Request\n\n{text}\n", encoding="utf-8")
                _write_transcript(run_dir, "user", text)
                _write_transcript(run_dir, "agentlab", f"Task created: {new_id}")
                print(f"Task {new_id} created. Run ./agentlab.sh prepare --project {project} --task-id {new_id} --write-plan to prepare workflow.")
                state = load_state(run_dir, project, new_id)
                state.status = "new"
                state.last_event = "Task created via chat."
                save_state(run_dir, state)

            case ChatIntent.ATTACH_TASK:
                tid = payload or ""
                attach_dir = root / "projects" / project / "runs" / tid
                if attach_dir.exists():
                    active_task_id = tid
                    run_dir = attach_dir
                    print(f"Attached to task: {tid}")
                else:
                    print(f"Task not found: {tid}")

            case ChatIntent.STATUS:
                if not run_dir:
                    print("No active task. Use /new <text> or /task <task_id>.")
                    continue
                state = load_state(run_dir, project, active_task_id or "")
                print(f"Status: {state.status}")
                print(f"Last event: {state.last_event}")
                print(f"Completed agents: {state.completed_agents}")
                print(f"Current agent: {state.current_agent or '(none)'}")

            case ChatIntent.PROGRESS:
                if not run_dir:
                    print("No active task.")
                    continue
                from progress_tracker import load_progress, progress_summary
                data = load_progress(run_dir)
                if data is None:
                    print("No progress.yml yet. Run prepare first.")
                else:
                    s = progress_summary(data)
                    print(f"Progress: {s['percent']}% — {s['status']}")
                    for ag in s.get("agents", []):
                        icon = {"completed": "✓", "active": "→", "paused": "⏸", "waiting": "·"}.get(ag["status"], "?")
                        print(f"  {icon} {ag['name']:20s} {ag['status']:12s} {ag['provider']:15s} {ag['tokens']} tokens")

            case ChatIntent.PLAN:
                if not run_dir:
                    print("No active task.")
                    continue
                plan_path = run_dir / "workflow_plan.yml"
                if not plan_path.exists():
                    print("No workflow plan. Run prepare first.")
                else:
                    import yaml
                    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
                    route = plan.get("route", {})
                    agents = route.get("agents", []) if isinstance(route, dict) else []
                    print(f"Route: {' → '.join(agents) if agents else 'not planned'}")
                    print(f"Budget mode: {plan.get('budget_mode', '?')}")

            case ChatIntent.RUN_AGENT:
                agent = payload or ""
                if not agent:
                    print("Usage: /run <AgentName>")
                    continue
                print(f"[dispatch] ./agentlab.sh run-agent {agent} --project {project} --task-id {active_task_id or 'task_0001'} {'--execute' if execute else ''}")

            case ChatIntent.RUN_NEXT:
                print(f"[dispatch] ./agentlab.sh run-next --project {project} --task-id {active_task_id or 'task_0001'} {'--execute' if execute else ''}")

            case ChatIntent.CHECK:
                print(f"[dispatch] ./agentlab.sh check --project {project} --task-id {active_task_id or 'task_0001'}")

            case ChatIntent.SYNC:
                print(f"[dispatch] ./agentlab.sh sync --project {project} --task-id {active_task_id or 'task_0001'}")

            case ChatIntent.PAUSE:
                print(f"[dispatch] ./agentlab.sh pause --project {project} --task-id {active_task_id or 'task_0001'}")

            case ChatIntent.RESUME:
                print(f"[dispatch] ./agentlab.sh resume --project {project} --task-id {active_task_id or 'task_0001'}")

            case ChatIntent.PROVIDERS:
                print(f"[dispatch] ./agentlab.sh providers")

            case ChatIntent.MODELS:
                print(f"[dispatch] ./agentlab.sh models")

            case ChatIntent.OPEN_PATH:
                if run_dir:
                    print(str(run_dir))
                else:
                    print(str(root / "projects" / project / "runs"))

            case ChatIntent.FOLLOWUP:
                if not run_dir:
                    print("No active task.")
                    continue
                text = payload or ""
                followup = run_dir / "followup_instructions.md"
                if followup.exists():
                    followup.write_text(followup.read_text(encoding="utf-8") + f"\n\n{text}", encoding="utf-8")
                else:
                    followup.write_text(f"# Follow-up Instructions\n\n{text}\n", encoding="utf-8")
                _write_transcript(run_dir, "user", text)
                _write_transcript(run_dir, "agentlab", f"Follow-up instruction appended.")
                state = load_state(run_dir, project, active_task_id or "")
                state.last_event = "User follow-up added."
                save_state(run_dir, state)
                print("Follow-up instruction saved.")


def _next_task_id(root: Path, project: str) -> str:
    runs_dir = root / "projects" / project / "runs"
    if not runs_dir.exists():
        return "task_0001"
    existing = [d.name for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("task_")]
    if not existing:
        return "task_0001"
    nums = []
    for name in existing:
        try:
            nums.append(int(name[5:5 + 4]))
        except ValueError:
            pass
    next_num = max(nums) + 1 if nums else 1
    return f"task_{next_num:04d}"