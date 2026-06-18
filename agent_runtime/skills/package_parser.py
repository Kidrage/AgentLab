"""S3 Skill package parser.

Parses local skill package metadata from SKILL.md, skill.yml, manifest.yml, and
nearby examples/tests folders. Parsing is read-only and never executes package
code.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "unnamed-skill"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---"):
        return {}, markdown
    parts = markdown.split("---", 2)
    if len(parts) < 3:
        return {}, markdown
    data = yaml.safe_load(parts[1]) or {}
    return data if isinstance(data, dict) else {}, parts[2].lstrip()


def _skill_markdown(path: Path) -> tuple[Path | None, dict[str, Any], str]:
    skill_path = path if path.is_file() else path / "SKILL.md"
    if not skill_path.exists():
        return None, {}, ""
    text = skill_path.read_text(encoding="utf-8")
    metadata, body = _frontmatter(text)
    return skill_path, metadata, body


def _list_child_names(path: Path, name: str) -> list[str]:
    directory = path / name
    if not directory.is_dir():
        return []
    return sorted(child.name for child in directory.iterdir() if child.is_file())


def _permissions(raw: dict[str, Any]) -> dict[str, Any]:
    permissions = raw.get("permissions") or raw.get("permission") or {}
    if not isinstance(permissions, dict):
        permissions = {}
    return {
        "filesystem_read": list(permissions.get("filesystem_read") or permissions.get("read") or []),
        "filesystem_write": list(permissions.get("filesystem_write") or permissions.get("write") or []),
        "shell": bool(permissions.get("shell", False)),
        "network": bool(permissions.get("network", False)),
        "env": bool(permissions.get("env", False)),
        "secrets": bool(permissions.get("secrets", False)),
        "external_tools": list(permissions.get("external_tools") or []),
    }


def _validation_errors(parsed: dict[str, Any], declared: dict[str, bool]) -> list[str]:
    errors: list[str] = []
    if not parsed.get("capabilities"):
        errors.append("capabilities must be declared")
    if not declared.get("permissions"):
        errors.append("permissions must be declared")
    if not declared.get("risk_level"):
        errors.append("risk_level must be declared")
    if parsed.get("source", {}).get("type") == "unknown":
        errors.append("source type is unknown")
    return errors


def parse_skill_package(path: Path | str) -> dict[str, Any]:
    """Parse a local skill package into normalized S3 metadata."""

    package_path = Path(path)
    root = package_path if package_path.is_dir() else package_path.parent
    skill_path, skill_meta, body = _skill_markdown(package_path)
    skill_yml = _read_yaml(root / "skill.yml")
    manifest_yml = _read_yaml(root / "manifest.yml")
    raw = {**manifest_yml, **skill_yml, **skill_meta}

    name = str(raw.get("name") or raw.get("skill_id") or root.name)
    description = str(raw.get("description") or "").strip()
    capabilities = raw.get("capabilities") or raw.get("suitable_task_types") or []
    if isinstance(capabilities, str):
        capabilities = [capabilities]
    if not capabilities and description:
        capabilities = [_slug(description)[:80]]

    risk = raw.get("risk") or {}
    risk_level = raw.get("risk_level") or (risk.get("level") if isinstance(risk, dict) else None)
    source = raw.get("source") or {}
    if not isinstance(source, dict):
        source = {"type": str(source)}
    source_type = str(source.get("type") or raw.get("source_type") or "unknown")

    declared = {
        "permissions": "permissions" in raw or "permission" in raw,
        "risk_level": bool(risk_level),
    }
    parsed = {
        "skill_id": _slug(str(raw.get("skill_id") or name)),
        "display_name": name,
        "description": description,
        "capabilities": [str(item) for item in capabilities],
        "permissions": _permissions(raw),
        "dependencies": list(raw.get("dependencies") or []),
        "risk_level": str(risk_level or "medium").lower(),
        "source": {
            "type": source_type,
            "path": str(skill_path or package_path),
        },
        "license": raw.get("license") or {"name": "unknown", "license_review_required": True},
        "entrypoints": list(raw.get("entrypoints") or []),
        "examples": _list_child_names(root, "examples"),
        "tests": _list_child_names(root, "tests"),
        "files": {
            "skill_md": str(skill_path) if skill_path else None,
            "skill_yml": str(root / "skill.yml") if (root / "skill.yml").exists() else None,
            "manifest_yml": str(root / "manifest.yml") if (root / "manifest.yml").exists() else None,
            "readme_md": str(root / "README.md") if (root / "README.md").exists() else None,
        },
        "body_preview": body[:240],
    }
    parsed["validation_errors"] = _validation_errors(parsed, declared)
    parsed["dispatchable"] = False
    return parsed
