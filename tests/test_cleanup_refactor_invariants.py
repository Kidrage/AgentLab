from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.config_inventory import build_config_inventory, config_inventory_payload
from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
from agent_runtime.config_loader import load_agentlab_configs, load_yaml
from agent_runtime.routing.route_catalog import (
    ROUTE_SIZE_MAP,
    RouteCatalog,
    route_size_suffix,
)
from agent_runtime.task_purge import generate_project_documentation
from agent_runtime.workspace_scanner import run_workspace_scan

LEGACY_COMPATIBILITY_ROUTES = {"fiction_chapter_pipeline"}


def test_retired_full_driver_prompts_are_not_active_templates() -> None:
    assert not (ROOT / "agent_templates" / "codex_full_driver").exists()
    archive = ROOT / "docs" / "archive" / "codex_full_driver_legacy_20260718"
    assert (archive / "README.md").exists()
    assert (archive / "templates" / "01_SUPERVISOR.md").exists()


def test_project_specific_production_scripts_are_archive_only() -> None:
    assert not (ROOT / "scripts" / "write_chapters.py").exists()
    assert not (ROOT / "scripts" / "reader_server.py").exists()

    archive = ROOT / "docs" / "archive" / "legacy_production_scripts_20260718"
    assert (archive / "README.md").exists()
    assert (archive / "write_chapters.py").exists()
    assert (archive / "reader_server.py").exists()


def test_dead_role_and_aider_plan_registries_are_removed() -> None:
    assert not (ROOT / "agent_runtime" / "agents_def.py").exists()
    assert not (ROOT / "agent_runtime" / "aider_adapter.py").exists()
    contracts = safe_read_yaml(ROOT / "config" / "worker_invocation_contracts.yml")
    bindings = safe_read_yaml(ROOT / "config" / "agent_role_bindings.yml")
    assert "aider" in contracts["contracts"]
    assert "Coder" in bindings["workers"]["aider"]["allowed_roles"]


def test_web_ui_fallback_does_not_publish_a_legacy_agent_chain() -> None:
    app = (ROOT / "web_ui" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web_ui" / "index.html").read_text(encoding="utf-8")
    sample = (ROOT / "web_ui" / "agent_status.sample.json").read_text(
        encoding="utf-8"
    )
    surface = app + index + sample
    assert "CodexPromptGenerator" not in surface
    assert "newTaskBackend" not in surface
    assert "switchBrainModel" not in surface
    assert "switchExecModel" not in surface


def test_every_active_agent_template_is_registered() -> None:
    registry = safe_read_yaml(ROOT / "config" / "agent_registry.yml")["agents"]
    registered = set()
    for contract in registry.values():
        registered.add(Path(contract["template_path"]).name)
        registered.update(
            Path(path).name
            for path in (contract.get("template_variants", {}) or {}).values()
        )

    active = {path.name for path in (ROOT / "agent_templates").glob("*.md")}
    assert active == registered


def test_project_memory_contract_has_no_writable_legacy_handoff_or_host_log() -> None:
    project_memory = safe_read_yaml(ROOT / "config" / "memory_policy.yml")[
        "records"
    ]["project_memory"]

    assert "HandOff.md" not in project_memory
    assert "08_CODEX_DIALOGUE_LOG.md" not in project_memory
    assert "08_WORKER_DIALOGUE_LOG.md" in project_memory


def test_task_purge_docs_do_not_claim_a_retired_agent_or_fixed_code_route(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_0001"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("# Draft an article\n", encoding="utf-8")
    (run_dir / "state.yml").write_text(
        "status: completed\nroute:\n  - Supervisor\n  - ArtifactProducer\n",
        encoding="utf-8",
    )

    generate_project_documentation(tmp_path, "Demo")

    guide = (tmp_path / "projects" / "Demo" / "docs" / "usage_guide.md").read_text(
        encoding="utf-8"
    )
    changelog = (tmp_path / "projects" / "Demo" / "docs" / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    assert "DocManager" not in guide + changelog
    assert "--project Demo" in guide
    assert "run-agent Coder" not in guide
    assert "run-pipeline" in guide


def test_active_guides_use_the_real_repository_hygiene_option() -> None:
    guides = [
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "USAGE_PLAN.md",
        ROOT / "docs" / "README.en-US.md",
        ROOT / "docs" / "README.zh-CN.md",
        ROOT / "docs" / "CURRENT_VERSION_CAPABILITIES.en-US.md",
        ROOT / "docs" / "CURRENT_VERSION_CAPABILITIES.zh-CN.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in guides)

    assert "repo-hygiene-check --repo" not in combined
    assert "repo-hygiene-check --root" in combined


def test_route_catalog_uses_routing_config_as_its_only_route_authority() -> None:
    routing_config = load_yaml(ROOT / "config" / "routing_rules.yml")
    catalog = RouteCatalog.from_config(routing_config)

    assert RouteCatalog.from_config().routes == routing_config["routes"]
    for route_key, configured in routing_config["routes"].items():
        assert "role_session_contracts" not in configured, route_key
        assert catalog.has_route(route_key), route_key
        assert catalog.agents_for(route_key) == configured.get("agents"), route_key
        assert catalog.size_for(route_key) == ROUTE_SIZE_MAP[str(configured.get("size"))]
        if "Coder" in configured.get("agents", []):
            assert "TesterAuditor" in configured["agents"], route_key


def test_legacy_compatibility_routes_are_explicitly_non_default() -> None:
    routing_config = load_yaml(ROOT / "config" / "routing_rules.yml")
    catalog = RouteCatalog.from_config(routing_config)

    for route_key in LEGACY_COMPATIBILITY_ROUTES:
        configured = routing_config["routes"][route_key]
        assert configured["status"] == "legacy_compatibility"
        assert configured["default_selectable"] is False
        assert catalog.has_configured_route(route_key), route_key
        assert catalog.agents_for(route_key) == configured["agents"], route_key


def test_task_router_uses_route_catalog_without_behavior_change() -> None:
    from agent_runtime.task_router import recommend_route

    routing_config = load_yaml(ROOT / "config" / "routing_rules.yml")
    route = recommend_route("Implement a small CLI fix with tests.", routing_config=routing_config)

    assert route.route_key == "small_task"
    assert route.agents == RouteCatalog.from_config(routing_config).agents_for("small_task")


def test_workspace_scan_uses_configured_deterministic_route_without_fake_agents(tmp_path: Path) -> None:
    target = tmp_path / "workspace"
    target.mkdir()
    (target / "README.md").write_text("# Demo\n", encoding="utf-8")
    agentlab_root = tmp_path / "agentlab"

    result = run_workspace_scan(
        agentlab_root,
        "WorkspaceDemo",
        "scan_001",
        target,
        max_depth=2,
    )

    run_dir = Path(result["run_dir"])
    assert result["artifact_check"]["valid"] is True, result["artifact_check"]
    workflow_plan = safe_read_yaml(run_dir / "workflow_plan.yml")
    route = workflow_plan["route"]
    expected_agents = RouteCatalog.from_config().agents_for("workspace_analysis_task")
    assert route["route_key"] == "workspace_analysis_task"
    assert route["agents"] == expected_agents == ["Supervisor", "RepoScout"]
    assert safe_read_yaml(run_dir / "state.yml")["completed_agents"] == expected_agents
    assert not (run_dir / "06_implementation_report.md").exists()
    assert not (run_dir / "09_archive_update.md").exists()

    lifecycle = safe_read_yaml(run_dir / "lifecycle.yml")
    assert lifecycle["nodes"]["CODER_IMPLEMENTATION"]["status"] == "skipped"
    assert lifecycle["nodes"]["ARCHIVE"]["status"] == "skipped"


def test_route_size_suffix_uses_canonical_route_catalog_mapping() -> None:
    assert route_size_suffix("small") == "L1"
    assert route_size_suffix("medium") == "L2"
    assert route_size_suffix("large") == "L3"
    assert route_size_suffix("unknown") == "L2"


def test_config_loader_safely_ignores_non_mapping_yaml(tmp_path: Path) -> None:
    path = tmp_path / "list.yml"
    path.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")

    assert load_yaml(path) == {}


def test_config_loader_reads_only_declared_dependencies() -> None:
    loaded = load_agentlab_configs(
        ROOT,
        keys=("routing_rules", "production_packs", "routing_rules"),
    )

    assert list(loaded) == ["routing_rules", "production_packs"]
    with pytest.raises(KeyError, match="unknown AgentLab config keys: retired_policy"):
        load_agentlab_configs(ROOT, keys=("retired_policy",))


def test_config_loader_cache_refreshes_and_returns_isolated_values(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("nested:\n  value: first\n", encoding="utf-8")

    first = load_yaml(path)
    first["nested"]["value"] = "mutated"
    assert load_yaml(path)["nested"]["value"] == "first"

    path.write_text("nested:\n  value: second-version\n", encoding="utf-8")
    assert load_yaml(path)["nested"]["value"] == "second-version"


def test_safe_yaml_cache_refreshes_and_returns_isolated_values(tmp_path: Path) -> None:
    path = tmp_path / "state.yml"
    path.write_text("nested:\n  value: first\n", encoding="utf-8")

    first = safe_read_yaml(path)
    first["nested"]["value"] = "mutated"
    assert safe_read_yaml(path)["nested"]["value"] == "first"

    # Keep the serialized size constant so timestamp/inode metadata must invalidate.
    path.write_text("nested:\n  value: later\n", encoding="utf-8")
    assert safe_read_yaml(path)["nested"]["value"] == "later"

    atomic_write_yaml(path, {"nested": {"value": "atomic"}})
    assert safe_read_yaml(path)["nested"]["value"] == "atomic"


def test_safe_yaml_missing_default_is_isolated(tmp_path: Path) -> None:
    default = {"items": []}

    first = safe_read_yaml(tmp_path / "missing.yml", default=default)
    first["items"].append("mutated")

    assert default == {"items": []}
    assert safe_read_yaml(tmp_path / "missing.yml", default=default) == {"items": []}


def test_config_inventory_classifies_cleanup_categories_and_counts() -> None:
    payload = config_inventory_payload(ROOT)
    by_path = {item["path"]: item for item in payload["items"]}

    assert by_path["config/routing_rules.yml"]["category"] == "source"
    assert by_path["config/generalization_fixtures.yml"]["category"] == "fixture"
    assert by_path["config/local_private_topology.example.yml"]["category"] == "runtime"
    assert not [item for item in payload["items"] if item["category"] == "unclassified"]
    assert payload["schema_version"] == 1
    assert payload["counts"]["source"] > 0
    assert payload["counts"]["runtime"] > 0


def test_config_inventory_ignores_private_runtime_trees(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    source_dir = tmp_path / "agent_runtime"
    private_dir = source_dir / ".venv" / "lib"
    config_dir.mkdir()
    private_dir.mkdir(parents=True)
    (config_dir / "unowned.yml").write_text("enabled: true\n", encoding="utf-8")
    (private_dir / "dependency.py").write_text('CONFIG = "unowned.yml"\n', encoding="utf-8")

    by_name = {item.path: item for item in build_config_inventory(tmp_path)}
    assert by_name["config/unowned.yml"].category == "unclassified"

    (source_dir / "component.py").write_text('CONFIG = "unowned.yml"\n', encoding="utf-8")
    by_name = {item.path: item for item in build_config_inventory(tmp_path)}
    assert by_name["config/unowned.yml"].category == "direct_source"


def test_suite_has_no_exact_duplicate_test_implementations() -> None:
    implementations: dict[str, list[str]] = defaultdict(list)
    test_root = ROOT / "tests"

    for path in sorted(test_root.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                candidates.append(node)
            elif isinstance(node, ast.ClassDef):
                candidates.extend(
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )

        for node in candidates:
            if not node.name.startswith("test_"):
                continue
            normalized = ast.FunctionDef(
                name="test_normalized",
                args=node.args,
                body=node.body,
                decorator_list=node.decorator_list,
                returns=node.returns,
                type_comment=node.type_comment,
            )
            fingerprint = ast.dump(normalized, include_attributes=False)
            implementations[fingerprint].append(f"{path.name}:{node.lineno}:{node.name}")

    duplicates = [locations for locations in implementations.values() if len(locations) > 1]
    assert duplicates == [], duplicates
