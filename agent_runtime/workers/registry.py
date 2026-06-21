"""Registry to load, cache, and query scanned local workers."""

import yaml
from pathlib import Path
from typing import Optional, Any, Dict
from agent_runtime.workers.worker_card import WorkerCard
from agent_runtime.workers.detector import scan_workers

class WorkerRegistry:
    def __init__(self, cache_dir: Path):
        self.cache_path = cache_dir / "worker_registry.yml"
        self.workers: dict[str, WorkerCard] = {}

    def load_from_cache(self) -> bool:
        """Load registered workers from the cache file. Returns True if successful."""
        if not self.cache_path.exists():
            return False
        try:
            content = self.cache_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if not data or "workers" not in data:
                return False
            for w_id, w_data in data["workers"].items():
                self.workers[w_id] = WorkerCard.from_dict(w_data)
            return True
        except Exception:
            return False

    def save_to_cache(self) -> None:
        """Save registered workers to the cache file."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "workers": {w_id: w.to_dict() for w_id, w in self.workers.items()}
        }
        try:
            content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
            self.cache_path.write_text(content, encoding="utf-8")
        except Exception:
            pass

    def scan_and_register(self) -> None:
        """Scan the system and register discovered workers, saving to cache."""
        scanned = scan_workers()
        for card in scanned:
            self.workers[card.worker_id] = card
        self.save_to_cache()

    def get_worker(self, worker_id: str) -> Optional[WorkerCard]:
        """Get a registered worker by ID."""
        return self.workers.get(worker_id)

    def list_workers(self) -> list[WorkerCard]:
        """List all registered workers."""
        return list(self.workers.values())
