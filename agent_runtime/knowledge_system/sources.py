"""Automatic source discovery for system and project knowledge spaces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

import yaml

from agent_runtime.policies import assert_path_allowed

from .models import AuthorityLevel, KnowledgeLifecycle, KnowledgeRecord, Modality, SourceRef


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
HARD_EXCLUDED_PARTS = {
    ".git", ".agentlab_runtime", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".ruff_cache",
}

PROJECT_SOURCE_GROUPS = (
    (AuthorityLevel.CANONICAL, KnowledgeLifecycle.ACTIVE, "project_fact", (
        "project_brain", "memory_snapshot", "config", "tasks",
    )),
    (AuthorityLevel.ACCEPTED, KnowledgeLifecycle.ACTIVE, "production_artifact", (
        "production", "artifacts", "agent_docs", "docs", "prompt_templates", "skills",
    )),
    (AuthorityLevel.CANDIDATE, KnowledgeLifecycle.ACTIVE, "candidate_artifact", (
        "candidates", "candidate", "revisions",
    )),
    (AuthorityLevel.AUDIT, KnowledgeLifecycle.ACTIVE, "audit_evidence", (
        "acceptance", "evaluation_runs", "runs", "background_jobs", "observability", "cost",
    )),
    (AuthorityLevel.EXTERNAL, KnowledgeLifecycle.ACTIVE, "external_reference", (
        "references", "reference", "sources", "research", "参考资料", "对标",
    )),
    (AuthorityLevel.AUDIT, KnowledgeLifecycle.DEPRECATED, "archived_artifact", ("archive",)),
)

CODE_HINTS = ("agentlab", "coding", "codebase", "spatial")
NARRATIVE_HINTS = (
    "novel", "crown", "story", "fiction", "narrative", "longform", "小说", "长篇",
)
MEDIA_HINTS = ("video", "image", "audio", "music", "media", "film")
RESEARCH_HINTS = ("research", "study", "survey")
SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class SourceCollector:
    def __init__(self, agentlab_root: Path, *, max_file_bytes: int = 1_000_000) -> None:
        self.root = Path(agentlab_root).resolve()
        self.max_file_bytes = max_file_bytes

    def collect_system(self, *, include_ineligible: bool = False) -> list[KnowledgeRecord]:
        sources: dict[Path, tuple[AuthorityLevel, KnowledgeLifecycle, str]] = {}
        for name in (
            "AGENTS.md",
            "OPERATING_MODEL.md",
            "DRIVER_PROTOCOL.md",
            "README.md",
            "CLAUDE.md",
            "CLI_ROADMAP.md",
            "CONTEXT.md",
            "PROJECT_HANDOFF.md",
            "USAGE_PLAN.md",
            "pyproject.toml",
            "agentlab.sh",
            "agentlab_app.py",
            ".codex/REPO_GUIDE.md",
            ".codex/MAINLINE.md",
        ):
            path = self.root / name
            if path.is_file() and not path.is_symlink():
                sources[path] = (AuthorityLevel.CANONICAL, KnowledgeLifecycle.ACTIVE, "agentlab_source")
        for relative in (
            "agent_runtime",
            "config",
            "docs",
            "skills/active",
            "agent_templates",
            "scripts",
            "tests",
            "web_ui",
            "examples",
            ".github/workflows",
            ".clinerules",
        ):
            directory = self.root / relative
            if directory.is_dir():
                for path in self._walk(directory):
                    if relative == "docs" and "archive" in path.relative_to(directory).parts:
                        if include_ineligible:
                            sources[path] = (
                                AuthorityLevel.AUDIT,
                                KnowledgeLifecycle.DEPRECATED,
                                "archived_governance_document",
                            )
                        continue
                    sources[path] = (
                        AuthorityLevel.CANONICAL,
                        KnowledgeLifecycle.ACTIVE,
                        "agentlab_source",
                    )
        for relative in ("_shared/AGENT_PROTOCOL.md", "_shared/AGENT_HANDOFF.md"):
            path = self.root / relative
            if path.is_file() and not path.is_symlink():
                sources[path] = (
                    AuthorityLevel.CANONICAL,
                    KnowledgeLifecycle.ACTIVE,
                    "governance_protocol",
                )
        if include_ineligible:
            for relative in (
                ".agents/agent_states", ".agents/locks", ".agents/projects",
                ".agents/sessions", ".agents/exports", "agents", "acceptance_runs",
            ):
                directory = self.root / relative
                if directory.is_dir():
                    for path in self._walk(directory):
                        sources.setdefault(
                            path,
                            (AuthorityLevel.AUDIT, KnowledgeLifecycle.ACTIVE, "governance_audit"),
                        )
        return [
            record
            for path, (authority, lifecycle, kind) in sorted(sources.items(), key=lambda item: str(item[0]))
            if (record := self._record_for_file(
                path,
                namespace="system.agentlab",
                project_id=None,
                authority=authority,
                lifecycle=lifecycle,
                object_kind=kind,
            )) is not None
        ]

    def discover_projects(self) -> list[str]:
        projects_root = assert_path_allowed(self.root / "projects", self.root)
        if not projects_root.is_dir():
            return []
        return sorted(
            path.name
            for path in projects_root.iterdir()
            if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
        )

    def infer_project_domain(self, project: str) -> str:
        project_root = assert_path_allowed(self.root / "projects" / project, self.root)
        normalized = project.lower()
        if any(hint in normalized for hint in CODE_HINTS):
            return "code_engineering"
        if any(hint in normalized for hint in NARRATIVE_HINTS):
            return "longform_narrative"
        if any(hint in normalized for hint in MEDIA_HINTS):
            return "media_production"
        if any(hint in normalized for hint in RESEARCH_HINTS):
            return "research"
        if project_root.is_dir():
            narrative_file_hints = ("chapter", "character", "story_bible", "章节", "人物")
            if any(
                any(hint in path.name.lower() for hint in narrative_file_hints)
                for path in self._walk(project_root)
            ):
                return "longform_narrative"
        return "code_engineering"

    def collect_project(
        self,
        project: str,
        *,
        domain: str,
        namespace: str | None = None,
        include_ineligible: bool = False,
    ) -> list[KnowledgeRecord]:
        project_root = assert_path_allowed(self.root / "projects" / project, self.root)
        if not project_root.is_dir():
            return []
        target_namespace = namespace or f"project.{project}"
        sources: dict[Path, tuple[AuthorityLevel, KnowledgeLifecycle, str]] = {}
        artifact_index = project_root / "project_artifact_index.yml"
        if artifact_index.is_file() and not artifact_index.is_symlink():
            sources[artifact_index] = (
                AuthorityLevel.CANONICAL,
                KnowledgeLifecycle.ACTIVE,
                "artifact_index",
            )
            current_release = _current_release_directory(project_root, artifact_index)
            if current_release is not None:
                for path in self._walk(current_release):
                    sources[path] = (
                        AuthorityLevel.ACCEPTED,
                        KnowledgeLifecycle.ACTIVE,
                        "formal_release",
                    )
        allowed = {AuthorityLevel.CANONICAL, AuthorityLevel.ACCEPTED}
        for authority, lifecycle, kind, relatives in PROJECT_SOURCE_GROUPS:
            if not include_ineligible and authority not in allowed:
                continue
            for relative in relatives:
                directory = project_root / relative
                if directory.is_dir():
                    for path in self._walk(directory):
                        sources.setdefault(path, (authority, lifecycle, kind))
        records = []
        for path, (authority, lifecycle, kind) in sorted(sources.items(), key=lambda item: str(item[0])):
            object_kind = domain if domain in {"longform_narrative", "research"} else kind
            record = self._record_for_file(
                path,
                namespace=target_namespace,
                project_id=project,
                authority=authority,
                lifecycle=lifecycle,
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
        lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.ACTIVE,
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
                lifecycle=lifecycle,
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
            if any(part in HARD_EXCLUDED_PARTS for part in relative_parts):
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
        lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.ACTIVE,
    ) -> KnowledgeRecord | None:
        path = assert_path_allowed(path, self.root)
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return None
        modality = _modality_for(path)
        is_media = modality in {Modality.IMAGE, Modality.AUDIO, Modality.VIDEO}
        if size > self.max_file_bytes and not is_media:
            return None
        if is_media:
            try:
                source_hash = _sha256_file(path)
            except OSError:
                return None
            raw = b""
        else:
            try:
                raw = path.read_bytes()
            except OSError:
                return None
            source_hash = hashlib.sha256(raw).hexdigest()
        metadata = {"suffix": path.suffix.lower(), "size_bytes": size, "raw_payload_indexed": False}
        if is_media:
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
            lifecycle=lifecycle,
            modality=modality,
            object_kind=object_kind,
            metadata=metadata,
        )


def _current_release_directory(project_root: Path, artifact_index: Path) -> Path | None:
    try:
        raw = yaml.safe_load(artifact_index.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    current_release = raw.get("current_release") if isinstance(raw, dict) else None
    if not isinstance(current_release, dict):
        return None
    edition_id = str(current_release.get("edition_id") or "")
    if not SAFE_RELEASE_ID.fullmatch(edition_id):
        return None
    directory = project_root / "release_objects" / "editions" / edition_id
    return directory if directory.is_dir() and not directory.is_symlink() else None


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
