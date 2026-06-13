"""Search provider policy and config helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_SEARCH_CONFIG: dict[str, Any] = {
    "search_providers": {
        "default_provider": "anysearch_optional",
        "anysearch": {
            "enabled": False,
            "mode": "api_or_mcp_adapter",
            "api_key_env": "ANYSEARCH_API_KEY",
            "endpoint": "https://api.anysearch.com",
            "allow_anonymous": True,
            "timeout_sec": 20,
            "max_results_default": 5,
            "max_batch_queries": 5,
            "max_url_extract_chars": 12000,
            "safety": {
                "require_approval_for_batch_over": 5,
                "block_localhost_urls": True,
                "block_private_ip_urls": True,
                "redact_api_key_in_logs": True,
            },
        },
        "fallback": {"enabled": True, "provider": "local_url_reader"},
    }
}


def load_search_config(root: Path | None = None) -> dict[str, Any]:
    root = root or Path.cwd()
    path = root / "config" / "search_providers.yml"
    if not path.exists():
        return DEFAULT_SEARCH_CONFIG.copy()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = DEFAULT_SEARCH_CONFIG.copy()
    merged["search_providers"] = {
        **DEFAULT_SEARCH_CONFIG["search_providers"],
        **(data.get("search_providers") or {}),
    }
    return merged


def search_artifact_dir(root: Path, project: str, task_id: str | None = None, output_dir: Path | None = None) -> Path:
    if output_dir is not None:
        return output_dir
    if task_id:
        return root / "projects" / project / "runs" / task_id / "artifacts" / "search"
    return root / "artifacts" / "search"

