"""Audit AgentLab role bindings against representative production chains."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.role_keys import canonical_role_name
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from role_keys import canonical_role_name


ROLE_RESPONSIBILITIES: dict[str, dict[str, str]] = {
    "Supervisor": {
        "responsibility": "Mission contract, route selection, scope, budget, production-pack selection, and approval gates.",
        "boundary": "Does not silently edit source or bypass approval gates.",
    },
    "RepoScout": {
        "responsibility": "Read codebase structure and repository context for code tasks.",
        "boundary": "Does not modify files.",
    },
    "Researcher": {
        "responsibility": "Produce evidence-backed domain briefs for new domains or production-pack synthesis.",
        "boundary": "Does not become a truth source without cited evidence.",
    },
    "Observer": {
        "responsibility": "Inspect only assigned text, image, video, audio, or PDF evidence and return source-bound observations and limitations.",
        "boundary": "Read-only; does not write prose, generate artifacts, or approve its own observations.",
    },
    "InterfaceMapper": {
        "responsibility": "Map code interfaces, contracts, and cross-module boundaries.",
        "boundary": "Does not implement patches.",
    },
    "PromptEngineer": {
        "responsibility": "Prepare bounded execution prompts when a task needs a handoff prompt.",
        "boundary": "Does not own implementation or promotion.",
    },
    "Coder": {
        "responsibility": "Implement code changes and code artifacts under the code_factory pack.",
        "boundary": "Does not default to producing fiction, media, or article artifacts.",
    },
    "ArtifactProducer": {
        "responsibility": "Produce non-code artifacts that follow the selected production-pack contract.",
        "boundary": "Does not replace Coder for source-code implementation.",
    },
    "NarrativePlanner": {
        "responsibility": "Convert blocking narrative audit evidence into a deterministic candidate chapter state plan.",
        "boundary": "Does not draft prose, establish canon, write production, or approve promotion.",
    },
    "Writer": {
        "responsibility": "Draft candidate longform narrative chapters and light-path continuity ledgers.",
        "boundary": "Does not promote candidate text into production memory.",
    },
    "Reviewer": {
        "responsibility": "Independently review narrative or visual candidates against the route-specific quality contract.",
        "boundary": "Does not rewrite prose, mutate media, or act as the producing worker.",
    },
    "Scribe": {
        "responsibility": "Maintain narrative ledgers and state-transition proposals.",
        "boundary": "Does not treat unapproved candidate facts as production facts.",
    },
    "TesterAuditor": {
        "responsibility": "Run or record validation commands, audit risks, and capture evidence.",
        "boundary": "Does not declare pass without evidence.",
    },
    "Verifier": {
        "responsibility": "Independently check output contracts, evidence integrity, acceptance decisions, and handoff completeness.",
        "boundary": "Does not edit implementation artifacts.",
    },
    "Archivist": {
        "responsibility": "Archive and promote accepted outputs into project memory.",
        "boundary": "Does not force promotion for packs that exclude archive or lack acceptance.",
    },
}

def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _role_binding_report(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    path = root / "config" / "agent_role_bindings.yml"
    config = _read_yaml(path)
    roles = config.get("roles", {}) if isinstance(config.get("roles"), dict) else {}
    workers = config.get("workers", {}) if isinstance(config.get("workers"), dict) else {}
    issues: list[str] = []
    report: list[dict[str, Any]] = []

    missing_catalog = sorted(set(roles) - set(ROLE_RESPONSIBILITIES))
    missing_bindings = sorted(set(ROLE_RESPONSIBILITIES) - set(roles))
    for role in missing_catalog:
        issues.append(f"role {role} is bound but missing from responsibility catalog")
    for role in missing_bindings:
        issues.append(f"role {role} is in responsibility catalog but missing from bindings")

    for role in sorted(set(ROLE_RESPONSIBILITIES) | set(roles)):
        binding = roles.get(role, {}) if isinstance(roles.get(role), dict) else {}
        allowed_workers = list(binding.get("allowed_workers") or [])
        required_session = bool(binding.get("required_session"))
        role_issues: list[str] = []
        if role not in ROLE_RESPONSIBILITIES:
            role_issues.append("missing responsibility definition")
        if role not in roles:
            role_issues.append("missing role binding")
        if role in roles and not allowed_workers:
            role_issues.append("allowed_workers is empty")
        if role in roles and not required_session:
            role_issues.append("required_session is not true")
        for worker in allowed_workers:
            worker_config = workers.get(worker, {}) if isinstance(workers.get(worker), dict) else {}
            worker_allowed = set(worker_config.get("allowed_roles") or [])
            worker_forbidden = set(worker_config.get("forbidden_roles") or [])
            if not worker_config:
                role_issues.append(f"allowed worker {worker} is not configured")
            elif role not in worker_allowed:
                role_issues.append(f"worker {worker} does not reciprocally allow {role}")
            if role in worker_forbidden:
                role_issues.append(f"worker {worker} both allows and forbids {role}")
        issues.extend(f"{role}: {issue}" for issue in role_issues)
        report.append(
            {
                "role": role,
                "status": "pass" if not role_issues else "fail",
                "responsibility": ROLE_RESPONSIBILITIES.get(role, {}).get("responsibility"),
                "boundary": ROLE_RESPONSIBILITIES.get(role, {}).get("boundary"),
                "allowed_workers": allowed_workers,
                "required_session": required_session,
                "issues": role_issues,
            }
        )
    return report, issues


def _chain_role_report(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        from production_chain_audit import build_production_chain_audit
    except ModuleNotFoundError:
        from agent_runtime.production_chain_audit import build_production_chain_audit

    chain = build_production_chain_audit(root)
    roles = set(ROLE_RESPONSIBILITIES)
    issues: list[str] = []
    report: list[dict[str, Any]] = []
    for scenario in chain.get("scenarios", []):
        agents = [str(agent) for agent in scenario.get("agents", [])]
        unknown = [agent for agent in agents if agent not in roles]
        lifecycle_coverage = (
            scenario.get("agent_lifecycle_coverage", {})
            if isinstance(scenario.get("agent_lifecycle_coverage"), dict)
            else {}
        )
        missing_lifecycle_agents = list(lifecycle_coverage.get("missing_agents") or [])
        if unknown:
            issues.append(f"{scenario.get('scenario_id')}: unknown agents: {', '.join(unknown)}")
        if lifecycle_coverage.get("status") not in {None, "pass"}:
            issues.append(
                f"{scenario.get('scenario_id')}: route agents without effective lifecycle nodes: "
                + ", ".join(str(agent) for agent in missing_lifecycle_agents)
            )
        report.append(
            {
                "scenario_id": scenario.get("scenario_id"),
                "status": "pass"
                if scenario.get("status") == "pass"
                and not unknown
                and lifecycle_coverage.get("status") in {None, "pass"}
                else "fail",
                "production_pack": scenario.get("production_pack", {}).get("pack_id"),
                "route_key": scenario.get("route_key"),
                "agents": agents,
                "unknown_agents": unknown,
                "agent_lifecycle_coverage": lifecycle_coverage,
                "scenario_issues": scenario.get("issues", []),
            }
        )
    return report, issues


def _worker_coverage_report(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    config = _read_yaml(root / "config" / "agent_role_bindings.yml")
    workers = config.get("workers", {}) if isinstance(config.get("workers"), dict) else {}
    roles = set(ROLE_RESPONSIBILITIES)
    issues: list[str] = []
    report: list[dict[str, Any]] = []
    for worker_name, worker_config in sorted(workers.items()):
        worker_config = worker_config if isinstance(worker_config, dict) else {}
        allowed = set(worker_config.get("allowed_roles") or [])
        forbidden = set(worker_config.get("forbidden_roles") or [])
        overlap = sorted(allowed & forbidden)
        unknown = sorted((allowed | forbidden) - roles)
        undecided = sorted(roles - allowed - forbidden)
        worker_issues: list[str] = []
        if overlap:
            worker_issues.append(f"roles both allowed and forbidden: {', '.join(overlap)}")
        if unknown:
            worker_issues.append(f"unknown role references: {', '.join(unknown)}")
        if undecided:
            worker_issues.append(f"roles neither allowed nor forbidden: {', '.join(undecided)}")
        issues.extend(f"{worker_name}: {issue}" for issue in worker_issues)
        report.append(
            {
                "worker": worker_name,
                "status": "pass" if not worker_issues else "fail",
                "allowed_roles": sorted(allowed),
                "forbidden_roles": sorted(forbidden),
                "issues": worker_issues,
            }
        )
    return report, issues


def _worker_capabilities(worker_config: dict[str, Any]) -> set[str]:
    explicit = {str(item) for item in worker_config.get("worker_capabilities") or []}
    if explicit:
        return explicit
    capabilities: set[str] = set()
    if worker_config.get("frontdesk_capable"):
        capabilities.add("frontdesk_gateway")
    if worker_config.get("worker_capable"):
        capabilities.add("role_worker")
    return capabilities


def _profile_role_binding_issue(
    role_bindings: dict[str, Any],
    worker: str,
    role: str,
) -> str | None:
    roles = role_bindings.get("roles", {}) if isinstance(role_bindings.get("roles"), dict) else {}
    workers = role_bindings.get("workers", {}) if isinstance(role_bindings.get("workers"), dict) else {}
    role_config = roles.get(role, {}) if isinstance(roles.get(role), dict) else {}
    worker_config = workers.get(worker, {}) if isinstance(workers.get(worker), dict) else {}
    if not worker_config:
        return f"worker {worker!r} is not configured in agent_role_bindings"
    if worker_config.get("frontdesk_capable") and not worker_config.get("worker_capable"):
        return f"worker {worker!r} is frontdesk-only and cannot execute role {role!r}"
    capabilities = _worker_capabilities(worker_config)
    if role in {"ArtifactProducer", "Writer"}:
        if not ({"candidate_artifact_worker", "role_worker"} & capabilities):
            return f"worker {worker!r} lacks candidate_artifact_worker or role_worker capability for role {role!r}"
    elif "role_worker" not in capabilities:
        return f"worker {worker!r} lacks role_worker capability for role {role!r}"
    if role in set(worker_config.get("forbidden_roles") or []):
        return f"worker {worker!r} is explicitly forbidden for role {role!r}"
    if role not in set(worker_config.get("allowed_roles") or []):
        return f"worker {worker!r} does not list role {role!r} in allowed_roles"
    if worker not in set(role_config.get("allowed_workers") or []):
        return f"role {role!r} does not list worker {worker!r} in allowed_workers"
    return None


def _profile_contract_report(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml")
    model_catalog = _read_yaml(root / "config" / "model_catalog.yml")
    catalog_models = (
        model_catalog.get("models", {})
        if isinstance(model_catalog.get("models"), dict)
        else {}
    )
    contracts = _read_yaml(root / "config" / "worker_invocation_contracts.yml").get("contracts", {})
    role_bindings = _read_yaml(root / "config" / "agent_role_bindings.yml")
    modes = profiles.get("modes", {}) if isinstance(profiles.get("modes"), dict) else {}
    contracts = contracts if isinstance(contracts, dict) else {}
    issues: list[str] = []
    report: list[dict[str, Any]] = []

    for mode_name, mode in sorted(modes.items()):
        if mode_name == "trusted_headless_cli" or not isinstance(mode, dict):
            continue
        tiers = mode.get("tiers", {}) if isinstance(mode.get("tiers"), dict) else {}
        for tier_name, tier in sorted(tiers.items()):
            if not isinstance(tier, dict):
                continue
            for role_key, role_config in sorted(tier.items()):
                if not isinstance(role_config, dict) or role_config.get("executor_type") != "cli_agent":
                    continue
                role = canonical_role_name(str(role_key))
                entry_issues: list[str] = []
                contract_name = str(role_config.get("invocation_contract") or "")
                cli_agent = str(role_config.get("cli_agent") or "")
                default_model = str(role_config.get("default") or "")
                contract = contracts.get(contract_name, {}) if isinstance(contracts.get(contract_name), dict) else {}
                contract_worker = str(contract.get("worker_id") or "")
                if not default_model:
                    entry_issues.append("default model key is missing")
                elif default_model not in catalog_models:
                    entry_issues.append(f"default model key {default_model!r} is missing from model_catalog.yml")
                if not contract:
                    entry_issues.append(f"missing invocation_contract {contract_name!r}")
                elif contract_worker != cli_agent:
                    entry_issues.append(
                        f"cli_agent {cli_agent!r} does not match invocation_contract {contract_name!r} worker_id {contract_worker!r}"
                    )
                role_binding_issue = _profile_role_binding_issue(role_bindings, cli_agent, role)
                role_binding_status = "pass" if role_binding_issue is None else "fail"
                if role_binding_issue:
                    entry_issues.append(role_binding_issue)

                fallback_cli_agent = str(role_config.get("fallback_cli_agent") or "")
                fallback_contract_name = str(role_config.get("fallback_invocation_contract") or "")
                fallback_model = str(role_config.get("fallback") or default_model)
                fallback_contract_worker = ""
                fallback_role_binding_status = None
                fallback_role_binding_issue = None
                if fallback_cli_agent:
                    if fallback_model not in catalog_models:
                        entry_issues.append(f"fallback model key {fallback_model!r} is missing from model_catalog.yml")
                    fallback_contract = (
                        contracts.get(fallback_contract_name, {})
                        if isinstance(contracts.get(fallback_contract_name), dict)
                        else {}
                    )
                    fallback_contract_worker = str(fallback_contract.get("worker_id") or "")
                    if not fallback_contract:
                        entry_issues.append(
                            f"missing fallback_invocation_contract {fallback_contract_name!r}"
                        )
                    elif fallback_contract_worker != fallback_cli_agent:
                        entry_issues.append(
                            f"fallback_cli_agent {fallback_cli_agent!r} does not match fallback_invocation_contract {fallback_contract_name!r} worker_id {fallback_contract_worker!r}"
                        )
                    fallback_role_binding_issue = _profile_role_binding_issue(
                        role_bindings, fallback_cli_agent, role
                    )
                    fallback_role_binding_status = (
                        "pass" if fallback_role_binding_issue is None else "fail"
                    )
                    if fallback_role_binding_issue:
                        entry_issues.append(f"fallback {fallback_role_binding_issue}")

                issue_prefix = f"{mode_name}/{tier_name}/{role_key}"
                issues.extend(f"{issue_prefix}: {issue}" for issue in entry_issues)
                report_item = {
                    "mode": mode_name,
                    "tier": tier_name,
                    "role_key": role_key,
                    "role": role,
                    "status": "pass" if not entry_issues else "fail",
                    "cli_agent": cli_agent,
                    "default_model": default_model,
                    "default_model_catalog_status": "pass" if default_model in catalog_models else "fail",
                    "invocation_contract": contract_name,
                    "contract_worker": contract_worker,
                    "role_binding_status": role_binding_status,
                    "issues": entry_issues,
                }
                if role_binding_issue:
                    report_item["role_binding_issue"] = role_binding_issue
                if fallback_cli_agent:
                    report_item["fallback_cli_agent"] = fallback_cli_agent
                    report_item["fallback_model"] = fallback_model
                    report_item["fallback_model_source"] = (
                        "explicit" if role_config.get("fallback") else "default_model"
                    )
                    report_item["fallback_model_catalog_status"] = (
                        "pass" if fallback_model in catalog_models else "fail"
                    )
                    report_item["fallback_invocation_contract"] = fallback_contract_name
                    report_item["fallback_contract_worker"] = fallback_contract_worker
                    report_item["fallback_role_binding_status"] = fallback_role_binding_status
                    if fallback_role_binding_issue:
                        report_item["fallback_role_binding_issue"] = fallback_role_binding_issue
                report.append(report_item)
    return report, issues


def build_agent_role_chain_audit(root: Path) -> dict[str, Any]:
    """Build a deterministic role/worker/chain consistency audit."""
    root = root.resolve()
    role_reports, role_issues = _role_binding_report(root)
    chain_reports, chain_issues = _chain_role_report(root)
    worker_reports, worker_issues = _worker_coverage_report(root)
    profile_contract_reports, profile_contract_issues = _profile_contract_report(root)
    issues = role_issues + chain_issues + worker_issues + profile_contract_issues
    return {
        "schema_version": 1,
        "report_type": "agentlab_agent_role_chain_audit",
        "root": str(root),
        "status": "pass" if not issues else "fail",
        "source_files": [
            str(root / "config" / "agent_role_bindings.yml"),
            str(root / "config" / "agent_model_profiles.yml"),
            str(root / "config" / "worker_invocation_contracts.yml"),
            str(root / "config" / "routing_rules.yml"),
            str(root / "config" / "production_packs.yml"),
        ],
        "roles": role_reports,
        "workers": worker_reports,
        "profile_contracts": profile_contract_reports,
        "production_chains": chain_reports,
        "issues": issues,
        "invariants": [
            "every role has a responsibility and boundary",
            "every role has at least one allowed worker and requires a role session",
            "role allowed_workers must be reciprocated by worker allowed_roles",
            "every worker must explicitly allow or forbid every canonical role",
            "every cli_agent and fallback_cli_agent must match the selected invocation contract worker_id",
            "every cli_agent and fallback_cli_agent selected by runtime profiles must be allowed by role bindings",
            "every default and effective fallback model selected by runtime profiles must exist in model_catalog.yml",
            "every agent used by representative production chains must be a canonical role",
            "every agent used by representative production chains must own at least one effective lifecycle node",
        ],
    }
