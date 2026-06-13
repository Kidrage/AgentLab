from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.governance.models import GovernanceInputBundle


SECRET_NAME_MARKERS = ("secret", "secrets", ".env", "token", "credential", "apikey", "api_key")
MAX_YAML_BYTES = 1_000_000


def load_execution_ledgers(paths: list[Path]) -> list[dict[str, Any]]:
    return [item for item, _warning in (_safe_load_yaml(path) for path in paths) if isinstance(item, dict)]


def load_retry_attempt_ledgers(paths: list[Path]) -> list[dict[str, Any]]:
    return [item for item, _warning in (_safe_load_yaml(path) for path in paths) if isinstance(item, dict)]


def load_provider_scorecards(paths: list[Path]) -> list[dict[str, Any]]:
    return [item for item, _warning in (_safe_load_yaml(path) for path in paths) if isinstance(item, dict)]


def load_final_receipts(paths: list[Path]) -> list[dict[str, Any]]:
    return [item for item, _warning in (_safe_load_yaml(path) for path in paths) if isinstance(item, dict)]


def discover_governance_inputs(
    root: Path,
    executor_runs: str | Path = "executor_runs",
    retry_runs: str | Path = "retry_runs",
) -> GovernanceInputBundle:
    root = root.resolve()
    warnings: list[str] = []
    manifest: dict[str, Any] = {
        "root": "[REDACTED_ROOT]",
        "execution_ledgers": [],
        "retry_attempt_ledgers": [],
        "provider_scorecards": [],
        "final_receipts": [],
        "warnings": warnings,
    }

    search_roots = [root / executor_runs, root / retry_runs]
    existing_roots: list[Path] = []
    for search_root in search_roots:
        if not search_root.exists():
            warnings.append(f"missing input directory: {_redact_path(search_root, root)}")
            continue
        existing_roots.append(search_root)

    paths = {
        "execution_ledgers": _discover_named(existing_roots, "execution_ledger.yml", root, warnings),
        "retry_attempt_ledgers": _discover_named(existing_roots, "retry_attempt_ledger.yml", root, warnings),
        "provider_scorecards": _discover_named(existing_roots, "provider_scorecard.yml", root, warnings),
        "final_receipts": [
            *_discover_named(existing_roots, "final_acceptance_receipt.yml", root, warnings),
            *_discover_named(existing_roots, "final_rejection_receipt.yml", root, warnings),
        ],
    }
    for key, found in paths.items():
        manifest[key] = [_redact_path(path, root) for path in found]

    execution_ledgers = _load_many(paths["execution_ledgers"], root, warnings)
    retry_attempt_ledgers = _load_many(paths["retry_attempt_ledgers"], root, warnings)
    provider_scorecards = _load_many(paths["provider_scorecards"], root, warnings)
    final_receipts = _load_many(paths["final_receipts"], root, warnings)

    return GovernanceInputBundle(
        root=root,
        execution_ledgers=execution_ledgers,
        retry_attempt_ledgers=retry_attempt_ledgers,
        provider_scorecards=provider_scorecards,
        final_receipts=final_receipts,
        manifest=manifest,
        warnings=warnings,
    )


def _discover_named(roots: list[Path], filename: str, root: Path, warnings: list[str]) -> list[Path]:
    found: list[Path] = []
    for search_root in roots:
        for path in sorted(search_root.rglob(filename)):
            if _looks_secret(path):
                warnings.append(f"skipped secret-like file: {_redact_path(path, root)}")
                continue
            if path.stat().st_size > MAX_YAML_BYTES:
                warnings.append(f"skipped oversized yaml: {_redact_path(path, root)}")
                continue
            found.append(path)
    return found


def _load_many(paths: list[Path], root: Path, warnings: list[str]) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for path in paths:
        data, warning = _safe_load_yaml(path)
        if warning:
            warnings.append(f"{_redact_path(path, root)}: {warning}")
            continue
        if isinstance(data, dict):
            loaded.append(_redact_value(data, root))
        else:
            warnings.append(f"{_redact_path(path, root)}: yaml root is not a mapping")
    return loaded


def _safe_load_yaml(path: Path) -> tuple[Any, str | None]:
    try:
        if _looks_secret(path):
            return None, "skipped secret-like file"
        if path.stat().st_size > MAX_YAML_BYTES:
            return None, "skipped oversized yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}, None
    except yaml.YAMLError as exc:
        return None, f"bad yaml: {exc.__class__.__name__}"
    except OSError as exc:
        return None, f"read failed: {exc.__class__.__name__}"


def _looks_secret(path: Path) -> bool:
    lowered = str(path).lower()
    return any(marker in lowered for marker in SECRET_NAME_MARKERS)


def _redact_value(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return value.replace(str(root), "[REDACTED_ROOT]").replace(str(Path.home()), "[REDACTED_HOME]")
    if isinstance(value, list):
        return [_redact_value(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, root) for key, item in value.items()}
    return value


def _redact_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path).replace(str(root), "[REDACTED_ROOT]").replace(str(Path.home()), "[REDACTED_HOME]")
