import pytest
from agent_runtime.observability.timeline import Timeline
from agent_runtime.observability.query import query_timeline, tail_event_log

def test_timeline_and_query(tmp_path):
    timeline = Timeline("p1", str(tmp_path))
    timeline.add_event("role_assigned", {"role": "coder"}, worker_id="w1")
    timeline.add_event("artifact_created", {"file": "main.py"})
    
    events = query_timeline(str(tmp_path))
    assert len(events) == 2
    assert events[0].event_type == "role_assigned"
    
    events_filtered = query_timeline(str(tmp_path), event_type="artifact_created")
    assert len(events_filtered) == 1
    assert events_filtered[0].event_type == "artifact_created"
    
    raw_logs = tail_event_log(str(tmp_path))
    assert len(raw_logs) == 2
