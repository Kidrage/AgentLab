"""P2 Capability Map scanner: discover which P2 modules exist, their status, and callable entrypoints."""
from __future__ import annotations

import importlib
import pkgutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml

ROOT = Path(__file__).resolve().parents[2]

P2_MODULES = {
    "review": {
        "module_dir": "agent_runtime/review",
        "test_fixtures": ["tests/fixtures/p2_review"],
        "expected_entrypoints": ["run_three_e_review", "ReviewTarget", "ReviewVerdict"],
    },
    "retry_loop": {
        "module_dir": "agent_runtime/retry",
        "test_fixtures": ["tests/fixtures/p2_retry_loop"],
        "expected_entrypoints": ["run_acceptance_retry_loop", "RetryLoopState", "RetryPolicy"],
    },
    "executor_router": {
        "module_dir": "agent_runtime/executors",
        "test_fixtures": ["tests/fixtures/p2_executor_router"],
        "expected_entrypoints": ["route_execution_request", "ExecutionRequest", "ExecutorProvider"],
    },
    "provider_governance": {
        "module_dir": "agent_runtime/governance",
        "test_fixtures": ["tests/fixtures/p2_provider_governance"],
        "expected_entrypoints": ["build_provider_performance_profiles", "derive_governance_decisions", "ProviderPerformanceProfile"],
    },
    "router_update": {
        "module_dir": "agent_runtime/router_update",
        "test_fixtures": ["tests/fixtures/p2_router_update"],
        "expected_entrypoints": ["build_router_policy_patch", "apply_router_policy_patch", "RouterPatchResult"],
    },
    "external_agents": {
        "module_dir": "agent_runtime/external_agents",
        "test_fixtures": [],
        "expected_entrypoints": ["ExternalHandoff", "ExternalResult", "scan_ecc_inventory"],
    },
    "external_skills": {
        "module_dir": "agent_runtime/skills",
        "test_fixtures": [],
        "expected_entrypoints": ["load_skill_registry", "propose_internal_skill_candidates"],
    },
}

CONFIG_FILES = [
    "config/review_policy.yml",
    "config/retry_policy.yml",
    "config/executor_router.yml",
    "config/provider_governance.yml",
    "config/router_update_policy.yml",
]

SCRIPTS = [
    "scripts/p2_review_check.py",
    "scripts/p2_retry_loop_check.py",
    "scripts/p2_executor_router_check.py",
    "scripts/p2_provider_governance_check.py",
    "scripts/p2_router_update_check.py",
]


def scan_p2_capabilities(base_ref: str = "p1-p2-stable-base") -> dict[str, Any]:
    """Scan all known P2 modules and produce a capability map dict."""
    capabilities: dict[str, Any] = {}
    gaps: list[dict[str, Any]] = []
    recommendations: list[str] = []

    for cap_name, info in P2_MODULES.items():
        module_dir = ROOT / info["module_dir"]
        dir_exists = module_dir.is_dir()

        # Check if directory has Python files
        py_files = list(module_dir.glob("*.py")) if dir_exists else []
        has_code = len(py_files) > 0

        # Check importability without side effects
        importable = False
        if has_code:
            import_path = info["module_dir"].replace("/", ".")
            try:
                mod = importlib.import_module(import_path)
                importable = mod is not None
            except Exception:
                importable = False

        # Check for callable entrypoints
        callable_eps = []
        if importable:
            mod = sys.modules.get(info["module_dir"].replace("/", "."))
            if mod:
                for ep_name in info["expected_entrypoints"]:
                    if hasattr(mod, ep_name) or _find_in_submodules(mod, ep_name, info["module_dir"]):
                        callable_eps.append(ep_name)

        # Determine status
        if dir_exists and has_code and callable_eps:
            status = "implemented"
        elif dir_exists and has_code:
            status = "implemented_or_partial"
        elif dir_exists:
            status = "scaffold"
        else:
            status = "missing"

        # Check test fixtures
        test_paths = []
        for tf in info["test_fixtures"]:
            if (ROOT / tf).is_dir():
                test_paths.append(tf)

        # Check CLI wiring
        cli_wired = False
        for script in SCRIPTS:
            if (ROOT / script).exists():
                # Map script to capability
                if cap_name == "review" and "review" in script:
                    cli_wired = True
                elif cap_name == "retry_loop" and "retry" in script:
                    cli_wired = True
                elif cap_name == "executor_router" and "executor" in script:
                    cli_wired = True
                elif cap_name == "provider_governance" and "governance" in script:
                    cli_wired = True
                elif cap_name == "router_update" and "router_update" in script:
                    cli_wired = True

        # Check configs
        configs = []
        for cf in CONFIG_FILES:
            if cap_name in cf and (ROOT / cf).exists():
                configs.append(cf)

        capabilities[cap_name] = {
            "status": status,
            "module_paths": [info["module_dir"]] if dir_exists else [],
            "tests": test_paths,
            "callable_entrypoints": callable_eps,
            "cli_wired": cli_wired,
            "configs": configs,
            "notes": _generate_notes(cap_name, status, dir_exists, has_code, callable_eps, cli_wired),
        }

        if status in ("missing", "scaffold"):
            gaps.append({
                "id": f"missing_{cap_name}",
                "severity": "high" if status == "missing" else "medium",
                "description": f"P2 module {cap_name} is {status}.",
            })

    # Check for closure orchestration gap
    closure_dir = ROOT / "agent_runtime/p2_closure"
    if not closure_dir.is_dir() or not list(closure_dir.glob("closure_runner.py")):
        gaps.append({
            "id": "missing_closure_orchestration",
            "severity": "medium",
            "description": "P2 modules exist but are not yet orchestrated into one closure workflow.",
        })
        recommendations.append("Add P2 closure runner that calls existing modules and writes evidence artifacts.")

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_ref": base_ref,
        "capabilities": capabilities,
        "gaps": gaps,
        "recommendations": recommendations,
    }


def write_capability_map(capability_map: dict[str, Any], output_path: Path) -> Path:
    """Write capability map to YAML."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_path, capability_map)
    return output_path


def _find_in_submodules(mod: Any, name: str, base_path: str) -> bool:
    """Check if name exists in any submodule of mod."""
    try:
        for _, mod_name, _ in pkgutil.walk_packages(mod.__path__, mod.__name__ + "."):
            try:
                submod = importlib.import_module(mod_name)
                if hasattr(submod, name):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _generate_notes(
    cap_name: str,
    status: str,
    dir_exists: bool,
    has_code: bool,
    callable_eps: list[str],
    cli_wired: bool,
) -> list[str]:
    notes: list[str] = []
    if status == "implemented" and not cli_wired:
        notes.append(f"Module implemented but not wired as CLI subcommand in run_task.py.")
    if not callable_eps and has_code:
        notes.append("Entry points not verified via import.")
    if cap_name == "retry_loop" and len(callable_eps) < 3:
        notes.append("May need closure adapter if direct callable API missing.")
    return notes
