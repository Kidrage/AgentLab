"""Config inventory helpers for cleanup planning.

The inventory is intentionally conservative: it classifies config files by
where they should live in the long run, without moving or deleting anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from config_loader import CONFIG_FILES
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.config_loader import CONFIG_FILES


RUNTIME_CONFIG_NAMES = {
    "backup_policy.local.yml",
    "local_private_topology.example.yml",
    "worker_performance_ledger.yml",
    "test_external_agents.yml",
}

DERIVED_CONFIG_NAMES = {
    "config_ui_schema.yml",
    "shared_agent_directory.yml",
    "worker_performance_ledger.yml",
}

FIXTURE_CONFIG_NAMES = {
    "generalization_fixtures.yml",
}

CANONICAL_SOURCE_NAMES = set(CONFIG_FILES.values()) | {
    "agent_role_bindings.yml",
    "agent_role_requirements.yml",
    "artifact_task_policy.yml",
    "capability_provider_registry.yml",
    "capability_registry.yml",
    "capability_routing_policy.yml",
    "capability_schema.yml",
    "ci_gate_policy.yml",
    "domain_route_packs.yml",
    "project_routing.yml",
    "routing_rules.yml",
    "worker_capability_defaults.yml",
    "worker_fallback_policy.yml",
    "worker_invocation_contracts.yml",
}


@dataclass(frozen=True)
class ConfigInventoryItem:
    path: str
    category: str
    configured_loader_key: str | None
    cleanup_note: str


def build_config_inventory(agentlab_root: Path) -> list[ConfigInventoryItem]:
    """Return a sorted inventory of top-level config YAML files."""
    config_dir = agentlab_root / "config"
    loader_by_file = {filename: key for key, filename in CONFIG_FILES.items()}
    items: list[ConfigInventoryItem] = []
    for path in sorted(config_dir.glob("*.yml")):
        name = path.name
        category = _classify_config(name)
        items.append(
            ConfigInventoryItem(
                path=str(path.relative_to(agentlab_root)),
                category=category,
                configured_loader_key=loader_by_file.get(name),
                cleanup_note=_cleanup_note(name, category),
            )
        )
    return items


def render_config_inventory_markdown(items: list[ConfigInventoryItem]) -> str:
    lines = [
        "# Config Inventory",
        "",
        "| path | category | loader key | cleanup note |",
        "| --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(
            f"| `{item.path}` | {item.category} | {item.configured_loader_key or ''} | {item.cleanup_note} |"
        )
    lines.append("")
    return "\n".join(lines)


def config_inventory_payload(agentlab_root: Path) -> dict[str, Any]:
    items = build_config_inventory(agentlab_root)
    return {
        "schema_version": 1,
        "items": [asdict(item) for item in items],
        "counts": _counts_by_category(items),
    }


def _classify_config(name: str) -> str:
    if name in FIXTURE_CONFIG_NAMES:
        return "fixture"
    if name in RUNTIME_CONFIG_NAMES:
        return "runtime"
    if name in DERIVED_CONFIG_NAMES:
        return "derived"
    if name in CANONICAL_SOURCE_NAMES:
        return "source"
    return "unclassified"


def _cleanup_note(name: str, category: str) -> str:
    if category == "source":
        return "keep as hand-maintained source unless merged into a stronger authority"
    if category == "derived":
        return "prefer generating from source configs"
    if category == "runtime":
        return "prefer moving runtime/local state out of tracked config"
    if category == "fixture":
        return "keep only if tests treat it as a golden fixture"
    return f"classify owner before editing or deleting {name}"


def _counts_by_category(items: list[ConfigInventoryItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    return dict(sorted(counts.items()))
