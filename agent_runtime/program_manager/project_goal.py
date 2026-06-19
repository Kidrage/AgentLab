from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_mission_contract(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def normalize_capabilities(items: Any) -> list[str]:
    values: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            values.append(str(item.get("capability") or item.get("name") or "unknown"))
    return sorted({item for item in values if item and item != "unknown"})


def infer_task_type(contract: dict[str, Any]) -> str:
    return str(contract.get("task_type") or contract.get("domain") or "unknown")
