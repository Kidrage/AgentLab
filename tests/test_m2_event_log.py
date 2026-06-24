import os
import pytest
from agent_runtime.observability.event import Event
from agent_runtime.observability.event_log import EventLogger

def test_event_logger(tmp_path):
    logger = EventLogger(str(tmp_path))
    event = Event(
        event_id="e1",
        event_type="cost_recorded",
        timestamp="2024-01-01T12:00:00Z",
        project_id="p1",
        details={"amount": 0.5},
        cost_usd=0.5
    )
    logger.log_event(event)
    
    # Check JSONL
    assert os.path.exists(os.path.join(tmp_path, "observability", "event_log.jsonl"))
    
    # Check YAML routing
    assert os.path.exists(os.path.join(tmp_path, "observability", "cost_events.yml"))
