"""Content-free, append-only telemetry for narrative model invocations.

The recorder is deliberately opt-in. It snapshots immutable metadata immediately
after a provider returns so later schema failures, retries, or overwritten role
manifests cannot erase evidence of a paid call.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

import yaml

from agent_runtime.observability.log_redaction import redact_secrets


NARRATIVE_DIAGNOSTICS_ENV = "AGENTLAB_NARRATIVE_DIAGNOSTICS"
INVOCATION_LOG_NAME = "narrative_invocations.jsonl"
_SCHEMA_VERSION = 1
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _diagnostics_enabled(plan: Any) -> bool:
    enabled = os.getenv(NARRATIVE_DIAGNOSTICS_ENV, "").strip().lower()
    route_key = str(getattr(getattr(plan, "route", None), "route_key", ""))
    return enabled in _TRUE_VALUES and route_key.startswith("narrative_")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_yaml_mapping(
    path_value: Any, run_dir: Path
) -> tuple[dict[str, Any], str | None]:
    if not path_value:
        return {}, None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = run_dir / path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}, str(path)
    return _mapping(data), str(path)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _sum_numeric(values: Sequence[Any]) -> int | None:
    numeric = [value for value in values if isinstance(value, (int, float))]
    return int(sum(numeric)) if numeric else None


def _text_fingerprint(value: Any) -> dict[str, Any]:
    if not value:
        return {
            "error_present": False,
            "error_chars": 0,
            "error_sha256": None,
        }
    rendered = str(value)
    return {
        "error_present": True,
        "error_chars": len(rendered),
        "error_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }


def _content_free_path(path_value: str | None, run_dir: Path) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        return str(path.relative_to(run_dir))
    except ValueError:
        return path.name


def _redact_string_values(value: Any) -> Any:
    """Redact secrets in values without treating metric names as credentials."""

    if isinstance(value, dict):
        return {key: _redact_string_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_string_values(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


@contextmanager
def _exclusive_append_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_append_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def record_narrative_invocation(
    plan: Any,
    role: str,
    result: Any,
    *,
    provider_surface: str,
    capacity_route: str | None = None,
    context_manifest_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Persist one content-free provider-call snapshot when diagnostics are enabled."""

    if not _diagnostics_enabled(plan):
        return None

    run_dir = Path(str(plan.run_dir))
    raw_usage = _mapping(getattr(result, "raw_usage", None))
    receipt, receipt_path = _read_yaml_mapping(
        raw_usage.get("model_execution_receipt"), run_dir
    )
    manifest, manifest_path = _read_yaml_mapping(
        _first_present(
            raw_usage.get("outbound_context_manifest"), context_manifest_path
        ),
        run_dir,
    )

    reported_usage = _mapping(receipt.get("provider_reported_usage"))
    payload = _mapping(manifest.get("payload"))
    inventory = _mapping(manifest.get("source_inventory"))
    source_files = [
        _mapping(item)
        for item in inventory.get("files", [])
        if isinstance(item, Mapping)
    ]

    event = {
        "schema_version": _SCHEMA_VERSION,
        "invocation_id": uuid4().hex,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "task": {
            "project": str(getattr(plan, "project", "")),
            "id": str(getattr(plan, "task_id", "")),
            "route_key": str(getattr(getattr(plan, "route", None), "route_key", "")),
        },
        "role": role,
        "attempt": {
            "id": _first_present(
                receipt.get("attempt_id"), raw_usage.get("capacity_attempt_id")
            ),
            "capacity_route": _first_present(
                capacity_route, receipt.get("capacity_route")
            ),
            "selection_kind": _first_present(
                receipt.get("selection_kind"), raw_usage.get("capacity_selection_kind")
            ),
        },
        "provider": {
            "surface": provider_surface,
            "result_provider": getattr(result, "provider", None),
            "selected": receipt.get("selected_provider"),
            "selected_model": _first_present(
                receipt.get("selected_model_id"), getattr(result, "model", None)
            ),
            "reported_model": receipt.get("provider_reported_primary_model_id"),
            "session_id": receipt.get("provider_reported_session_id"),
            "process_started": _first_present(
                receipt.get("provider_process_started"),
                raw_usage.get("provider_process_started"),
            ),
        },
        "timing": {
            "model_active_seconds": raw_usage.get("duration_s"),
            "measurement": (
                "provider_reported"
                if raw_usage.get("duration_s") is not None
                else "missing"
            ),
        },
        "usage": {
            "input_tokens": _first_present(
                reported_usage.get("input_tokens"),
                getattr(result, "input_tokens", None),
            ),
            "output_tokens": _first_present(
                reported_usage.get("output_tokens"),
                getattr(result, "output_tokens", None),
            ),
            "cache_read_input_tokens": reported_usage.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": reported_usage.get(
                "cache_creation_input_tokens"
            ),
            "total_tokens": _first_present(
                reported_usage.get("total_tokens"),
                getattr(result, "total_tokens", None),
            ),
            "model_breakdown": _mapping(
                reported_usage.get("provider_reported_model_usage")
            ),
        },
        "cost": {
            "amount": _first_present(
                reported_usage.get("estimated_cost"), raw_usage.get("cost_usd")
            ),
            "currency": _first_present(reported_usage.get("cost_currency"), "USD"),
            "source": _first_present(
                reported_usage.get("usage_source"), raw_usage.get("usage_source")
            ),
        },
        "context": {
            "payload_bytes": payload.get("bytes"),
            "payload_sha256": payload.get("sha256"),
            "source_count": _first_present(
                inventory.get("count"), len(source_files) if source_files else None
            ),
            "source_bytes": _sum_numeric([item.get("bytes") for item in source_files]),
            "source_files": [
                {
                    "path": item.get("path"),
                    "bytes": item.get("bytes"),
                    "sha256": item.get("sha256"),
                }
                for item in source_files
            ],
            "manifest_path": _content_free_path(manifest_path, run_dir),
        },
        "result": {
            "status": getattr(result, "status", None),
            **_text_fingerprint(getattr(result, "error", None)),
            "failure_class": raw_usage.get("failure_class"),
        },
        "evidence": {"model_receipt_path": _content_free_path(receipt_path, run_dir)},
        "safety": {"candidate_only": True, "production_modified": False},
    }
    safe_event = _redact_string_values(event)
    _append_event(run_dir / INVOCATION_LOG_NAME, safe_event)
    return safe_event
