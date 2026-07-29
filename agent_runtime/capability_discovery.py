"""Metadata-only capability discovery adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import json
import os
import re

import yaml

_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CapabilityDiscoveryError(ValueError):
    """Raised when a discovery source returns an invalid contract."""


def _candidate(
    *,
    candidate_id: str,
    source_kind: str,
    package_type: str,
    name: str,
    description: str,
    source_locator: str,
    version: str | None,
    license_id: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "capability-candidate/v1",
        "candidate_id": candidate_id,
        "source_kind": source_kind,
        "package_type": package_type,
        "name": name,
        "description": description,
        "source_locator": source_locator,
        "version": version,
        "license": license_id,
        "lifecycle_status": "quarantined",
        "install_allowed": False,
        "promotion_evidence_eligible": False,
    }


def _skill_frontmatter(path: Path) -> dict[str, Any]:
    lines: list[str] = []
    try:
        with path.open(encoding="utf-8") as handle:
            if handle.readline().strip() != "---":
                raise CapabilityDiscoveryError(f"missing SKILL.md frontmatter: {path}")
            for line in handle:
                if line.strip() == "---":
                    break
                lines.append(line)
            else:
                raise CapabilityDiscoveryError(
                    f"unterminated SKILL.md frontmatter: {path}"
                )
    except (OSError, UnicodeError) as exc:
        raise CapabilityDiscoveryError(f"cannot read SKILL.md metadata: {path}") from exc
    try:
        value = yaml.safe_load("".join(lines)) or {}
    except yaml.YAMLError as exc:
        raise CapabilityDiscoveryError(f"invalid SKILL.md frontmatter: {path}") from exc
    if not isinstance(value, dict):
        raise CapabilityDiscoveryError(f"SKILL.md frontmatter must be a mapping: {path}")
    return value


class LocalAgentSkillsAdapter:
    """Discover Agent Skills by reading only SKILL.md frontmatter."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def search(self, query: str) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        needle = query.casefold().strip()
        candidates: list[dict[str, Any]] = []
        for skill_dir in sorted(self.root.iterdir()):
            skill_path = skill_dir / "SKILL.md"
            if skill_dir.is_symlink() or not skill_dir.is_dir() or not skill_path.is_file():
                continue
            try:
                metadata = _skill_frontmatter(skill_path)
            except CapabilityDiscoveryError:
                continue
            name = str(metadata.get("name") or "")
            description = str(metadata.get("description") or "")
            if (
                not _SKILL_NAME.fullmatch(name)
                or name != skill_dir.name
                or not description
                or len(description) > 1024
            ):
                continue
            if needle and needle not in f"{name} {description}".casefold():
                continue
            candidate = _candidate(
                candidate_id=f"local-skill:{name}",
                source_kind="agent_skills_local",
                package_type="skill",
                name=name,
                description=description,
                source_locator=str(skill_dir),
                version=str((metadata.get("metadata") or {}).get("version") or "")
                or None,
                license_id=str(metadata.get("license") or "") or None,
            )
            candidate.update(
                {
                    "compatibility": metadata.get("compatibility"),
                    "allowed_tools_declared": metadata.get("allowed-tools"),
                    "contains_code": (skill_dir / "scripts").is_dir(),
                    "progressive_disclosure": {
                        "metadata_loaded": True,
                        "instructions_loaded": False,
                        "resources_loaded": False,
                    },
                }
            )
            candidates.append(candidate)
        return candidates


JsonGetter = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


def _http_get_json(url: str, headers: Mapping[str, str]) -> Mapping[str, Any]:
    request = Request(url, headers=dict(headers))
    with urlopen(request, timeout=15) as response:  # nosec B310 - fixed HTTPS adapters
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, Mapping):
        raise CapabilityDiscoveryError("discovery response must be a mapping")
    return value


class McpRegistrySourceAdapter:
    """Consume official MCP Registry metadata without trusting or installing it."""

    endpoint = "https://registry.modelcontextprotocol.io/v0.1/servers"

    def __init__(self, getter: JsonGetter | None = None) -> None:
        self.getter = getter or _http_get_json

    def search(self, query: str) -> list[dict[str, Any]]:
        payload = self.getter(
            f"{self.endpoint}?search={quote_plus(query)}&limit=20",
            {"Accept": "application/json"},
        )
        return self.parse(payload)

    @staticmethod
    def parse(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        servers = payload.get("servers")
        if not isinstance(servers, list):
            raise CapabilityDiscoveryError("MCP Registry response has no servers list")
        candidates: list[dict[str, Any]] = []
        for raw in servers:
            if not isinstance(raw, Mapping):
                continue
            server = raw.get("server") if isinstance(raw.get("server"), Mapping) else raw
            name = str(server.get("name") or "")
            if not name:
                continue
            repository = (
                server.get("repository")
                if isinstance(server.get("repository"), Mapping)
                else {}
            )
            packages = server.get("packages") if isinstance(server.get("packages"), list) else []
            locator = str(repository.get("url") or "")
            if not locator and packages and isinstance(packages[0], Mapping):
                locator = (
                    f"{packages[0].get('registryType')}:"
                    f"{packages[0].get('identifier')}"
                )
            candidate = _candidate(
                candidate_id=f"mcp-registry:{name}:{server.get('version') or 'unknown'}",
                source_kind="mcp_registry",
                package_type="mcp_server",
                name=name,
                description=str(server.get("description") or ""),
                source_locator=locator,
                version=str(server.get("version") or "") or None,
                license_id=None,
            )
            declared = server.get("_meta") if isinstance(server.get("_meta"), Mapping) else {}
            candidate.update(
                {
                    "registry_metadata_only": True,
                    "annotations_trusted": False,
                    "declared_annotations": declared.get("tool_annotations"),
                    "effective_risk": {
                        "read_only": False,
                        "destructive": True,
                        "idempotent": False,
                        "open_world": True,
                    },
                    "packages": packages,
                    "remotes": server.get("remotes") or [],
                }
            )
            candidates.append(candidate)
        return candidates


class GitHubSourceAdapter:
    """Use GitHub popularity only to order discovery, never to promote."""

    endpoint = "https://api.github.com/search/repositories"

    def __init__(self, getter: JsonGetter | None = None) -> None:
        self.getter = getter or _http_get_json

    def search(self, query: str) -> list[dict[str, Any]]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = self.getter(
            f"{self.endpoint}?q={quote_plus(query)}&sort=stars&order=desc&per_page=50",
            headers,
        )
        return self.parse(payload)

    @staticmethod
    def parse(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items")
        if not isinstance(items, list):
            raise CapabilityDiscoveryError("GitHub response has no items list")
        candidates: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping) or not item.get("full_name"):
                continue
            license_info = item.get("license") if isinstance(item.get("license"), Mapping) else {}
            name = str(item["full_name"])
            candidate = _candidate(
                candidate_id=f"github:{name}",
                source_kind="github",
                package_type="plugin_bundle",
                name=name,
                description=str(item.get("description") or ""),
                source_locator=str(item.get("html_url") or ""),
                version=str(item.get("default_branch") or "") or None,
                license_id=str(license_info.get("spdx_id") or "") or None,
            )
            candidate["discovery_signals"] = {
                "stars": int(item.get("stargazers_count") or 0),
            }
            candidates.append(candidate)
        return candidates
