#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$ROOT/agent_runtime/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON:-python3}"
fi

# Load environment variables from .env file
if [[ -f "$ROOT/agent_runtime/.env" ]]; then
  set -a
  source "$ROOT/agent_runtime/.env"
  set +a
fi

cd "$ROOT/agent_runtime"

# ─── Codex Full-Driver Mode CLI Commands ────────────────────────────────
case "${1:-}" in
  codex-start)
    shift
    exec "$PYTHON_BIN" -c "
import sys, yaml, typer
from pathlib import Path
from run_task import runtime_context
from handoff_builder import write_handoff_packet
from state_store import load_state, save_state
from rich.console import Console

console = Console()
agentlab_root, project_name = runtime_context(None)

# Parse args
project = None
task_id = None
request_file = None
mode = 'full-driver'
i = 1
while i < len(sys.argv):
    if sys.argv[i] == '--project' and i+1 < len(sys.argv):
        project = sys.argv[i+1]; i += 2
    elif sys.argv[i] == '--task-id' and i+1 < len(sys.argv):
        task_id = sys.argv[i+1]; i += 2
    elif sys.argv[i] == '--request-file' and i+1 < len(sys.argv):
        request_file = sys.argv[i+1]; i += 2
    elif sys.argv[i] == '--mode' and i+1 < len(sys.argv):
        mode = sys.argv[i+1]; i += 2
    else:
        i += 1

console.print(f'[bold]Codex Full-Driver: {task_id}[/bold]')
console.print(f'  Project: {project or project_name}')
console.print(f'  Mode: {mode}')
console.print(f'  Request file: {request_file or \"(none)\"}')
console.print()
console.print('[green]Task initialized. Begin with preflight → supervisor → reposcout → ... → archivist → handoff[/green]')
" "$@"
    ;;
  codex-status)
    shift
    exec "$PYTHON_BIN" -c "
import sys
from pathlib import Path
from run_task import runtime_context
from state_store import load_state
from rich.console import Console

console = Console()
agentlab_root, project_name = runtime_context(None)

task_id = 'task_0001'
if len(sys.argv) > 1:
    for i, arg in enumerate(sys.argv):
        if arg == '--task-id' and i+1 < len(sys.argv):
            task_id = sys.argv[i+1]
        elif arg == '--project' and i+1 < len(sys.argv):
            project_name = sys.argv[i+1]

project_root = agentlab_root / 'projects' / project_name
run_dir = project_root / 'runs' / task_id
state = load_state(run_dir, project_name, task_id)

console.print(f'[bold]Codex Task Status: {task_id}[/bold]')
console.print(f'  Project: {project_name}')
console.print(f'  Status: {state.status}')
console.print(f'  Execution mode: {getattr(state, \"execution_mode\", \"codex_full_driver\")}')
console.print(f'  Current agent: {state.current_agent}')
console.print(f'  Completed agents: {state.completed_agents}')
console.print(f'  Next agent: {getattr(state, \"next_agent\", \"?\")}')
console.print(f'  Blocked: {state.blocked}')
" "$@"
    ;;
  codex-handoff)
    shift
    exec "$PYTHON_BIN" -c "
import sys
from pathlib import Path
from run_task import runtime_context
from handoff_builder import build_handoff_packet, write_handoff_packet
from rich.console import Console

console = Console()
agentlab_root, project_name = runtime_context(None)

task_id = 'task_0001'
if len(sys.argv) > 1:
    for i, arg in enumerate(sys.argv):
        if arg == '--task-id' and i+1 < len(sys.argv):
            task_id = sys.argv[i+1]
        elif arg == '--project' and i+1 < len(sys.argv):
            project_name = sys.argv[i+1]

project_root = agentlab_root / 'projects' / project_name
packet = build_handoff_packet(project_root, task_id)
path = write_handoff_packet(project_root, task_id, packet)
console.print(f'[green]Handoff packet written:[/green] {path}')
console.print(f'  Status: {packet[\"status\"]}')
console.print(f'  Last agent: {packet[\"last_completed_agent\"]}')
console.print(f'  Next agent: {packet[\"next_agent\"]}')
" "$@"
    ;;
  codex-resume)
    shift
    exec "$PYTHON_BIN" -c "
import sys
from pathlib import Path
from run_task import runtime_context
from api_continuation import load_handoff_packet, print_continuation_plan
from rich.console import Console

console = Console()
agentlab_root, project_name = runtime_context(None)

task_id = 'task_0001'
from_file = 'handoff_packet.yml'
if len(sys.argv) > 1:
    for i, arg in enumerate(sys.argv):
        if arg == '--task-id' and i+1 < len(sys.argv):
            task_id = sys.argv[i+1]
        elif arg == '--project' and i+1 < len(sys.argv):
            project_name = sys.argv[i+1]
        elif arg == '--from' and i+1 < len(sys.argv):
            from_file = sys.argv[i+1]

project_root = agentlab_root / 'projects' / project_name
handoff = load_handoff_packet(project_root, task_id)
if handoff is None:
    console.print(f'[red]No handoff packet found for {task_id}[/red]')
    sys.exit(1)

console.print(f'[bold]Resume: {task_id}[/bold]')
console.print(f'  Status: {handoff[\"status\"]}')
console.print(f'  Next agent: {handoff[\"next_agent\"]}')
console.print(f'  Resume available: {handoff[\"resume_available\"]}')
console.print()
console.print('[green]To continue with API agents:[/green]')
console.print(f'  ./agentlab.sh continue-with-api --project {project_name} --task-id {task_id} --from {from_file}')
console.print()
console.print('[green]To continue manually:[/green]')
console.print(f'  Read {project_root}/runs/{task_id}/handoff_packet.yml')
" "$@"
    ;;
  codex-verify-artifacts)
    shift
    exec "$PYTHON_BIN" -c "
import sys
from pathlib import Path
from run_task import runtime_context
from codex_artifact_validator import validate_artifacts, print_validation_report
from rich.console import Console

console = Console()
agentlab_root, project_name = runtime_context(None)

task_id = 'task_0001'
if len(sys.argv) > 1:
    for i, arg in enumerate(sys.argv):
        if arg == '--task-id' and i+1 < len(sys.argv):
            task_id = sys.argv[i+1]
        elif arg == '--project' and i+1 < len(sys.argv):
            project_name = sys.argv[i+1]

project_root = agentlab_root / 'projects' / project_name
result = validate_artifacts(project_root, task_id)
print_validation_report(result)
" "$@"
    ;;
  continue-with-api)
    shift
    exec "$PYTHON_BIN" -c "
import sys
from pathlib import Path
from run_task import runtime_context
from api_continuation import continue_with_api, print_continuation_plan
from rich.console import Console

console = Console()
agentlab_root, project_name = runtime_context(None)

task_id = 'task_0001'
from_file = 'handoff_packet.yml'
dry_run = True
if len(sys.argv) > 1:
    for i, arg in enumerate(sys.argv):
        if arg == '--task-id' and i+1 < len(sys.argv):
            task_id = sys.argv[i+1]
        elif arg == '--project' and i+1 < len(sys.argv):
            project_name = sys.argv[i+1]
        elif arg == '--from' and i+1 < len(sys.argv):
            from_file = sys.argv[i+1]
        elif arg == '--execute':
            dry_run = False

project_root = agentlab_root / 'projects' / project_name
result = continue_with_api(project_root, task_id, dry_run=dry_run)
print_continuation_plan(result)
" "$@"
    ;;
  *)
    # Fall through to the standard AgentLab CLI
    exec "$PYTHON_BIN" "$ROOT/agent_runtime/run_task.py" "$@"
    ;;
esac
