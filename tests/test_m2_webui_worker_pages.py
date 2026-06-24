import pytest
import json
from agentlab_app.dashboard.routes import dispatch_request

def test_workers_route():
    resp = dispatch_request("/workers")
    assert resp["status"] == 200
    body = json.loads(resp["body"])
    assert body["page"] == "workers"
    assert "workers" in body

def test_worker_detail_route():
    resp = dispatch_request("/workers/claude_code")
    assert resp["status"] == 200
    body = json.loads(resp["body"])
    assert body["page"] == "worker_detail"
    assert body["worker_id"] == "claude_code"
