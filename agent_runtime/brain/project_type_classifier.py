"""Project type classifier — maps domain + prompt to canonical project type."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_project_type_keywords(config_path: Path | None = None) -> dict[str, Any]:
    if config_path is None:
        config_path = _default_config_path()
    if not config_path.exists():
        return {}
    import yaml

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("project_type_keywords", {}) if isinstance(data, dict) else {}


def load_project_types(config_path: Path | None = None) -> dict[str, Any]:
    """Load the full project_types definitions from project_type_classifier.yml."""
    if config_path is None:
        config_path = _project_type_config_path()
    if not config_path.exists():
        return {}
    import yaml

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("project_types", {}) if isinstance(data, dict) else {}


# domain → default project_type mapping
_DOMAIN_TO_PROJECT_TYPE: dict[str, str] = {
    "coding": "codebase_build_project",
    "creative_longform": "longform_text_project",
    "video_generation": "video_generation_project",
    "image_generation": "media_generation_project",
    "image_editing": "media_generation_project",
    "video_editing": "media_generation_project",
    "research": "research_archive_project",
    "document_processing": "document_knowledgebase_project",
    "multimodal": "multimodal_content_project",
    "audio_music": "multimodal_content_project",
    "local_ops": "local_automation_project",
    "unknown": "unknown_project",
}


def classify_project_type(
    prompt: str,
    domain: str,
    project_type_keywords: dict[str, Any] | None = None,
) -> str:
    """Classify a prompt into a canonical project type.

    Uses keyword matching first; falls back to domain→project_type mapping.
    """
    if project_type_keywords is None:
        project_type_keywords = load_project_type_keywords()
    lowered = prompt.lower()
    scores: dict[str, int] = {}
    for ptype, keywords in project_type_keywords.items():
        score = 0
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            if kw.lower() in lowered:
                score += len(kw.split())
        if score > 0:
            scores[ptype] = score
    if scores:
        return max(scores, key=lambda k: scores[k])
    # fallback to domain mapping
    return _DOMAIN_TO_PROJECT_TYPE.get(domain, "unknown_project")


def get_project_type_definition(
    project_type: str,
    project_types: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the full project type definition dict."""
    if project_types is None:
        project_types = load_project_types()
    return project_types.get(project_type, project_types.get("unknown_project", {}))


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "mission_compiler_v2.yml"


def _project_type_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "project_type_classifier.yml"
