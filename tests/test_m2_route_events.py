import os
import yaml
import pytest
from agent_runtime.observability.timeline import Timeline

def test_route_events_yaml(tmp_path):
    timeline = Timeline("p1", str(tmp_path))
    timeline.add_event("route_decision_created", {"target": "coder_agent"})
    
    route_file = os.path.join(tmp_path, "observability", "route_events.yml")
    assert os.path.exists(route_file)
    with open(route_file, "r") as f:
        data = list(yaml.safe_load_all(f))
        assert len(data) == 1
        assert data[0]["event_type"] == "route_decision_created"
