import pytest
import json
from agentlab_app.dashboard.api import json_response, build_error

def test_json_response_headers():
    resp = json_response({"hello": "world"})
    assert resp["status"] == 200
    assert resp["headers"]["Content-Type"] == "application/json"
    assert b"hello" in resp["body"]

def test_build_error():
    resp = build_error("something went wrong", 400)
    assert resp["status"] == 400
    body = json.loads(resp["body"])
    assert body["error"] == "something went wrong"
