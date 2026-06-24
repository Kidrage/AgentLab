import pytest
from agent_runtime.observability.log_redaction import redact_secrets

def test_redact_api_keys():
    data = {
        "OPENAI_API_KEY": "sk-1234567890abcdef",
        "nested": {
            "secret_token": "some-secret-string"
        },
        "normal_key": "value"
    }
    redacted = redact_secrets(data)
    assert redacted["OPENAI_API_KEY"] == "[REDACTED]"
    assert redacted["nested"]["secret_token"] == "[REDACTED]"
    assert redacted["normal_key"] == "value"
    
def test_redact_private_paths():
    path = "/home/admin/project/file.txt"
    redacted = redact_secrets(path)
    assert redacted == "/home/[USER]/project/file.txt"

    path2 = "/home/admin/workspace/config.json"
    redacted2 = redact_secrets(path2)
    assert redacted2 == "/home/[USER]/workspace/config.json"
