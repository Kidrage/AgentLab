from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.config_inventory import build_config_inventory, config_inventory_payload
from agent_runtime.config_loader import load_yaml
from agent_runtime.routing.route_catalog import RouteCatalog


ROOT = Path(__file__).resolve().parents[1]


def test_route_catalog_loads_all_configured_routes() -> None:
    routing_config = load_yaml(ROOT / "config" / "routing_rules.yml")
    catalog = RouteCatalog.from_config(routing_config)

    for route_key in routing_config["routes"]:
        assert catalog.has_route(route_key), route_key
        assert catalog.agents_for(route_key), route_key
        assert catalog.size_for(route_key) in {"small", "medium", "large"}


def test_task_router_uses_route_catalog_without_behavior_change() -> None:
    from agent_runtime.task_router import recommend_route

    routing_config = load_yaml(ROOT / "config" / "routing_rules.yml")
    route = recommend_route("Implement a small CLI fix with tests.", routing_config=routing_config)

    assert route.route_key == "small_task"
    assert route.agents == RouteCatalog.from_config(routing_config).agents_for("small_task")


def test_config_loader_safely_ignores_non_mapping_yaml(tmp_path: Path) -> None:
    path = tmp_path / "list.yml"
    path.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")

    assert load_yaml(path) == {}


def test_config_inventory_classifies_cleanup_categories() -> None:
    items = build_config_inventory(ROOT)
    by_path = {item.path: item for item in items}

    assert by_path["config/routing_rules.yml"].category == "source"
    assert by_path["config/generalization_fixtures.yml"].category == "fixture"
    assert by_path["config/local_private_topology.example.yml"].category == "runtime"
    if "config/worker_performance_ledger.yml" in by_path:
        assert by_path["config/worker_performance_ledger.yml"].category == "runtime"


def test_config_inventory_payload_has_counts() -> None:
    payload = config_inventory_payload(ROOT)

    assert payload["schema_version"] == 1
    assert payload["counts"]["source"] > 0
    assert payload["counts"]["runtime"] > 0
