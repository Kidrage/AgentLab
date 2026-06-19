from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_yaml


def append_executor_event(path: Path, event: dict) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"entries": []}
    data = data or {"entries": []}
    entry = dict(event)
    entry.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    data.setdefault("entries", []).append(entry)
    atomic_write_yaml(path, data)
    return data
