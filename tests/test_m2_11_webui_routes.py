import pytest
import json
from agentlab_app.dashboard.routes import dispatch_request

def test_webui_dashboard_route_exists():
    """Test that the main dashboard route is wired correctly and returns 200."""
    resp = dispatch_request("/dashboard")
    assert resp["status"] == 200
    data = json.loads(resp["body"])
    assert data["page"] == "dashboard"

def test_webui_project_detail_and_drilldowns():
    """Test the detailed views for project routing."""
    resp = dispatch_request("/project/proj123")
    assert resp["status"] == 200
    assert json.loads(resp["body"])["project_id"] == "proj123"

    for sub in ["timeline", "costs", "phases", "artifacts", "routes"]:
        resp = dispatch_request(f"/project/proj123/{sub}")
        assert resp["status"] == 200
        assert json.loads(resp["body"])["page"] == f"project_{sub}"

def test_webui_handles_missing_routes():
    """Test that missing routes return a clean 404 response."""
    resp = dispatch_request("/invalid_route_that_should_never_exist")
    assert resp["status"] == 404
