import yaml
from agent_runtime.config_loader import load_agentlab_configs

def explain_worker(worker_id: str) -> str:
    from agent_runtime.workers.detector import DEFAULT_CANDIDATES
    
    worker_data = next((w for w in DEFAULT_CANDIDATES if w.get("worker_id") == worker_id), None)
    if not worker_data:
        return f"Worker '{worker_id}' not found in registry."
        
    name = worker_data.get("display_name", worker_id)
    cmd = worker_data.get("command", "none")
    installed = worker_data.get("installed", False)
    auth = worker_data.get("authenticated", "unknown")
    category = worker_data.get("category", "unknown")
    
    explanation = f"# Worker Diagnosis: {name} ({worker_id})\n\n"
    explanation += f"**Category**: {category}\n"
    explanation += f"**Command**: `{cmd}`\n"
    explanation += f"**Installed**: {'Yes' if installed else 'No'}\n"
    explanation += f"**Authenticated**: {auth}\n\n"
    
    if not installed:
        explanation += "## Issue: Not Installed\n"
        explanation += f"The CLI tool required for this worker (`{cmd}`) is not available in the PATH. "
        explanation += "Please install it to use this worker.\n"
    elif auth != "yes":
        explanation += "## Issue: Not Authenticated\n"
        explanation += "The worker is installed but appears unauthenticated or misconfigured. "
        explanation += "Check API keys or run the provider's login command.\n"
    else:
        explanation += "Worker appears fully healthy and available for routing.\n"
        
    return explanation
