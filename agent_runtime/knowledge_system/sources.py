"""Automatic source discovery for system and project knowledge spaces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from agent_runtime.policies import assert_path_allowed

from .models import AuthorityLevel, KnowledgeRecord, Modality, SourceRef


TEXT_SUFFIXES = {".md", ".txt", ".rst"}
CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".sh", ".zsh", ".sql",
}
STRUCTURED_SUFFIXES = {".yml", ".yaml", ".json", ".jsonl", ".toml", ".ini", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | CODE_SUFFIXES | STRUCTURED_SUFFIXES | IMAGE_SUFFIXES | AUDIO_SUFFIXES | VIDEO_SUFFIXES
EXCLUDED_PARTS = {
    ".git", ".agentlab_runtime", ".venv", "venv", "__pycache__", "node_modules",
    "archive", "candidates", "candidate", "runs", "acceptance_runs",
}


class SourceCollector:
    def __init__(self, agentlab_root: Path, *, max_file_bytes: int = 1_000_000) -> None:
        self.root = Path(agentlab_root).resolve()
        self.max_file_bytes = max_file_bytes

    def collect_system(self) -> list[KnowledgeRecord]:
        candidates: set[Path] = set()
        for name in ("AGENTS.md", "OPERATING_MODEL.md", "DRIVER_PROTOCOL.md", "README.md"):
            path = self.root / name
            if path.is_file():
                candidates.add(path)
        for relative in ("agent_runtime", "config", "docs", "skills/active"):
            directory = self.root / relative
            if directory.is_dir():
                candidates.update(self._walk(directory))
        return [
            record
            for path in sorted(candidates)
            if (record := self._record_for_file(
                path,
                namespace="system.agentlab",
                project_id=None,
                authority=AuthorityLevel.CANONICAL,
                object_kind="agentlab_source",
            )) is not None
        ]

    def collect_project(self, project: str, *, domain: str) -> list[KnowledgeRecord]:
        project_root = assert_path_allowed(self.root / "projects" / project, self.root)
        if not project_root.is_dir():
            return []
        sources: list[tuple[Path, AuthorityLevel, str]] = []
        artifact_index = project_root / "project_artifact_index.yml"
        if artifact_index.is_file():
            sources.append((artifact_index, AuthorityLevel.CANONICAL, "artifact_index"))
        for relative, authority, kind in (
            ("project_brain", AuthorityLevel.CANONICAL, "project_fact"),
            ("production", AuthorityLevel.ACCEPTED, "production_artifact"),
            ("agent_docs", AuthorityLevel.ACCEPTED, "operator_memory"),
        ):
            directory = project_root / relative
            if directory.is_dir():
                sources.extend((path, authority, kind) for path in self._walk(directory))
        records = []
        for path, authority, kind in sorted(sources, key=lambda item: str(item[0])):
            object_kind = domain if domain in {"longform_narrative", "research"} else kind
            record = self._record_for_file(
                path,
                namespace=f"project.{project}",
                project_id=project,
                authority=authority,
                object_kind=object_kind,
            )
            if record is not None:
                records.append(record)
        return records

    def collect_paths(
        self,
        paths: Iterable[str | Path],
        *,
        namespace: str,
        project_id: str | None,
        authority: AuthorityLevel,
        object_kind: str,
    ) -> list[KnowledgeRecord]:
        records = []
        for raw in paths:
            path = assert_path_allowed(raw, self.root)
            if not path.is_file():
                continue
            record = self._record_for_file(
                path,
                namespace=namespace,
                project_id=project_id,
                authority=authority,
                object_kind=object_kind,
            )
            if record is not None:
                records.append(record)
        return records

    def _walk(self, directory: Path) -> Iterable[Path]:
        for path in directory.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative_parts = path.relative_to(self.root).parts
            if any(part in EXCLUDED_PARTS for part in relative_parts):
                continue
            if path.suffix.lower() in SUPPORTED_SUFFIXES:
                yield path

    def _record_for_file(
        self,
        path: Path,
        *,
        namespace: str,
        project_id: str | None,
        authority: AuthorityLevel,
        object_kind: str,
    ) -> KnowledgeRecord | None:
        path = assert_path_allowed(path, self.root)
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size > self.max_file_bytes or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        source_hash = hashlib.sha256(raw).hexdigest()
        modality = _modality_for(path)
        metadata = {"suffix": path.suffix.lower(), "size_bytes": size, "raw_payload_indexed": False}
        if modality in {Modality.IMAGE, Modality.AUDIO, Modality.VIDEO}:
            content = json.dumps(
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "modality": modality.value,
                    "size_bytes": size,
                    "content_hash": source_hash,
                },
                sort_keys=True,
            )
            object_kind = "media_asset"
        else:
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
            metadata["raw_payload_indexed"] = True
        source = SourceRef(path.relative_to(self.root).as_posix(), source_hash)
        return KnowledgeRecord.create(
            namespace=namespace,
            project_id=project_id,
            source=source,
            content=content,
            authority=authority,
            modality=modality,
            object_kind=object_kind,
            metadata=metadata,
        )


def _modality_for(path: Path) -> Modality:
    suffix = path.suffix.lower()
    if suffix in CODE_SUFFIXES:
        return Modality.CODE
    if suffix in STRUCTURED_SUFFIXES:
        return Modality.STRUCTURED
    if suffix in IMAGE_SUFFIXES:
        return Modality.IMAGE
    if suffix in AUDIO_SUFFIXES:
        return Modality.AUDIO
    if suffix in VIDEO_SUFFIXES:
        return Modality.VIDEO
    return Modality.TEXT
