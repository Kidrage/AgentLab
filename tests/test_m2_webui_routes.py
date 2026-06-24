import pytest
import json
from agentlab_app.dashboard.routes import dispatch_request

def test_dashboard_route():
    resp = dispatch_request("/dashboard")
    assert resp["status"] == 200
    data = json.loads(resp["body"])
    assert data["page"] == "dashboard"

def test_project_routes():
    resp = dispatch_request("/projects")
    assert resp["status"] == 200
    data = json.loads(resp["body"])
    assert "projects" in data

    resp = dispatch_request("/project/proj123")
    assert resp["status"] == 200
    assert json.loads(resp["body"])["project_id"] == "proj123"

    for sub in ["timeline", "costs", "phases", "artifacts", "routes"]:
        resp = dispatch_request(f"/project/proj123/{sub}")
        assert resp["status"] == 200
        assert json.loads(resp["body"])["page"] == f"project_{sub}"

def test_not_found():
    resp = dispatch_request("/does-not-exist")
    assert resp["status"] == 404
