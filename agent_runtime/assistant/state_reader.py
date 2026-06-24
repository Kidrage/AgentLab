import json
import yaml
from pathlib import Path
from .models import AssistantStateSnapshot

def read_project_state(project_id: str) -> AssistantStateSnapshot:
    from agent_runtime.run_task import _PROJECT_ROOT
    project_dir = _PROJECT_ROOT / "projects" / project_id

    snapshot = AssistantStateSnapshot(
        project_id=project_id,
        known=project_dir.exists()
    )

    if not snapshot.known:
        snapshot.warnings.append(f"Project directory {project_dir} not found.")
        return snapshot

    tasks_dir = project_dir / "tasks"
    if tasks_dir.exists():
        snapshot.source_files.append(str(tasks_dir))
        for phase_dir in tasks_dir.iterdir():
            if phase_dir.is_dir():
                state_file = phase_dir / "state.yml"
                if state_file.exists():
                    snapshot.source_files.append(str(state_file))
                    try:
                        data = yaml.safe_load(state_file.read_text()) or {}
                        snapshot.phase_statuses[phase_dir.name] = data.get("status", "unknown")
                        # Simplified checks for mock
                        if data.get("status") == "blocked":
                            snapshot.blocked_items.append(phase_dir.name)
                        if data.get("status") == "running":
                            snapshot.current_phase = phase_dir.name
                    except Exception as e:
                        snapshot.warnings.append(f"Failed to read {state_file}: {e}")

    obs_dir = project_dir / "observability"
    timeline_file = obs_dir / "timeline.jsonl"
    if timeline_file.exists():
        snapshot.source_files.append(str(timeline_file))
        total_cost = 0.0
        try:
            with open(timeline_file, "r") as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        event = json.loads(line)
                        if event.get("event_type") == "cost_estimated":
                            total_cost += float(event.get("cost_usd", 0.0))
                    except Exception:
                        pass
            snapshot.cost_summary = total_cost
        except Exception as e:
            snapshot.warnings.append(f"Failed to read timeline: {e}")

    # Mocking reading from missing directories for other fields
    approvals_dir = project_dir / "approvals"
    if approvals_dir.exists():
        snapshot.source_files.append(str(approvals_dir))

    return snapshot
