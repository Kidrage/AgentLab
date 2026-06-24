from __future__ import annotations
import json
import os
from typing import List, Optional

from agent_runtime.observability.event import Event

def query_timeline(project_dir: str, event_type: Optional[str] = None, limit: int = 100) -> List[Event]:
    """Retrieve events from a project's timeline."""
    timeline_path = os.path.join(project_dir, "observability", "timeline.jsonl")
    if not os.path.exists(timeline_path):
        return []
        
    events = []
    with open(timeline_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if event_type and data.get("event_type") != event_type:
                continue
            events.append(Event.from_dict(data))
            
    return events[-limit:]

def tail_event_log(project_dir: str, limit: int = 50) -> List[dict]:
    """Retrieve raw entries from the event log."""
    log_path = os.path.join(project_dir, "observability", "event_log.jsonl")
    if not os.path.exists(log_path):
        return []
        
    events = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
            
    return events[-limit:]
