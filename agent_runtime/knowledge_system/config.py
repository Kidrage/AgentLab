"""Knowledge-system policy loading with conservative defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from agent_runtime.policies import assert_path_allowed


VALID_MODES = {"off", "shadow", "assist", "enforce"}
VALID_CHANNELS = {"keyword", "semantic", "graph"}
VALID_KEYWORD_BACKENDS = {"auto", "bm25"}


@dataclass(frozen=True)
class KnowledgeSystemConfig:
    mode: str = "off"
    auto_memory: str = "propose_only"
    runtime_path: str = ".agentlab_runtime/knowledge"
    keyword_backend: str = "auto"
    top_k: int = 8
    required_channels: tuple[str, ...] = ("keyword",)
    max_file_bytes: int = 1_000_000
    index_system_sources: bool = True
    index_project_sources: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "KnowledgeSystemConfig":
        raw = dict(value or {})
        retrieval = raw.get("retrieval") if isinstance(raw.get("retrieval"), dict) else {}
        indexing = raw.get("indexing") if isinstance(raw.get("indexing"), dict) else {}
        storage = raw.get("storage") if isinstance(raw.get("storage"), dict) else {}
        mode = str(raw.get("mode") or "off")
        auto_memory = str(raw.get("auto_memory") or "propose_only")
        channels = tuple(dict.fromkeys(str(item) for item in retrieval.get("required_channels") or ["keyword"]))
        if mode not in VALID_MODES:
            raise ValueError(f"knowledge system mode must be one of {sorted(VALID_MODES)}")
        if auto_memory != "propose_only":
            raise ValueError("automatic knowledge updates must remain propose_only")
        unknown_channels = sorted(set(channels) - VALID_CHANNELS)
        if unknown_channels:
            raise ValueError(f"unknown knowledge retrieval channels: {', '.join(unknown_channels)}")
        runtime_path = str(storage.get("runtime_path") or ".agentlab_runtime/knowledge")
        if Path(runtime_path).is_absolute() or ".." in Path(runtime_path).parts:
            raise ValueError("knowledge storage.runtime_path must stay inside AgentLab root")
        keyword_backend = str(storage.get("keyword_backend") or "auto")
        if keyword_backend not in VALID_KEYWORD_BACKENDS:
            raise ValueError(
                f"knowledge keyword backend must be one of {sorted(VALID_KEYWORD_BACKENDS)}"
            )
        return cls(
            mode=mode,
            auto_memory=auto_memory,
            runtime_path=runtime_path,
            keyword_backend=keyword_backend,
            top_k=max(1, min(50, int(retrieval.get("top_k") or 8))),
            required_channels=channels,
            max_file_bytes=max(1024, int(indexing.get("max_file_bytes") or 1_000_000)),
            index_system_sources=bool(indexing.get("system_sources", True)),
            index_project_sources=bool(indexing.get("project_sources", True)),
        )


def load_knowledge_config(agentlab_root: Path) -> KnowledgeSystemConfig:
    root = Path(agentlab_root).resolve()
    path = assert_path_allowed(root / "config" / "knowledge_system.yml", root)
    if not path.exists():
        return KnowledgeSystemConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config/knowledge_system.yml must contain a mapping")
    return KnowledgeSystemConfig.from_mapping(raw)
