"""Symlink auditor for runtime hygiene."""

from pathlib import Path
from typing import Any

class SymlinkAudit:
    def __init__(self, symlinks: list[dict[str, Any]], warnings: list[str]):
        self.symlinks = symlinks
        self.warnings = warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "symlinks": self.symlinks,
            "warnings": self.warnings
        }

def audit_symlinks(agentlab_root: Path) -> SymlinkAudit:
    """Audit all symlinks under agentlab_root (skipping ignored directories)."""
    symlinks: list[dict[str, Any]] = []
    warnings: list[str] = []

    ignored_names = {
        ".git", ".venv", "venv", "node_modules", "__pycache__",
        "projects", "acceptance_runs", "web_ui", "tests", "workspaces"
    }

    def scan(dir_path: Path):
        try:
            for item in dir_path.iterdir():
                if item.name in ignored_names:
                    continue
                if item.is_symlink():
                    # Audit this symlink
                    target_str = item.readlink()
                    target_path = Path(target_str)
                    
                    # Resolve it
                    try:
                        resolved = item.resolve()
                        exists = resolved.exists()
                    except Exception:
                        resolved = item.parent / target_path
                        exists = False

                    outside = False
                    try:
                        resolved_abs = resolved.resolve()
                        root_abs = agentlab_root.resolve()
                        # check if resolved_abs is under root_abs
                        resolved_abs.relative_to(root_abs)
                    except ValueError:
                        outside = True

                    risk_flags = []
                    if not exists:
                        risk_flags.append("broken_symlink")
                        warnings.append(f"Symlink {item} is broken: target does not exist")
                    if outside:
                        risk_flags.append("pointing_outside_workspace")
                        warnings.append(f"Symlink {item} points outside workspace: {target_str}")
                    if target_path.is_absolute():
                        risk_flags.append("absolute_path_symlink")
                        warnings.append(f"Symlink {item} uses absolute path target: {target_str}")

                    symlinks.append({
                        "path": str(item.relative_to(agentlab_root)),
                        "target": str(target_str),
                        "resolved_target": str(resolved),
                        "is_valid": exists,
                        "outside_workspace": outside,
                        "absolute": target_path.is_absolute(),
                        "broken": not exists,
                        "risk_flags": risk_flags
                    })
                elif item.is_dir():
                    scan(item)
        except PermissionError:
            pass

    scan(agentlab_root)
    return SymlinkAudit(symlinks, warnings)
