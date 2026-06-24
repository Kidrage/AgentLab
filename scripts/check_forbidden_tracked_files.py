#!/usr/bin/env python3
"""Check that no forbidden files are tracked by Git.

Catches:
  .env, .env.*, **/.env, **/.env.*
  *.pem, *.key, *.p12, *.pfx
  agent_runtime/.env, agent_runtime/.env.*

Safe files that are allowed:
  .env.example, *.env.example, config/*.example
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATTERNS = [
    # Direct .env files
    ".env",
    ".env.*",
    # Nested .env files
    "**/.env",
    "**/.env.*",
    # Specific sensitive paths
    "agent_runtime/.env",
    "agent_runtime/.env.*",
    # Certificate / key files
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
]

# Files/patterns that are explicitly allowed
ALLOWED_PATTERNS = [
    ".env.example",
    "*.env.example",
    "**/*.env.example",
]

EXIT_OK = 0
EXIT_FORBIDDEN_FOUND = 1
EXIT_GIT_ERROR = 2


def _tracked_files() -> list[str]:
    """Return list of tracked files from git ls-files."""
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError as exc:
        print(f"error: git ls-files failed: {exc.stderr}")
        sys.exit(EXIT_GIT_ERROR)
    except FileNotFoundError:
        print("error: git not found")
        sys.exit(EXIT_GIT_ERROR)


def _match_any(relpath: str, patterns: list[str]) -> bool:
    """Check if relpath matches any glob pattern."""
    p = Path(relpath)
    for pattern in patterns:
        if p.match(pattern):
            return True
    return False


def main() -> int:
    tracked = _tracked_files()

    forbidden_found: list[str] = []

    for relpath in tracked:
        if _match_any(relpath, FORBIDDEN_PATTERNS):
            # Check if it's explicitly allowed
            if _match_any(relpath, ALLOWED_PATTERNS):
                continue
            forbidden_found.append(relpath)

    if forbidden_found:
        print(f"FAIL: {len(forbidden_found)} forbidden file(s) tracked by Git:")
        for f in forbidden_found:
            print(f"  - {f}")
        print("\nForbidden patterns:")
        for p in FORBIDDEN_PATTERNS:
            print(f"  {p}")
        print("\nAllowed patterns (exempted):")
        for p in ALLOWED_PATTERNS:
            print(f"  {p}")
        return EXIT_FORBIDDEN_FOUND

    print(f"PASS: No forbidden files tracked ({len(tracked)} total tracked files).")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
