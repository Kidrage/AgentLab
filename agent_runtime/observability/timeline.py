from __future__ import annotations
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agent_runtime.observability.event import Event, VALID_EVENT_TYPES
from agent_runtime.observability.event_log import EventLogger
from agent_runtime.observability.log_redaction import redact_secrets

class Timeline:
    """Manages the append-only timeline of a project."""
    def __init__(self, project_id: str, project_dir: str):
        self.project_id = project_id
        self.project_dir = project_dir
        self.observability_dir = os.path.join(project_dir, "observability")
        os.makedirs(self.observability_dir, exist_ok=True)
        self.logger = EventLogger(project_dir)
        
    def add_event(
        self, 
        event_type: str, 
        details: Dict[str, Any],
        source: str = "system",
        user_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        task_id: Optional[str] = None,
        role_id: Optional[str] = None,
        cost_usd: Optional[float] = None
    ) -> Event:
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            project_id=self.project_id,
            details=details,
            source=source,
            user_id=user_id,
            worker_id=worker_id,
            task_id=task_id,
            role_id=role_id,
            cost_usd=cost_usd
        )
        
        # Write to underlying granular logs
        self.logger.log_event(event)
        
        # Write to timeline.jsonl
        timeline_path = os.path.join(self.observability_dir, "timeline.jsonl")
        safe_dict = redact_secrets(event.to_dict())
        with open(timeline_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(safe_dict) + "\n")
            
        return event
