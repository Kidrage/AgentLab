from __future__ import annotations
import json
import os
import yaml
from typing import Dict, Any

from agent_runtime.observability.event import Event
from agent_runtime.observability.log_redaction import redact_secrets

class EventLogger:
    """Handles routing events to their respective log files."""
    def __init__(self, project_dir: str):
        self.observability_dir = os.path.join(project_dir, "observability")
        os.makedirs(self.observability_dir, exist_ok=True)
        
    def log_event(self, event: Event) -> None:
        """Log an event to the main event_log.jsonl and specific YAML files."""
        safe_dict = redact_secrets(event.to_dict())
        
        # Main JSONL log
        log_path = os.path.join(self.observability_dir, "event_log.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(safe_dict) + "\n")
            
        # Route to specific YAML logs
        self._route_to_yaml(event.event_type, safe_dict)

    def _route_to_yaml(self, event_type: str, safe_dict: Dict[str, Any]) -> None:
        category_map = {
            "cost_estimated": "cost_events.yml",
            "cost_recorded": "cost_events.yml",
            "worker_detected": "worker_events.yml",
            "worker_auditioned": "worker_events.yml",
            "role_assigned": "worker_events.yml",
            "route_decision_created": "route_events.yml",
            "approval_requested": "decision_events.yml",
            "approval_accepted": "decision_events.yml",
            "approval_rejected": "decision_events.yml",
            "executor_started": "executor_runs.yml",
            "executor_finished": "executor_runs.yml",
            "artifact_created": "artifact_events.yml",
        }
        
        target_file = category_map.get(event_type)
        if target_file:
            path = os.path.join(self.observability_dir, target_file)
            with open(path, "a", encoding="utf-8") as f:
                f.write("---\n")
                yaml.safe_dump(safe_dict, f, allow_unicode=True, sort_keys=False)
