import pytest
import json
from agentlab_app.dashboard.api import json_response, _redact_secrets

def test_secret_redaction():
    secret_data = {
        "name": "project1",
        "openai_api_key": "sk-1234567890",
        "AWS_SECRET_ACCESS_KEY": "secret-value",
        "nested": {
            "password": "my-password"
        }
    }
    
    redacted = _redact_secrets(secret_data)
    assert redacted["name"] == "project1"
    assert redacted["openai_api_key"] == "[REDACTED]"
    assert redacted["AWS_SECRET_ACCESS_KEY"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"

def test_json_response_redacts_secrets():
    secret_data = {"token": "123"}
    resp = json_response(secret_data)
    body = json.loads(resp["body"])
    assert body["token"] == "[REDACTED]"
