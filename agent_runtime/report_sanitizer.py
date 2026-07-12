from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


LOCAL_USERS_PATH_RE = re.compile(r"/" r"Users/[^\s`'\"<>]+")


def _local_path_token(path_text: str) -> str:
    name = Path(path_text).name or "redacted"
    return f"<local_path:{name}>"


def sanitize_report_value(value: Any, root: Path) -> Any:
    """Return a report-safe copy without machine-local absolute paths."""
    root_text = str(root.resolve())
    if isinstance(value, dict):
        return {
            key: sanitize_report_value(item, root)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [sanitize_report_value(item, root) for item in value if item is not None]
    if isinstance(value, tuple):
        return [sanitize_report_value(item, root) for item in value]
    if isinstance(value, str):
        text = value.replace(f"{root_text}/", "").replace(root_text, ".")
        return LOCAL_USERS_PATH_RE.sub(lambda match: _local_path_token(match.group(0)), text)
    return value


def dump_report_yaml(report: dict[str, Any], root: Path) -> str:
    safe_report = sanitize_report_value(report, root)
    return yaml.safe_dump(safe_report, sort_keys=False, allow_unicode=True)


def write_report_yaml(path: Path, report: dict[str, Any], root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_report_yaml(report, root), encoding="utf-8")
