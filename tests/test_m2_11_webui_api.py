import pytest
import json
from agentlab_app.dashboard.api import json_response, build_error

def test_webui_json_response_headers():
    """
    Test that normal JSON responses attach the correct HTTP
    status codes and Content-Type headers for browser compatibility.
    """
    resp = json_response({"message": "success"})
    assert resp["status"] == 200
    assert resp["headers"]["Content-Type"] == "application/json"
    assert b"success" in resp["body"]

def test_webui_build_error_formatter():
    """
    Test that the error formatter constructs a standard error
    JSON envelope with the provided status code.
    """
    resp = build_error("Unauthorized access", 401)
    assert resp["status"] == 401
    
    body = json.loads(resp["body"])
    assert "error" in body
    assert body["error"] == "Unauthorized access"
