import json

def json_response(data, status=200):
    """Format a response as a JSON string and dict suitable for HTTP handler."""
    redacted_data = _redact_secrets(data)
    body = json.dumps(redacted_data).encode("utf-8")
    return {"status": status, "headers": {"Content-Type": "application/json"}, "body": body}

def _redact_secrets(data):
    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            if "api_key" in k.lower() or "secret" in k.lower() or "password" in k.lower() or "token" in k.lower() or "authorization" in k.lower():
                new_data[k] = "[REDACTED]"
            else:
                new_data[k] = _redact_secrets(v)
        return new_data
    elif isinstance(data, list):
        return [_redact_secrets(i) for i in data]
    else:
        return data

def build_error(message, status=400):
    return json_response({"error": message}, status=status)
