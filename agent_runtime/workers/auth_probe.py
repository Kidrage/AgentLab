"""Auth probe to safely detect if required API keys are configured."""

import json
import os
from pathlib import Path

def probe_auth(worker_id: str) -> str:
    """Safe authentication probe that never leaks keys."""
    # Deterministic local tools do not require authentication
    deterministic_tools = {
        "rg", "git", "ast-grep", "sg", "pytest", "ruff", "eslint",
        "mypy", "npm", "pnpm", "uv", "docker"
    }
    
    clean_id = worker_id.lower().replace("_", "-").replace("code", "").strip("-")
    
    if clean_id in deterministic_tools:
        return "yes"

    if clean_id == "agy":
        oauth_session_markers = [
            os.path.expanduser("~/Library/Application Support/Antigravity"),
            os.path.expanduser("~/.agy"),
        ]
        if any(os.path.exists(path) for path in oauth_session_markers):
            return "yes"
        return "unknown"

    if clean_id == "hermes":
        oauth_session_markers = [
            os.path.expanduser("~/.hermes"),
            os.path.join(os.getcwd(), ".hermes"),
        ]
        if any(os.path.exists(path) for path in oauth_session_markers):
            return "yes"
        
    # Map worker category to environment variables
    env_keys = {
        "claude": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        "codex": ["OPENAI_API_KEY", "CODEX_API_KEY"],
        "aider": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "hermes": ["DEEPSEEK_API_KEY", "HERMES_API_KEY", "QWEN_API_KEY"],
        "openclaw": ["OPENCLAW_API_KEY"],
        "bl": ["DASHSCOPE_API_KEY"],
        "bailian": ["DASHSCOPE_API_KEY"],
        "qwen": ["QWEN_API_KEY", "DASHSCOPE_API_KEY"],
        "gemini": ["GEMINI_API_KEY"],
    }
    
    keys = env_keys.get(clean_id)
    if not keys:
        # Fallback: check if the clean_id itself matches any common keys
        for key, vars in env_keys.items():
            if key in clean_id:
                keys = vars
                break
                
    if not keys:
        return "unknown"
        
    if clean_id == "claude":
        # Inspect only the two governed DeepSeek binding fields.  Values are
        # never returned or logged by this boolean probe.
        settings_path = Path.home() / ".claude" / "settings.json"
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
        private_env = settings.get("env") if isinstance(settings, dict) else {}
        if (
            isinstance(private_env, dict)
            and bool(str(private_env.get("ANTHROPIC_AUTH_TOKEN") or "").strip())
            and str(private_env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
            == "https://api.deepseek.com/anthropic"
        ):
            return "yes"
        # Governed Claude routes are bound only to the exact private
        # DeepSeek endpoint above.  Generic CCS markers and ambient API keys
        # cannot establish that provider/auth binding.
        return "no"
        
    for k in keys:
        if os.environ.get(k):
            return "yes"
            
    return "no"
