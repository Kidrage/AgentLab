"""Deterministic content digests for governed files and directory artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def artifact_sha256(path: Path) -> str:
    """Hash one file or a directory's sorted relative file/hash manifest."""
    target = Path(path)
    if target.is_symlink():
        raise ValueError(f"artifact path may not be a symlink: {target}")
    if target.is_file():
        return hashlib.sha256(target.read_bytes()).hexdigest()
    if not target.is_dir():
        raise ValueError(f"artifact path is missing or unsupported: {target}")
    entries: list[dict[str, str]] = []
    for child in sorted(target.rglob("*")):
        if child.is_symlink():
            raise ValueError(f"artifact directory contains a symlink: {child}")
        if child.is_file():
            entries.append(
                {
                    "path": child.relative_to(target).as_posix(),
                    "sha256": hashlib.sha256(child.read_bytes()).hexdigest(),
                }
            )
    payload = json.dumps(
        entries,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
