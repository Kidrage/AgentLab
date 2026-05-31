"""Atomic file I/O for AgentLab critical state files.

Provides safe writes via temp-file + fsync + atomic rename, preventing
half-written states that would corrupt on power loss or crash.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text content atomically.

    Writes to a temp file in the same directory, fsync's it,
    then atomically renames over the target path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_yaml(path: Path, data: object, **yaml_kwargs) -> None:
    """Write YAML data atomically via safe_dump."""
    content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, **yaml_kwargs)
    atomic_write_text(path, content)