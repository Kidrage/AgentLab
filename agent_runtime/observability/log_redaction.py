from __future__ import annotations

import re
from typing import Any, Dict, List, Union

def redact_secrets(data: Union[Dict[str, Any], List[Any], str, Any]) -> Union[Dict[str, Any], List[Any], str, Any]:
    """
    Redact sensitive information like API keys, secrets, and private absolute paths
    from logs and events before they are written to disk.
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(x in k_lower for x in ["api_key", "apikey", "secret", "token"]):
                result[k] = "[REDACTED]"
            else:
                result[k] = redact_secrets(v)
        return result
    elif isinstance(data, list):
        return [redact_secrets(item) for item in data]
    elif isinstance(data, str):
        # Redact API keys and secrets
        redacted = re.sub(r'(api[_-]?key[\s=:]+)(["\']?)[a-zA-Z0-9_\-]+(\2)', r'\1\2[REDACTED]\3', data, flags=re.IGNORECASE)
        redacted = re.sub(r'(secret[\s=:]+)(["\']?)[a-zA-Z0-9_\-]+(\2)', r'\1\2[REDACTED]\3', redacted, flags=re.IGNORECASE)
        redacted = re.sub(r'(bearer\s+)[a-zA-Z0-9_\-\.]+', r'\1[REDACTED]', redacted, flags=re.IGNORECASE)
        
        # Redact private paths
        redacted = re.sub(r'/Users/[a-zA-Z0-9_-]+/', r'/Users/[USER]/', redacted)
        redacted = re.sub(r'/home/[a-zA-Z0-9_-]+/', r'/home/[USER]/', redacted)
        
        return redacted
    else:
        return data
