"""Automatic source discovery for system and project knowledge spaces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

import yaml

from agent_runtime.artifact_digest import artifact_sha256
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
        "project_brain", "config",
    )),
    (AuthorityLevel.CANDIDATE, KnowledgeLifecycle.ACTIVE, "candidate_artifact", (
        "candidates", "candidate", "revisions", "artifacts", "memory_snapshot",
    )),
    (AuthorityLevel.AUDIT, KnowledgeLifecycle.ACTIVE, "audit_evidence", (
        "acceptance", "evaluation_runs", "runs", "background_jobs", "observability", "cost",
        "agent_docs", "docs", "prompt_templates", "skills", "tasks", "production",
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
            if (
                not _has_symlink_component(path, self.root)
                and path.is_file()
                and not path.is_symlink()
            ):
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
            if not _has_symlink_component(directory, self.root) and directory.is_dir():
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
            if (
                not _has_symlink_component(path, self.root)
                and path.is_file()
                and not path.is_symlink()
            ):
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
        raw_projects_root = self.root / "projects"
        if _has_symlink_component(raw_projects_root, self.root):
            return []
        projects_root = assert_path_allowed(raw_projects_root, self.root)
        if not projects_root.is_dir():
            return []
        return sorted(
            path.name
            for path in projects_root.iterdir()
            if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
        )

    def infer_project_domain(self, project: str) -> str:
        raw_project_root = self.root / "projects" / project
        if _has_symlink_component(raw_project_root, self.root / "projects"):
            return "code_engineering"
        project_root = assert_path_allowed(raw_project_root, self.root)
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
        raw_project_root = self.root / "projects" / project
        if _has_symlink_component(raw_project_root, self.root / "projects"):
            return []
        project_root = assert_path_allowed(raw_project_root, self.root)
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
            for selected_root in _current_artifact_roots(project_root, artifact_index):
                selected_paths = (
                    (selected_root,)
                    if selected_root.is_file()
                    else self._walk(selected_root)
                )
                for path in selected_paths:
                    sources[path] = (
                        AuthorityLevel.ACCEPTED,
                        KnowledgeLifecycle.ACTIVE,
                        "formal_release",
                    )
        # Runtime v2 exposes one curated metadata surface. Raw ledgers, attempts,
        # failed drafts, and task artifact bytes remain deliberately unindexed.
        runtime_selected = project_root / "runtime" / "knowledge" / "selected_artifacts.yml"
        if (
            not _has_symlink_component(runtime_selected, project_root)
            and runtime_selected.is_file()
            and not runtime_selected.is_symlink()
        ):
            sources[runtime_selected] = (
                AuthorityLevel.CANONICAL,
                KnowledgeLifecycle.ACTIVE,
                "task_runtime_selected_manifest",
            )
        allowed = {AuthorityLevel.CANONICAL, AuthorityLevel.ACCEPTED}
        for authority, lifecycle, kind, relatives in PROJECT_SOURCE_GROUPS:
            if not include_ineligible and authority not in allowed:
                continue
            for relative in relatives:
                directory = project_root / relative
                if _has_symlink_component(directory, project_root):
                    continue
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
            if _has_symlink_component(path, directory):
                continue
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


def _current_release_paths(project_root: Path, artifact_index: Path) -> tuple[Path, ...]:
    try:
        raw = yaml.safe_load(artifact_index.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return ()
    current_release = raw.get("current_release") if isinstance(raw, dict) else None
    if not isinstance(current_release, dict):
        return ()
    edition_id = str(current_release.get("edition_id") or "")
    if not SAFE_RELEASE_ID.fullmatch(edition_id):
        return ()
    release_slot = str(current_release.get("release_slot") or "")
    candidate_set_id = str(current_release.get("candidate_set_id") or "")
    candidate_set_sha256 = str(current_release.get("candidate_set_sha256") or "")
    if not SAFE_RELEASE_ID.fullmatch(release_slot):
        return ()
    if not SAFE_RELEASE_ID.fullmatch(candidate_set_id):
        return ()
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_set_sha256):
        return ()
    directory = project_root / "release_objects" / "editions" / edition_id
    if _has_symlink_component(directory, project_root):
        return ()
    if not directory.is_dir() or directory.is_symlink():
        return ()
    receipt_path = directory / "promotion_receipt.yml"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        return ()
    expected_receipt_path = (
        Path("release_objects") / "editions" / edition_id / "promotion_receipt.yml"
    ).as_posix()
    if str(current_release.get("promotion_receipt") or "") != expected_receipt_path:
        return ()
    try:
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return ()
    if not isinstance(receipt, dict) or str(receipt.get("status") or "").lower() != "promoted":
        return ()
    if str(receipt.get("edition_id") or "") != edition_id:
        return ()
    if str(receipt.get("release_slot") or "") != release_slot:
        return ()
    if str(receipt.get("candidate_set_id") or "") != candidate_set_id:
        return ()
    if str(receipt.get("candidate_set_sha256") or "") != candidate_set_sha256:
        return ()
    chapters = receipt.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return ()
    try:
        expected_ids = {int(value) for value in current_release.get("chapter_ids") or []}
    except (TypeError, ValueError):
        return ()
    if not expected_ids:
        return ()
    observed_ids: set[int] = set()
    selected_paths = [receipt_path]
    for chapter in chapters:
        if not isinstance(chapter, dict):
            return ()
        try:
            chapter_id = int(chapter.get("chapter_id"))
        except (TypeError, ValueError):
            return ()
        if chapter_id in observed_ids:
            return ()
        expected_sha256 = str(chapter.get("artifact_sha256") or "")
        chapter_path = directory / f"chapter_{chapter_id:03d}.md"
        expected_artifact_path = (
            Path("release_objects")
            / "editions"
            / edition_id
            / f"chapter_{chapter_id:03d}.md"
        ).as_posix()
        if str(chapter.get("artifact_path") or "") != expected_artifact_path:
            return ()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            return ()
        if not chapter_path.is_file() or chapter_path.is_symlink():
            return ()
        if _sha256_file(chapter_path) != expected_sha256:
            return ()
        observed_ids.add(chapter_id)
        selected_paths.append(chapter_path)
    if observed_ids != expected_ids:
        return ()
    return tuple(selected_paths)


def _current_artifact_roots(project_root: Path, artifact_index: Path) -> tuple[Path, ...]:
    roots = list(_current_release_paths(project_root, artifact_index))
    try:
        raw = yaml.safe_load(artifact_index.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return tuple(roots)
    artifacts = raw.get("artifacts") if isinstance(raw, dict) else None
    if not isinstance(artifacts, list):
        return tuple(roots)
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("status") or "").lower() != "current":
            continue
        if bool(artifact.get("evidence_only", False)):
            continue
        raw_path = str(artifact.get("production_path") or "")
        relative = Path(raw_path)
        if not raw_path or relative.is_absolute() or ".." in relative.parts:
            continue
        if not relative.parts or relative.parts[0] != "production":
            continue
        raw_selected = project_root / relative
        if _has_symlink_component(raw_selected, project_root):
            continue
        try:
            selected = assert_path_allowed(raw_selected, project_root / "production")
        except ValueError:
            continue
        if selected.is_symlink() or not (selected.is_file() or selected.is_dir()):
            continue
        expected_sha256 = str(artifact.get("production_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            continue
        try:
            actual_sha256 = artifact_sha256(selected)
        except (OSError, ValueError):
            continue
        if actual_sha256 != expected_sha256:
            continue
        roots.append(selected)
    return tuple(dict.fromkeys(roots))


def _has_symlink_component(path: Path, root: Path) -> bool:
    """Return true before resolution if any path component below *root* is a symlink."""
    lexical_root = Path(root).absolute()
    if lexical_root.is_symlink():
        return True
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = lexical_root / candidate
    try:
        relative = candidate.relative_to(lexical_root)
    except ValueError:
        return True
    current = lexical_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


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
