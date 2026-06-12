"""Inventory helpers for external skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atomic_io import atomic_write_json, safe_read_json


def load_external_skill_inventory(path: Path) -> dict[str, Any]:
    data = safe_read_json(path, default={}) or {}
    return data if isinstance(data, dict) else {}


def write_external_skill_inventory(path: Path, inventory: dict[str, Any]) -> Path:
    atomic_write_json(path, inventory)
    return path
