"""Role-aware worker fallback policy."""

from __future__ import annotations

from pathlib import Path

import yaml


class WorkerFallbackPolicy:
    def __init__(self, config_path: Path) -> None:
        self.data: dict = {}
        if config_path.exists():
            self.data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    def candidates(self, role: str) -> list[str]:
        roles = self.data.get("roles", {})
        key = role.lower().replace("_", "").replace("-", "")
        for configured_role, workers in roles.items():
            normalized = configured_role.lower().replace("_", "").replace("-", "")
            if normalized == key:
                return list(workers or [])
        return list(self.data.get("default", []) or [])

    def fallbacks(self, role: str, selected_worker: str | None) -> list[str]:
        return [worker for worker in self.candidates(role) if worker != selected_worker]
