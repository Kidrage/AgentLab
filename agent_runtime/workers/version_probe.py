"""Version probe to retrieve the version of an installed CLI command."""

import subprocess
import re
from typing import Optional

def probe_version(command: str) -> Optional[str]:
    """Safely probe the version of a command by running it with --version or equivalent."""
    if not command:
        return None
    
    # Custom version args
    args = [command, "--version"]
    if command == "git":
        args = ["git", "version"]
    elif command in ("npm", "pnpm", "uv"):
        args = [command, "--version"]
        
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=1.5)
        # Some commands might output version to stderr or return non-zero but still succeed in outputting version
        out = (res.stdout or "").strip() or (res.stderr or "").strip()
        if out:
            # Look for semantic version pattern e.g. 1.2.3 or v1.2
            match = re.search(r'v?(\d+\.\d+(?:\.\d+)?(?:\-[a-zA-Z0-9\.]+)?(?:\+\S+)?)', out)
            if match:
                return match.group(1)
            return out.splitlines()[0][:40]
    except Exception:
        pass
    return None
