"""Health probe to determine if a worker is functional and ready for execution."""

from agent_runtime.workers.command_probe import probe_command
from agent_runtime.workers.auth_probe import probe_auth

def probe_health(worker_id: str, command: str) -> str:
    """Determine the health state of a worker: 'healthy', 'unhealthy', or 'unknown'."""
    if not probe_command(command):
        return "unhealthy"
        
    auth_status = probe_auth(worker_id)
    if auth_status == "no":
        return "unhealthy"
        
    return "healthy"
