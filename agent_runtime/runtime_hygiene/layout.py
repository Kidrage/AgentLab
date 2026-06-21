"""Runtime layout scanner for AgentLab hygiene."""

from pathlib import Path
from typing import Any, Optional
import subprocess

class LayoutReport:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        return self.data

def is_git_tracked(path: Path, root: Path) -> bool:
    """Check if a path is tracked by git."""
    if not path.exists():
        return False
    try:
        res = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path.relative_to(root))],
            capture_output=True, text=True, cwd=str(root)
        )
        return res.returncode == 0
    except Exception:
        return False

def scan_layout(agentlab_root: Path) -> LayoutReport:
    """Scan the runtime hygiene layout of the repository."""
    agents_dir = agentlab_root / ".agents"
    profiles_dir = agents_dir / "profiles"
    workspaces_dir = agents_dir / "workspaces"
    bridges_dir = agents_dir / "bridges"
    logs_dir = agents_dir / "logs"
    runtime_dir = agents_dir / "runtime"

    # Ensure directories exist
    for d in [profiles_dir, workspaces_dir, bridges_dir, logs_dir, runtime_dir]:
        d.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    # Profile entries to check
    profile_names = ["claude", "codex", "qwen", "hermes", "gemini", "bailian", "openclaw"]
    profile_entries = []
    for name in profile_names:
        p = profiles_dir / name
        exists = p.exists()
        is_sym = p.is_symlink()
        target = str(p.readlink()) if is_sym else None
        tracked = is_git_tracked(p, agentlab_root)
        
        risk_flags = []
        if tracked:
            risk_flags.append("git_tracked")
            warnings.append(f"Profile directory {p} is tracked by Git")
        if is_sym and target and not Path(target).exists():
            risk_flags.append("broken_symlink")
            warnings.append(f"Profile symlink {p} points to nonexistent target: {target}")

        profile_entries.append({
            "name": name,
            "path": str(p.relative_to(agentlab_root)),
            "exists": exists,
            "symlink": is_sym,
            "target": target,
            "git_tracked": tracked,
            "risk_flags": risk_flags
        })

    # Workspace entries to check
    workspace_names = ["claude", "codex", "qwen", "hermes", "openclaw", "generic_cli"]
    workspace_entries = []
    for name in workspace_names:
        p = workspaces_dir / name
        exists = p.exists()
        is_sym = p.is_symlink()
        target = str(p.readlink()) if is_sym else None
        tracked = is_git_tracked(p, agentlab_root)
        cleanable = True # Workspaces can be cleaned up
        
        risk_flags = []
        if tracked:
            risk_flags.append("git_tracked")
            warnings.append(f"Workspace directory {p} is tracked by Git")
        if is_sym and target and not Path(target).exists():
            risk_flags.append("broken_symlink")
            warnings.append(f"Workspace symlink {p} points to nonexistent target: {target}")

        workspace_entries.append({
            "name": name,
            "path": str(p.relative_to(agentlab_root)),
            "exists": exists,
            "symlink": is_sym,
            "target": target,
            "git_tracked": tracked,
            "cleanable": cleanable,
            "risk_flags": risk_flags
        })

    data = {
        "agentlab_root": str(agentlab_root),
        "profiles_dir": str(profiles_dir.relative_to(agentlab_root)),
        "workspaces_dir": str(workspaces_dir.relative_to(agentlab_root)),
        "bridges_dir": str(bridges_dir.relative_to(agentlab_root)),
        "logs_dir": str(logs_dir.relative_to(agentlab_root)),
        "runtime_dir": str(runtime_dir.relative_to(agentlab_root)),
        "profile_entries": profile_entries,
        "workspace_entries": workspace_entries,
        "warnings": warnings
    }

    return LayoutReport(data)
