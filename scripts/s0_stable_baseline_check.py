#!/usr/bin/env python3
"""S0 stable baseline smoke check for AgentLab.

The check is deterministic and local-first: it imports key P0/P1/P2 modules and
checks CLI help without executing external agents, cloning repositories, making
network calls, or starting servers.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "agent_runtime"

for import_root in (ROOT, RUNTIME_ROOT):
    import_text = str(import_root)
    if import_text not in sys.path:
        sys.path.insert(0, import_text)


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


P0_MODULES = [
    "agent_runtime.costing.ledger",
    "agent_runtime.costing.budget",
    "agent_runtime.ingestion.repo_manifest",
    "agent_runtime.ingestion.clone_guard",
    "agent_runtime.ingestion.resource_ledger",
    "agent_runtime.artifact_contract",
    "agent_runtime.pipeline_runner",
]

P1_MODULES = [
    "agent_runtime.skills.registry",
    "agent_runtime.external_agents.handoff",
    "agent_runtime.external_agents.ecc_inventory",
    "agent_runtime.search.anysearch_adapter",
    "agent_runtime.search.local_url_reader",
    "agent_runtime.ingestion.repo_indexers.codegraph_adapter",
]

P2_MODULES = [
    "agent_runtime.review.three_e_reviewer",
    "agent_runtime.retry.retry_manager",
    "agent_runtime.governance.routing_feedback",
    "agent_runtime.context_governance.context_pack",
    "agent_runtime.recovery.failure_event",
    "agent_runtime.recovery.recovery_plan",
    "agent_runtime.recovery.closure_feedback",
    "agent_runtime.p2_closure.closure_runner",
]


def _import_check(module_name: str) -> CheckResult:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        return CheckResult(name=f"import:{module_name}", status="FAIL", detail=f"{type(exc).__name__}: {exc}")
    return CheckResult(name=f"import:{module_name}", status="PASS")


def _cli_check(args: list[str]) -> CheckResult:
    command = [str(ROOT / "agentlab.sh"), *args]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return CheckResult(name=f"cli:{' '.join(args)}", status="FAIL", detail=f"{type(exc).__name__}: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[:3]
        return CheckResult(name=f"cli:{' '.join(args)}", status="FAIL", detail=" | ".join(detail))
    return CheckResult(name=f"cli:{' '.join(args)}", status="PASS")


def run_checks() -> dict[str, Any]:
    checks: list[CheckResult] = []
    warnings: list[str] = []

    # This smoke is import-only for code modules and help-only for CLI entrypoints.
    # It intentionally avoids network calls, ECC execution, repository cloning,
    # MCP server startup, external tools, and lifecycle execution.

    for module_name in P0_MODULES + P1_MODULES + P2_MODULES:
        checks.append(_import_check(module_name))

    checks.append(_cli_check(["--help"]))
    checks.append(_cli_check(["run-pipeline", "--help"]))

    failed = [check for check in checks if check.status != "PASS"]
    return {
        "verdict": "PASS" if not failed else "FAIL",
        "checks": [check.as_dict() for check in checks],
        "warnings": warnings,
    }


def main() -> int:
    result = run_checks()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())