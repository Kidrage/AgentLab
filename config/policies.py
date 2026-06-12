def assert_path_allowed(path: str) -> bool:
    """Verify that a path is allowed in the current context."""
    # Allow only paths within the current working directory
    from pathlib import Path
    cwd = Path.cwd()
    try:
        Path(path).relative_to(cwd)
        return True
    except ValueError:
        return False

def assert_file_allowed(file_path: str) -> bool:
    """Verify that a file path is allowed in the current context."""
    from pathlib import Path
    path = Path(file_path)
    
    # Allow only files within the project directory
    project_dir = Path(__file__).parent.parent.parent
    try:
        path.relative_to(project_dir)
        return True
    except ValueError:
        return False

def get_allowed_paths():
    """Get list of allowed paths for the current context."""
    from pathlib import Path
    return {
        "cwd": str(Path.cwd()),
        "project_dir": str(Path(__file__).parent.parent.parent),
        "allowed_patterns": [
            "projects/AgentLab/**",
            "config/**",
            "agent_runtime/**",
            "docs/**",
            "tests/**"
        ]
    }