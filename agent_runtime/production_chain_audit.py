"""Production-chain audit for AgentLab task archetypes."""

from __future__ import annotations

from dataclasses import dataclass
import tempfile
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChainScenario:
    scenario_id: str
    project: str
    request: str
    expected_pack: str
    expected_agents: tuple[str, ...]
    forbidden_agents: tuple[str, ...] = ()
    forbidden_effective_lifecycle_nodes: tuple[str, ...] = ()


LIFECYCLE_NODE_AGENT = {
    "SUPERVISOR_PLAN": "Supervisor",
    "REPO_CONTEXT": "RepoScout",
    "RESEARCH_OPTIONAL": "Researcher",
    "INTERFACE_OPTIONAL": "InterfaceMapper",
    "CODER_IMPLEMENTATION": "Coder",
    "ARTIFACT_PRODUCTION": "ArtifactProducer",
    "WRITER_DRAFT": "Writer",
    "FICTION_REVIEW": "Reviewer",
    "SCRIBE_LEDGER": "Scribe",
    "VALIDATION": "TesterAuditor",
    "AUDIT": "TesterAuditor",
    "VERIFY": "Verifier",
    "ARCHIVE": "Archivist",
}


SCENARIOS = [
    ChainScenario(
        scenario_id="code_factory_web_ui",
        project="AgentLab",
        request="Implement an AgentLab web UI status dashboard and app shell.",
        expected_pack="code_factory",
        expected_agents=("Supervisor", "Coder", "Verifier"),
        forbidden_agents=(),
    ),
    ChainScenario(
        scenario_id="narrative_light_chapter",
        project="Crown_of_Ash",
        request="写 Crown 第 1 章。",
        expected_pack="narrative_longform",
        expected_agents=("Supervisor", "Writer"),
        forbidden_agents=("Coder", "ArtifactProducer"),
    ),
    ChainScenario(
        scenario_id="article_light_draft",
        project="AgentLab",
        request="写一篇产品说明文章。",
        expected_pack="article_light",
        expected_agents=("Supervisor", "ArtifactProducer"),
        forbidden_agents=("Coder", "RepoScout", "InterfaceMapper"),
    ),
    ChainScenario(
        scenario_id="narrative_heavy_audit",
        project="Crown_of_Ash",
        request="审计 Crown 前 10 章的连续性、人物状态和时间线。",
        expected_pack="narrative_longform",
        expected_agents=("Supervisor", "Reviewer", "Scribe", "Verifier"),
        forbidden_agents=("Coder", "Writer", "ArtifactProducer"),
        forbidden_effective_lifecycle_nodes=("WRITER_DRAFT",),
    ),
    ChainScenario(
        scenario_id="media_series_production",
        project="Crown_of_Ash",
        request="把 Crown of Ash 第一卷做成连续漫画、短视频和海报图册，需要保持角色视觉、场景资产和镜头连续性。",
        expected_pack="media_series_production",
        expected_agents=("Supervisor", "ArtifactProducer", "Verifier"),
        forbidden_agents=("Coder", "Archivist"),
    ),
    ChainScenario(
        scenario_id="unknown_non_code_pack_synthesis",
        project="AgentLab",
        request="设计一个沉浸式气味剧场装置生产流程，需要观众动线、气味提示和安全验收。",
        expected_pack="pack_synthesis_candidate",
        expected_agents=("Supervisor", "Researcher", "ArtifactProducer", "Verifier"),
        forbidden_agents=("Coder", "RepoScout", "InterfaceMapper"),
    ),
]


def _task_state(plan: Any) -> list[str]:
    return list(plan.memory_policy.get("records", {}).get("task_state", []) or [])


def _required_io(plan: Any) -> list[str]:
    values: list[str] = []
    for config in plan.included_agents.values():
        values.extend(str(item) for item in config.get("required_inputs", []) or [])
        values.extend(str(item) for item in config.get("required_outputs", []) or [])
    return values


def _code_shell_hits(plan: Any) -> list[str]:
    text = "\n".join(_required_io(plan) + _task_state(plan) + [str(gate) for gate in plan.validation_gates])
    forbidden = ["implementation_report", "interface_map", "05_coder_prompt", "01_REPO_MAP", "reposcout"]
    return [item for item in forbidden if item in text]


def _effective_lifecycle_nodes(pack: dict[str, Any], route_agents: list[str]) -> list[str]:
    route_agent_set = set(route_agents)
    effective: list[str] = []
    for node in pack.get("lifecycle_nodes") or []:
        node_id = str(node)
        owner = LIFECYCLE_NODE_AGENT.get(node_id)
        if owner and owner not in route_agent_set:
            continue
        effective.append(node_id)
    return effective


def _agent_lifecycle_coverage(route_agents: list[str], effective_lifecycle_nodes: list[str]) -> dict[str, Any]:
    node_owners: dict[str, list[str]] = {}
    for node in effective_lifecycle_nodes:
        owner = LIFECYCLE_NODE_AGENT.get(str(node))
        if not owner:
            continue
        node_owners.setdefault(owner, []).append(str(node))
    coverage = {
        agent: node_owners.get(agent, [])
        for agent in route_agents
    }
    missing_agents = [agent for agent, nodes in coverage.items() if not nodes]
    return {
        "status": "pass" if not missing_agents else "fail",
        "coverage": coverage,
        "missing_agents": missing_agents,
    }


def _state_governance_issues(plan: Any) -> list[str]:
    pack = plan.production_pack or {}
    artifact_intent = plan.artifact_intent if isinstance(plan.artifact_intent, dict) else {}
    task_state = _task_state(plan)
    issues: list[str] = []
    if not pack.get("lifecycle_nodes"):
        issues.append("production pack has no lifecycle_nodes")
    if not pack.get("memory_contract"):
        issues.append("production pack has no memory_contract")
    elif not task_state:
        issues.append("workflow memory_policy has no task_state records")
    if not pack.get("quality_gates"):
        issues.append("production pack has no quality_gates")
    if not artifact_intent:
        issues.append("artifact_intent is missing")
    else:
        for key in ("candidate_dir", "production_dir", "archive_strategy", "rules"):
            if not artifact_intent.get(key):
                issues.append(f"artifact_intent missing {key}")
    return issues


def _summarize_plan(plan: Any, scenario: ChainScenario) -> dict[str, Any]:
    agents = list(plan.route.agents)
    pack = plan.production_pack or {}
    pack_id = pack.get("pack_id")
    missing_agents = [agent for agent in scenario.expected_agents if agent not in agents]
    unexpected_agents = [agent for agent in scenario.forbidden_agents if agent in agents]
    code_shell_hits = _code_shell_hits(plan)
    governance_issues = _state_governance_issues(plan)
    effective_lifecycle_nodes = _effective_lifecycle_nodes(pack, agents)
    agent_lifecycle_coverage = _agent_lifecycle_coverage(agents, effective_lifecycle_nodes)
    forbidden_effective_nodes = [
        node for node in scenario.forbidden_effective_lifecycle_nodes if node in effective_lifecycle_nodes
    ]
    if pack_id == "code_factory":
        code_shell_hits = []
    elif pack.get("status") == "synthesis_candidate":
        code_shell_hits = [hit for hit in code_shell_hits if hit not in {"implementation_report", "interface_map", "05_coder_prompt", "01_REPO_MAP", "reposcout"}]
    status = "pass"
    issues: list[str] = []
    if pack_id != scenario.expected_pack:
        status = "fail"
        issues.append(f"expected pack {scenario.expected_pack}, got {pack_id}")
    if missing_agents:
        status = "fail"
        issues.append(f"missing expected agents: {', '.join(missing_agents)}")
    if unexpected_agents:
        status = "fail"
        issues.append(f"forbidden agents present: {', '.join(unexpected_agents)}")
    if code_shell_hits and pack_id != "code_factory":
        status = "fail"
        issues.append(f"non-code active contract contains code-shell terms: {', '.join(code_shell_hits)}")
    if governance_issues:
        status = "fail"
        issues.extend(governance_issues)
    if agent_lifecycle_coverage["status"] != "pass":
        status = "fail"
        issues.append(
            "route agents without effective lifecycle nodes: "
            + ", ".join(agent_lifecycle_coverage["missing_agents"])
        )
    if forbidden_effective_nodes:
        status = "fail"
        issues.append(
            "forbidden effective lifecycle nodes present: "
            + ", ".join(forbidden_effective_nodes)
        )
    return {
        "scenario_id": scenario.scenario_id,
        "status": status,
        "project": scenario.project,
        "request": scenario.request,
        "route_key": plan.route.route_key,
        "agents": agents,
        "skipped_agents": list(plan.route.skipped_agents or []),
        "production_pack": {
            "pack_id": pack_id,
            "status": pack.get("status"),
            "task_domain": pack.get("task_domain"),
            "lifecycle_nodes": pack.get("lifecycle_nodes", []),
            "effective_lifecycle_nodes": effective_lifecycle_nodes,
            "inactive_route_lifecycle_nodes": [
                str(node)
                for node in pack.get("lifecycle_nodes") or []
                if str(node) not in effective_lifecycle_nodes
            ],
            "required_outputs": pack.get("required_outputs", []),
            "memory_contract": pack.get("memory_contract", []),
            "quality_gates": pack.get("quality_gates", []),
        },
        "state_governance": {
            "status": "pass" if not governance_issues else "fail",
            "has_lifecycle_nodes": bool(pack.get("lifecycle_nodes")),
            "has_memory_contract": bool(pack.get("memory_contract")),
            "has_task_state_records": bool(_task_state(plan)),
            "has_quality_gates": bool(pack.get("quality_gates")),
            "has_artifact_intent": bool(plan.artifact_intent),
            "issues": governance_issues,
        },
        "agent_lifecycle_coverage": agent_lifecycle_coverage,
        "active_task_state": _task_state(plan),
        "validation_gate_ids": [gate.get("id") for gate in plan.validation_gates],
        "artifact_intent": plan.artifact_intent,
        "issues": issues,
    }


def build_production_chain_audit(root: Path) -> dict[str, Any]:
    """Build a deterministic audit of representative production chains."""
    from production_pack_registry import audit_pack_catalog
    from workflow_plan import build_workflow_plan

    root = root.resolve()
    pack_catalog_audit = audit_pack_catalog(root / "config" / "production_packs.yml")
    scenarios: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="agentlab-chain-audit-") as tmp:
        tmp_path = Path(tmp)
        for scenario in SCENARIOS:
            request_path = tmp_path / f"{scenario.scenario_id}.md"
            request_path.write_text(scenario.request, encoding="utf-8")
            plan = build_workflow_plan(
                root,
                scenario.project,
                f"task_chain_audit_{scenario.scenario_id}",
                user_request_path=request_path,
            )
            scenarios.append(_summarize_plan(plan, scenario))

    status = (
        "pass"
        if all(item["status"] == "pass" for item in scenarios)
        and pack_catalog_audit.get("status") == "pass"
        else "fail"
    )
    return {
        "schema_version": 1,
        "report_type": "agentlab_production_chain_audit",
        "root": str(root),
        "status": status,
        "pack_catalog_audit": pack_catalog_audit,
        "scenarios": scenarios,
        "invariants": [
            "code tasks keep the code_factory shell and Coder path",
            "known non-code tasks use configured production packs",
            "unknown complex non-code tasks enter production-pack synthesis",
            "narrative heavy audit uses Reviewer and Scribe without default prose generation",
            "non-code active contracts do not inherit implementation reports, interface maps, coder prompts, or repo maps",
            "every representative chain has lifecycle nodes, memory contract, task-state records, quality gates, and artifact intent",
            "effective lifecycle nodes must respect route agents so audit-only routes do not activate generation nodes",
            "every route agent in a representative chain must own at least one effective lifecycle node",
        ],
    }
