"""Command probe to detect if a local CLI command is installed."""

import shutil
from pathlib import Path

def probe_command(command: str) -> bool:
    """Check if the command is available in the system PATH."""
    if not command:
        return False
    return shutil.which(command) is not None
