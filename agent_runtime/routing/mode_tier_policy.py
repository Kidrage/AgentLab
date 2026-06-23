"""Mode/tier constraints and ranking preferences for worker routing."""

from __future__ import annotations

from pathlib import Path

import yaml


_COST_RANK = {"free": 0, "low": 1, "medium": 2, "high": 3, "unknown": 4}


class ModeTierWorkerPolicy:
    def __init__(self, config_path: Path) -> None:
        self.data: dict = {}
        if config_path.exists():
            self.data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    def _mode(self, mode: str) -> dict:
        return self.data.get("modes", {}).get(mode, {}) or {}

    def _tier(self, tier: str) -> dict:
        return self.data.get("tiers", {}).get(tier, {}) or {}

    def permits(self, worker_id: str, cost_tier: str, mode: str, tier: str) -> tuple[bool, str]:
        mode_cfg = self._mode(mode)
        if worker_id in mode_cfg.get("forbidden_workers", []):
            return False, f"worker forbidden by mode {mode}"
        ceiling = self._tier(tier).get("cost_ceiling", "high")
        if _COST_RANK.get(cost_tier, 4) > _COST_RANK.get(ceiling, 3):
            return False, f"cost tier {cost_tier} exceeds {tier} ceiling {ceiling}"
        return True, "permitted"

    def preference(self, role: str, mode: str, tier: str) -> list[str]:
        mode_cfg = self._mode(mode)
        role_key = role.lower().replace("_", "").replace("-", "")
        for configured_role, workers in mode_cfg.get("role_preferences", {}).items():
            normalized = configured_role.lower().replace("_", "").replace("-", "")
            if normalized == role_key:
                return list(workers or [])
        return list(self._tier(tier).get("preferred_workers", []) or [])

    def rank(self, workers: list[str], role: str, mode: str, tier: str) -> list[str]:
        preferred = self.preference(role, mode, tier)
        order = {worker: idx for idx, worker in enumerate(preferred)}
        return sorted(workers, key=lambda worker: (order.get(worker, len(order)), workers.index(worker)))
