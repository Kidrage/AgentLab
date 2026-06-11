"""Optional webhook notification channel for AgentLab feedback events."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import hmac
import json
import os
import time
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from atomic_io import atomic_write_yaml, safe_read_yaml


DISPATCHABLE_EVENTS = {
    "ACTION_REQUIRED",
    "BLOCKED",
    "BUDGET_WARNING",
    "STALE_RUNNING",
    "FAILED_RECOVERABLE",
    "COMPLETED",
    "SKILL_REQUEST_PENDING",
    "SKILL_CANDIDATE_READY",
    "SKILL_PROMOTED",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def webhook_policy_path(agentlab_root: Path) -> Path:
    return agentlab_root / "config" / "webhook_policy.yml"


def load_policy(agentlab_root: Path) -> dict[str, Any]:
    policy = safe_read_yaml(webhook_policy_path(agentlab_root), default={}) or {}
    policy.setdefault("schema_version", 1)
    policy.setdefault("enabled", False)
    policy.setdefault("endpoints", [])
    policy.setdefault("retry", {})
    policy["retry"].setdefault("max_attempts", 3)
    policy["retry"].setdefault("backoff_seconds", 2)
    policy.setdefault("security", {})
    policy["security"].setdefault("sign_payload", True)
    policy["security"].setdefault("redact_secrets", True)
    return policy


def delivery_log_path(agentlab_root: Path, project: str, task_id: str | None = None) -> Path:
    if task_id:
        return agentlab_root / "projects" / project / "runs" / task_id / "webhook_delivery_log.yml"
    return agentlab_root / "projects" / project / "webhook_delivery_log.yml"


def _load_log(path: Path) -> dict[str, Any]:
    data = safe_read_yaml(path, default={}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema_version", 1)
    data.setdefault("deliveries", [])
    return data


def append_delivery_log(agentlab_root: Path, project: str, task_id: str | None, entry: dict[str, Any]) -> Path:
    path = delivery_log_path(agentlab_root, project, task_id)
    data = _load_log(path)
    data["deliveries"].append(entry)
    atomic_write_yaml(path, data)
    return path


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if any(token in str(key).lower() for token in ("secret", "token", "api_key", "apikey", "password")):
                redacted[key] = "REDACTED"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def build_payload(
    *,
    event: str,
    project: str,
    task_id: str | None = None,
    stage: str | None = None,
    severity: str | None = None,
    summary: str = "",
    reason: str = "",
    decision_card: dict[str, Any] | None = None,
    links: dict[str, str] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "event": event,
        "project": project,
        "task_id": task_id,
        "stage": stage,
        "severity": severity or event,
        "summary": summary,
        "reason": reason,
        "decision_card": decision_card,
        "links": links or {},
        "created_at": created_at or utc_now(),
    }


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 10) -> tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    req = urllib_request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")[:500]
    except HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")[:500]
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _endpoint_enabled(endpoint: dict[str, Any], event: str) -> bool:
    events = endpoint.get("events") or []
    return not events or event in events


def dispatch_event(
    agentlab_root: Path,
    *,
    event: str,
    project: str,
    task_id: str | None = None,
    stage: str | None = None,
    severity: str | None = None,
    summary: str = "",
    reason: str = "",
    decision_card: dict[str, Any] | None = None,
    links: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event not in DISPATCHABLE_EVENTS:
        raise ValueError(f"Unsupported webhook event: {event}")

    policy = load_policy(agentlab_root)
    base_payload = payload or build_payload(
        event=event,
        project=project,
        task_id=task_id,
        stage=stage,
        severity=severity,
        summary=summary,
        reason=reason,
        decision_card=decision_card,
        links=links,
    )
    if policy.get("security", {}).get("redact_secrets", True):
        base_payload = redact_payload(base_payload)

    if not policy.get("enabled", False):
        return {"ok": True, "enabled": False, "deliveries": [], "payload": base_payload}

    retry = policy.get("retry", {})
    max_attempts = max(1, int(retry.get("max_attempts", 3)))
    backoff = max(0, float(retry.get("backoff_seconds", 2)))
    deliveries: list[dict[str, Any]] = []
    for endpoint in policy.get("endpoints", []):
        name = endpoint.get("name", "webhook")
        if not _endpoint_enabled(endpoint, event):
            continue
        url = os.getenv(endpoint.get("url_env", ""))
        if not url:
            deliveries.append({"endpoint": name, "status": "skipped", "reason": "url_env_not_configured"})
            continue
        body = json.dumps(base_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "AgentLab-Webhook/1"}
        secret = os.getenv(endpoint.get("secret_env", ""))
        if policy.get("security", {}).get("sign_payload", True) and secret:
            headers["X-AgentLab-Signature"] = _signature(secret, body)

        attempts = []
        delivered = False
        for attempt in range(1, max_attempts + 1):
            try:
                status_code, response_text = post_json(url, base_payload, headers)
                ok = 200 <= status_code < 300
                attempts.append({"attempt": attempt, "status_code": status_code, "ok": ok, "response": response_text})
                if ok:
                    delivered = True
                    break
            except Exception as exc:
                attempts.append({"attempt": attempt, "ok": False, "error": str(exc)})
            if attempt < max_attempts and backoff:
                time.sleep(backoff)

        entry = {
            "endpoint": name,
            "event": event,
            "project": project,
            "task_id": task_id,
            "created_at": utc_now(),
            "status": "delivered" if delivered else "failed",
            "attempts": attempts,
            "payload": base_payload,
        }
        append_delivery_log(agentlab_root, project, task_id, entry)
        deliveries.append(entry)

    return {"ok": all(d.get("status") in {"delivered", "skipped"} for d in deliveries), "enabled": True, "deliveries": deliveries, "payload": base_payload}


def webhook_status(agentlab_root: Path, project: str, task_id: str | None = None) -> dict[str, Any]:
    path = delivery_log_path(agentlab_root, project, task_id)
    data = _load_log(path)
    return {
        "project": project,
        "task_id": task_id,
        "path": str(path),
        "delivery_count": len(data.get("deliveries", [])),
        "deliveries": data.get("deliveries", []),
    }


def redeliver_last_failed(agentlab_root: Path, project: str, task_id: str | None = None) -> dict[str, Any]:
    status = webhook_status(agentlab_root, project, task_id)
    failed = [item for item in status.get("deliveries", []) if item.get("status") == "failed"]
    if not failed:
        return {"ok": True, "redelivered": False, "reason": "no_failed_delivery"}
    last = failed[-1]
    payload = dict(last.get("payload", {}))
    event = payload.get("event") or last.get("event")
    return dispatch_event(agentlab_root, event=event, project=project, task_id=task_id, payload=payload)
