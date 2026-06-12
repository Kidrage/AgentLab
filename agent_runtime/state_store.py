from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from agent_runtime.atomic_io import atomic_read_yaml, atomic_write_yaml

def utc_now() -> str:
    """Return current UTC time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()

def load_state(run_dir: Path) -> dict:
    """Load task state from disk."""
    path = run_dir / "task_state.yml"
    if not path.exists():
        return {}
    return atomic_read_yaml(str(path)) or {}

def save_state(run_dir: Path, state: dict) -> None:
    """Save task state to disk."""
    path = run_dir / "task_state.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(str(path), state)

class TaskEvents:
    """Manage task event recording."""
    
    def __init__(self, task_id: str, run_dir: Optional[Path] = None):
        self.task_id = task_id
        if run_dir:
            self.run_dir = run_dir
        else:
            self.run_dir = Path(f"projects/AgentLab/runs/{task_id}")
    
    def record_event(self, event_data: dict) -> None:
        """Record a task event."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        events_path = self.run_dir / "task_events.jsonl"
        
        event = {"timestamp": utc_now(), **event_data}
        import json
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        
        existing = ""
        if events_path.exists():
            existing = events_path.read_text(encoding="utf-8")
        
        events_path.write_text(existing + line + "\n", encoding="utf-8")
    
    def get_task_events(self, task_id: str) -> list:
        """Get events for a task."""
        events_path = self.run_dir / "task_events.jsonl"
        if not events_path.exists():
            return []
        
        import json
        events = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

# Alias for backward compatibility
TaskState = dict