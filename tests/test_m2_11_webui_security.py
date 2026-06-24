import pytest
import json
from agentlab_app.dashboard.api import json_response, _redact_secrets

def test_webui_secret_redaction_system():
    """
    Test that the secret redaction engine correctly scrubs
    API keys, passwords, and tokens before they are rendered
    to the frontend JSON response.
    """
    secret_data = {
        "project_name": "Demo",
        "openai_api_key": "sk-1234567890",
        "AWS_SECRET_ACCESS_KEY": "secret-value",
        "nested_config": {
            "password": "my-password",
            "token": "ghp_12345"
        }
    }
    
    redacted = _redact_secrets(secret_data)
    
    # Safe fields must be untouched
    assert redacted["project_name"] == "Demo"
    
    # Dangerous fields must be redacted
    assert redacted["openai_api_key"] == "[REDACTED]"
    assert redacted["AWS_SECRET_ACCESS_KEY"] == "[REDACTED]"
    assert redacted["nested_config"]["password"] == "[REDACTED]"
    assert redacted["nested_config"]["token"] == "[REDACTED]"

def test_webui_json_response_applies_redaction():
    """Test that the json_response wrapper applies redaction by default."""
    secret_data = {"auth_token": "secret_123"}
    resp = json_response(secret_data)
    body = json.loads(resp["body"])
    assert body["auth_token"] == "[REDACTED]"
