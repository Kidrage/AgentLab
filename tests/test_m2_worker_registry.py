"""Tests for WorkerRegistry caching and loader operations."""

from pathlib import Path
import yaml
from agent_runtime.workers.registry import WorkerRegistry
from agent_runtime.workers.worker_card import WorkerCard

def test_registry_scan_and_cache(tmp_path):
    registry = WorkerRegistry(tmp_path)

    # Cache shouldn't exist initially
    assert registry.load_from_cache() is False

    # Run scan
    registry.scan_and_register()

    # Cache should be saved now
    cache_file = tmp_path / "worker_registry.yml"
    assert cache_file.is_file()

    # Verify content in cache file
    content = yaml.safe_load(cache_file.read_text(encoding="utf-8"))
    assert "workers" in content
    assert len(content["workers"]) > 0

    # Load from cache on a new registry instance
    new_registry = WorkerRegistry(tmp_path)
    assert new_registry.load_from_cache() is True
    assert len(new_registry.list_workers()) == len(registry.list_workers())

    # Check fetching worker
    w = new_registry.get_worker("git")
    assert w is not None
    assert w.worker_id == "git"
