"""Auth probe to safely detect if required API keys are configured."""

import os

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
        "agy": ["AGY_API_KEY", "GEMINI_API_KEY"]
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
        # Safe detection of CCS config files without reading or leaking content
        provider_dir = os.path.expanduser("~/.claude-provider")
        if os.path.isfile(os.path.join(provider_dir, "active")) or \
           os.path.isfile(os.path.join(provider_dir, "config")):
            return "yes"
        
    for k in keys:
        if os.environ.get(k):
            return "yes"
            
    return "no"
