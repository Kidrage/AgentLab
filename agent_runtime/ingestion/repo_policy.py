"""Repo ingestion policy loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_REPO_INGESTION_POLICY: dict[str, Any] = {
    "default_mode": "api_first",
    "allow_full_clone": False,
    "require_approval_for_clone": True,
    "require_approval_for_build": True,
    "limits": {
        "max_api_tree_entries": 100000,
        "max_single_file_kb": 256,
        "max_files_read": 100,
        "max_total_text_mb": 5,
        "max_sparse_checkout_mb": 100,
        "max_workspace_mb": 200,
    },
    "default_excludes": [
        ".git/**",
        "build/**",
        "dist/**",
        "DerivedData/**",
        "node_modules/**",
        "third_party/**",
        "vendor/**",
        "*.onnx",
        "*.pt",
        "*.pth",
        "*.ckpt",
        "*.wav",
        "*.flac",
        "*.aiff",
        "*.mp4",
        "*.zip",
        "*.tar",
        "*.dmg",
        "*.framework",
        "*.xcframework",
    ],
    "modes": {
        "repo_profile": {"max_level": "targeted_fetch", "clone_allowed": False},
        "repo_patch": {"max_level": "sparse_clone", "full_clone_allowed": False},
        "repo_build_test": {"max_level": "full_clone", "approval_required": True},
    },
}


def load_repo_ingestion_policy(agentlab_root: Path | None = None) -> dict[str, Any]:
    if agentlab_root is None:
        return dict(DEFAULT_REPO_INGESTION_POLICY)
    path = agentlab_root / "config" / "repo_ingestion_policy.yml"
    if not path.exists():
        return dict(DEFAULT_REPO_INGESTION_POLICY)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        loaded = {}
    policy = dict(DEFAULT_REPO_INGESTION_POLICY)
    policy.update(loaded.get("repo_ingestion", loaded) or {})
    limits = dict(DEFAULT_REPO_INGESTION_POLICY["limits"])
    limits.update((loaded.get("repo_ingestion", loaded) or {}).get("limits", {}) or {})
    policy["limits"] = limits
    return policy
