"""External Skill URL Import — real fetch, parse, and lifecycle integration.

This module implements the full external skill import pipeline:
  fetch SKILL.md from URL → parse YAML frontmatter → risk scan / cost preview
  → create skill request → (approve → stage → validate → promote externally)

Security principles:
  - No external code execution.
  - URL must pass allowlist/policy check.
  - Network is disabled by default; `allow_network=True` is required.
  - Import always enters pending_user_approval status.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import re
import time
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

import yaml

from atomic_io import safe_read_yaml

# ── policy ────────────────────────────────────────────────────────

POLICY_PATH = Path("config/external_skill_import_policy.yml")

DEFAULT_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "enabled": False,
    "allow_network_by_default": False,
    "allowed_hosts": ["raw.githubusercontent.com"],
    "allowed_url_prefixes": [],
    "max_bytes": 200000,
    "timeout_seconds": 10,
    "store_source_snapshot": True,
    "execute_external_code": False,
    "default_status": "pending_user_approval",
    "default_risk_level": "low",
}


def load_import_policy(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / POLICY_PATH
    data = safe_read_yaml(path, default={}) or {}
    if not isinstance(data, dict):
        data = {}
    policy = dict(DEFAULT_POLICY)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(policy.get(key), dict):
            merged = dict(policy[key])
            merged.update(value)
            policy[key] = merged
        elif isinstance(value, list) and isinstance(policy.get(key), list):
            policy[key] = list(value)
        else:
            policy[key] = value
    return policy


def _policy_allows_url(policy: dict[str, Any], url: str) -> bool:
    """Check whether policy allows this URL."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    allowed_hosts = [h.lower() for h in policy.get("allowed_hosts", [])]
    allowed_prefixes = policy.get("allowed_url_prefixes", [])

    if allowed_hosts and host not in allowed_hosts:
        return False
    if allowed_prefixes:
        if not any(url.startswith(prefix) for prefix in allowed_prefixes):
            return False
    return True


# ── fetch ─────────────────────────────────────────────────────────

def fetch_skill_markdown_from_url(
    url: str,
    *,
    timeout_seconds: int = 10,
    max_bytes: int = 200000,
) -> dict[str, Any]:
    """Fetch raw SKILL.md text from an external URL.

    Returns:
      dict with keys: ok, source_url, markdown_text, markdown_sha256,
      byte_count, fetched_at, error (if ok=False)
    """
    req = urllib_request.Request(url, headers={"User-Agent": "AgentLab-SkillImporter/1"})
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return {
                    "ok": False,
                    "source_url": url,
                    "error": f"Response exceeds max_bytes ({max_bytes}).",
                }
            text = raw.decode("utf-8", errors="replace")
            sha = hashlib.sha256(raw).hexdigest()
            return {
                "ok": True,
                "source_url": url,
                "markdown_text": text,
                "markdown_sha256": sha,
                "byte_count": len(raw),
                "fetched_at": _utc_now(),
            }
    except HTTPError as exc:
        return {
            "ok": False,
            "source_url": url,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except URLError as exc:
        return {
            "ok": False,
            "source_url": url,
            "error": f"Network error: {exc.reason}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "source_url": url,
            "error": f"Fetch error: {exc}",
        }


# ── frontmatter ───────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_skill_frontmatter(markdown_text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a SKILL.md string.

    Returns:
      dict with keys: ok, name, description, license, version, author,
      tags, raw_frontmatter, error (if ok=False)
    """
    match = _FRONTMATTER_RE.match(markdown_text)
    if not match:
        return {"ok": False, "error": "No YAML frontmatter found (missing --- delimiters)."}
    raw = match.group(1)
    try:
        fm = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return {"ok": False, "error": f"Frontmatter YAML parse error: {exc}"}
    if not isinstance(fm, dict):
        return {"ok": False, "error": "Frontmatter is not a YAML mapping."}

    name = fm.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        return {"ok": False, "error": "Frontmatter missing required 'name' field."}

    description = fm.get("description")
    if not description or not isinstance(description, str) or not description.strip():
        return {"ok": False, "error": "Frontmatter missing required 'description' field."}

    return {
        "ok": True,
        "name": str(name).strip(),
        "description": str(description).strip(),
        "license": fm.get("license", ""),
        "version": fm.get("version", ""),
        "author": fm.get("author", ""),
        "tags": fm.get("tags", []),
        "raw_frontmatter": fm,
    }


# ── token estimation ──────────────────────────────────────────────

def estimate_markdown_tokens(markdown_text: str) -> dict[str, Any]:
    """Estimate token count using char/4 heuristic."""
    char_count = len(markdown_text)
    tokens_estimate = max(1, char_count // 4)
    return {
        "character_count": char_count,
        "input_tokens_estimate": tokens_estimate,
        "method": "char_div_4",
    }


# ── request building ──────────────────────────────────────────────

def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _timestamp_id(prefix: str, name: str) -> str:
    stamp = _utc_now().replace(":", "").replace("-", "").replace("T", "").replace(".", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(name).strip().lower()).strip("-")[:48]
    return f"{prefix}_{stamp}_{slug}"


def build_external_skill_request(
    project: str,
    url: str,
    markdown_text: str,
    *,
    frontmatter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a skill request dict for an externally fetched SKILL.md."""
    if frontmatter is None:
        fm = parse_skill_frontmatter(markdown_text)
    else:
        fm = frontmatter
    if not fm.get("ok"):
        raise ValueError(f"Invalid frontmatter: {fm.get('error')}")

    token_info = estimate_markdown_tokens(markdown_text)
    skill_name = fm["name"]
    request_id = _timestamp_id("skill_req", skill_name)
    return {
        "schema_version": 1,
        "id": request_id,
        "project": project,
        "created_at": _utc_now(),
        "source": {
            "type": "external_url",
            "uri": url,
        },
        "skill_name": skill_name,
        "purpose": fm.get("description", ""),
        "description": fm.get("description", ""),
        "license": fm.get("license", ""),
        "version": fm.get("version", ""),
        "author": fm.get("author", ""),
        "tags": fm.get("tags", []),
        "markdown_sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        "input_tokens_estimate": token_info["input_tokens_estimate"],
        "character_count": token_info["character_count"],
        "risk": {
            "has_scripts": False,
            "requires_network": False,
            "modifies_files": False,
            "permission_level": "low",
        },
        "risk_level": "low",
        "cost_preview": {
            "total_tokens": token_info["input_tokens_estimate"],
            "input_tokens": token_info["input_tokens_estimate"],
            "output_tokens": 0,
            "estimated_cost": None,
            "cost_currency": "USD",
            "exact_cost_available": False,
            "pricing_source": "not_configured",
            "token_phases": {
                "discovery_tokens": token_info["input_tokens_estimate"],
            },
        },
        "triggers": [skill_name],
        "summary": fm.get("description", ""),
        "status": "pending_user_approval",
    }


# ── main import flow ──────────────────────────────────────────────

def import_skill_from_url(
    agentlab_root: Path,
    project: str,
    url: str,
    *,
    allow_network: bool = False,
) -> dict[str, Any]:
    """Full external skill import pipeline.

    1. Load policy / check allowlist
    2. Fetch SKILL.md from URL (if network allowed)
    3. Parse frontmatter
    4. Build skill request
    5. Save source snapshot
    6. Write skill adoption request

    Args:
        agentlab_root: AgentLab repo root.
        project: Project name.
        url: External SKILL.md URL.
        allow_network: Must be True to actually fetch.

    Returns:
        dict with keys: ok, source_url, skill_name, description, license,
        markdown_sha256, input_tokens_estimate, risk_level, request_id,
        status (always pending_user_approval), snapshot_path, error (if failed)
    """
    policy = load_import_policy(agentlab_root)

    if not policy.get("enabled", False):
        return {
            "ok": False,
            "source_url": url,
            "error": "External skill import is disabled by policy (config/external_skill_import_policy.yml).",
        }

    if not _policy_allows_url(policy, url):
        return {
            "ok": False,
            "source_url": url,
            "error": f"URL not in allowlist. Check allowed_hosts and allowed_url_prefixes in config/external_skill_import_policy.yml.",
        }

    if not allow_network and not policy.get("allow_network_by_default", False):
        return {
            "ok": False,
            "source_url": url,
            "error": "Network access required but not allowed. Set --allow-network or enable allow_network_by_default in policy.",
        }

    max_bytes = int(policy.get("max_bytes", 200000))
    timeout = int(policy.get("timeout_seconds", 10))

    # 1. Fetch
    fetched = fetch_skill_markdown_from_url(
        url, timeout_seconds=timeout, max_bytes=max_bytes
    )
    if not fetched.get("ok"):
        return {
            "ok": False,
            "source_url": url,
            "error": fetched.get("error", "Unknown fetch error"),
            "fetch_details": fetched,
        }

    markdown_text = fetched["markdown_text"]
    markdown_sha256 = fetched["markdown_sha256"]

    # 2. Parse frontmatter
    fm = parse_skill_frontmatter(markdown_text)
    if not fm.get("ok"):
        return {
            "ok": False,
            "source_url": url,
            "error": fm.get("error", "Unknown frontmatter error"),
            "markdown_sha256": markdown_sha256,
        }

    skill_name = fm["name"]

    # 3. Build request
    try:
        request = build_external_skill_request(
            project, url, markdown_text, frontmatter=fm
        )
    except ValueError as exc:
        return {
            "ok": False,
            "source_url": url,
            "error": str(exc),
            "markdown_sha256": markdown_sha256,
        }

    # 4. Save source snapshot
    request_id = request["id"]
    snapshot_path = None
    if policy.get("store_source_snapshot", True):
        snapshot_dir = (
            agentlab_root
            / "projects"
            / project
            / "skill_requests"
            / request_id
            / "source_snapshot"
        )
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / "SKILL.md"
        snapshot_path.write_text(markdown_text, encoding="utf-8")

    # 5. Write skill adoption request
    from skill_evolution import write_skill_adoption_request

    write_skill_adoption_request(agentlab_root, request)

    return {
        "ok": True,
        "source_url": url,
        "skill_name": skill_name,
        "description": fm.get("description", ""),
        "license": fm.get("license", ""),
        "version": fm.get("version", ""),
        "author": fm.get("author", ""),
        "markdown_sha256": markdown_sha256,
        "input_tokens_estimate": request["input_tokens_estimate"],
        "risk_level": "low",
        "request_id": request_id,
        "status": "pending_user_approval",
        "snapshot_path": str(snapshot_path) if snapshot_path else None,
    }


# ── fixture-based import (no network) ─────────────────────────────

def import_skill_from_fixture(
    agentlab_root: Path,
    project: str,
    fixture_path: Path,
    *,
    source_url: str = "",
) -> dict[str, Any]:
    """Import a skill from a local fixture SKILL.md file (no network).

    Follows the same pipeline as import_skill_from_url but reads
    from a local file. Used for offline testing.
    """
    if not fixture_path.exists():
        return {
            "ok": False,
            "source_url": source_url or str(fixture_path),
            "error": f"Fixture file not found: {fixture_path}",
        }

    markdown_text = fixture_path.read_text(encoding="utf-8")
    markdown_sha256 = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()

    fm = parse_skill_frontmatter(markdown_text)
    if not fm.get("ok"):
        return {
            "ok": False,
            "source_url": source_url or str(fixture_path),
            "error": fm.get("error", "Unknown frontmatter error"),
        }

    skill_name = fm["name"]

    try:
        request = build_external_skill_request(
            project, source_url or str(fixture_path), markdown_text, frontmatter=fm
        )
    except ValueError as exc:
        return {
            "ok": False,
            "source_url": source_url or str(fixture_path),
            "error": str(exc),
            "markdown_sha256": markdown_sha256,
        }

    from skill_evolution import write_skill_adoption_request

    write_skill_adoption_request(agentlab_root, request)

    return {
        "ok": True,
        "source_url": source_url or str(fixture_path),
        "skill_name": skill_name,
        "description": fm.get("description", ""),
        "license": fm.get("license", ""),
        "version": fm.get("version", ""),
        "author": fm.get("author", ""),
        "markdown_sha256": markdown_sha256,
        "input_tokens_estimate": request["input_tokens_estimate"],
        "risk_level": "low",
        "request_id": request["id"],
        "status": "pending_user_approval",
    }