"""User-facing model configuration commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib

import typer
import yaml
from rich.console import Console
from rich.table import Table


MODE_TO_TIER = {
    "quality": "full",
    "balanced": "performance",
    "frugal": "low",
    "full": "full",
    "performance": "performance",
    "low": "low",
}

ROLE_ALIASES = {
    "supervisor": "supervisor",
    "reposcout": "reposcout",
    "repo_scout": "reposcout",
    "researcher": "researcher",
    "interfacemapper": "interface_mapper",
    "interface_mapper": "interface_mapper",
    "promptengineer": "prompt_engineer",
    "prompt_engineer": "prompt_engineer",
    "coder": "coder",
    "artifactproducer": "artifact_producer",
    "artifact_producer": "artifact_producer",
    "testerauditor": "tester_auditor",
    "tester_auditor": "tester_auditor",
    "verifier": "verifier",
    "archivist": "archivist",
    "writer": "writer",
}


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _role_key(role: str) -> str:
    key = str(role or "").replace("-", "_").replace(" ", "_").lower()
    return ROLE_ALIASES.get(key, key)


def _proposal_dir(root: Path) -> Path:
    return root / ".agentlab" / "model_proposals"


def _proposal_id(role: str, cli: str, model: str) -> str:
    seed = f"{datetime.now(timezone.utc).isoformat()}:{role}:{cli}:{model}".encode()
    return "model_" + hashlib.sha1(seed).hexdigest()[:12]


def _tier(mode: str) -> str:
    normalized = str(mode or "balanced").lower()
    if normalized not in MODE_TO_TIER:
        raise typer.BadParameter("mode must be quality, balanced, frugal, full, performance, or low")
    return MODE_TO_TIER[normalized]


def _mode_config(agent_model_profiles: dict[str, Any], mode: str) -> dict[str, Any]:
    tier = _tier(mode)
    default_mode = str(agent_model_profiles.get("default_mode") or "full_cli")
    modes = agent_model_profiles.get("modes") or {}
    return ((modes.get(default_mode) or {}).get("tiers") or {}).get(tier) or {}


def _catalog_entry(catalog: dict[str, Any], model_key: str) -> dict[str, Any]:
    return ((catalog.get("models") or {}).get(model_key) or {}) if model_key else {}


def _provider_entry(catalog: dict[str, Any], model_entry: dict[str, Any]) -> dict[str, Any]:
    provider = str(model_entry.get("provider") or "")
    return ((catalog.get("providers") or {}).get(provider) or {}) if provider else {}


def _cost_source(model_entry: dict[str, Any], provider_entry: dict[str, Any]) -> str:
    pricing = model_entry.get("pricing") or {}
    billing = pricing.get("billing_source") or pricing.get("currency") or provider_entry.get("currency")
    if not billing:
        return "unknown"
    if billing == "token_plan":
        return "subscription/token plan"
    if billing == "codex_oauth":
        return "oauth/subscription quota"
    if billing == "agy_oauth":
        return "oauth/subscription quota"
    if billing == "gemini_api_key":
        return "free-tier/api quota"
    return f"pay-as-you-go/{billing}"


def _risk(model_key: str, model_entry: dict[str, Any]) -> str:
    weaknesses = ", ".join(str(item) for item in model_entry.get("weaknesses") or [])
    if model_key.startswith("qwen3_7") or model_key.startswith("qwen3_6_plus"):
        return weaknesses or "higher cost; use only when the task needs Qwen strengths"
    return weaknesses or "normal"


def _role_rows(root: Path, *, mode: str, role: str | None) -> list[dict[str, str]]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml", {}) or {}
    catalog = _read_yaml(root / "config" / "model_catalog.yml", {}) or {}
    tier_cfg = _mode_config(profiles, mode)
    selected_role = _role_key(role) if role else None
    rows: list[dict[str, str]] = []
    for role_key, cfg in sorted(tier_cfg.items()):
        if selected_role and role_key != selected_role:
            continue
        if isinstance(cfg, str):
            rows.append({
                "role": role_key,
                "cli": "skip",
                "model": cfg,
                "provider": "",
                "cost": "",
                "fallback": "",
                "fit": "role skipped in this mode",
                "risk": "",
            })
            continue
        if not isinstance(cfg, dict):
            continue
        model_key = str(cfg.get("default") or cfg.get("provider") or "")
        model_entry = _catalog_entry(catalog, model_key)
        provider_entry = _provider_entry(catalog, model_entry)
        rows.append({
            "role": role_key,
            "cli": str(cfg.get("cli_agent") or cfg.get("executor_type") or "direct_api"),
            "model": model_key,
            "provider": str(model_entry.get("provider") or cfg.get("provider") or ""),
            "cost": _cost_source(model_entry, provider_entry),
            "fallback": str(cfg.get("fallback") or cfg.get("fallback_cli_agent") or ""),
            "fit": ", ".join(str(item) for item in model_entry.get("suitable_agents") or [])[:80],
            "risk": _risk(model_key, model_entry),
        })
    return rows


def _render_rows(console: Console, rows: list[dict[str, str]]) -> None:
    table = Table()
    table.add_column("Role", no_wrap=True)
    table.add_column("CLI/API", no_wrap=True)
    table.add_column("Model", overflow="fold")
    table.add_column("Provider", overflow="fold")
    table.add_column("Cost", overflow="fold")
    table.add_column("Fallback", overflow="fold")
    table.add_column("Fit", overflow="fold")
    table.add_column("Risk", overflow="fold")
    for row in rows:
        table.add_row(
            row["role"],
            row["cli"],
            row["model"],
            row["provider"],
            row["cost"],
            row["fallback"],
            row["fit"],
            row["risk"],
        )
    console.print(table)
    for row in rows:
        console.print(
            " | ".join(
                [
                    f"role={row['role']}",
                    f"cli_api={row['cli']}",
                    f"model={row['model']}",
                    f"provider={row['provider']}",
                    f"cost={row['cost']}",
                    f"fallback={row['fallback']}",
                    f"fit={row['fit']}",
                    f"risk={row['risk']}",
                ]
            )
        )


def _doctor_issues(root: Path) -> list[dict[str, str]]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml", {}) or {}
    issues: list[dict[str, str]] = []
    modes = profiles.get("modes") or {}
    for mode_name, mode_cfg in modes.items():
        tiers = (mode_cfg or {}).get("tiers") or {}
        for tier_name in ("performance", "low"):
            for role, cfg in (tiers.get(tier_name) or {}).items():
                if not isinstance(cfg, dict):
                    continue
                for field in ("default", "fallback"):
                    value = str(cfg.get(field) or "")
                    if value.startswith("qwen3_7_max") or (tier_name == "low" and value.startswith("qwen3_6_plus")):
                        issues.append({
                            "severity": "warning",
                            "scope": f"{mode_name}.{tier_name}.{role}.{field}",
                            "issue": "high_qwen_default_in_balanced_or_frugal",
                            "value": value,
                        })
    return issues


def register_model_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    models_app = typer.Typer(help="Show, propose, apply, and audit model routing.", no_args_is_help=True)

    @models_app.command("show")
    def show_models(
        role: str | None = typer.Option(None, "--role", help="Limit output to one role, e.g. Writer."),
        mode: str = typer.Option("balanced", "--mode", help="quality, balanced, or frugal."),
    ) -> None:
        """Show role model routing with cost source and risks."""
        rows = _role_rows(project_root, mode=mode, role=role)
        _render_rows(console, rows)
        if role and not rows:
            raise typer.Exit(code=1)

    @models_app.command("plan")
    def plan_models(
        mode: str = typer.Option(..., "--mode", help="quality, balanced, or frugal."),
    ) -> None:
        """Preview the model plan for a quality/cost mode."""
        rows = _role_rows(project_root, mode=mode, role=None)
        console.print({"mode": mode, "tier": _tier(mode), "status": "preview_only"})
        _render_rows(console, rows)

    @models_app.command("propose")
    def propose_model(
        role: str = typer.Option(..., "--role", help="Role to change, e.g. Writer."),
        cli: str = typer.Option(..., "--cli", help="CLI/API worker id, e.g. agy."),
        model: str = typer.Option(..., "--model", help="Model catalog key, e.g. deepseek_v4_flash."),
        mode: str = typer.Option("balanced", "--mode", help="quality, balanced, or frugal."),
    ) -> None:
        """Create a model-routing proposal without changing config."""
        catalog = _read_yaml(project_root / "config" / "model_catalog.yml", {}) or {}
        if model not in (catalog.get("models") or {}):
            console.print(f"[red]Unknown model catalog key: {model}[/red]")
            raise typer.Exit(code=1)
        proposal_id = _proposal_id(role, cli, model)
        proposal = {
            "schema_version": 1,
            "proposal_id": proposal_id,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_file": "config/agent_model_profiles.yml",
            "mode": mode,
            "tier": _tier(mode),
            "role": _role_key(role),
            "cli_agent": cli,
            "model": model,
            "requires_agentlab_apply": True,
            "frontdesk_may_apply": False,
        }
        _write_yaml(_proposal_dir(project_root) / f"{proposal_id}.yml", proposal)
        console.print(yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True).rstrip())

    @models_app.command("apply")
    def apply_model_proposal(
        proposal: str = typer.Option(..., "--proposal", help="Proposal id from models propose."),
    ) -> None:
        """Apply an explicit pending model proposal."""
        path = _proposal_dir(project_root) / f"{proposal}.yml"
        data = _read_yaml(path, {}) or {}
        if not data or data.get("proposal_id") != proposal:
            console.print(f"[red]Unknown proposal id: {proposal}[/red]")
            raise typer.Exit(code=1)
        if data.get("status") != "pending":
            console.print(f"[red]Proposal is not pending: {proposal}[/red]")
            raise typer.Exit(code=1)
        profiles_path = project_root / "config" / "agent_model_profiles.yml"
        profiles = _read_yaml(profiles_path, {}) or {}
        mode_name = str(profiles.get("default_mode") or "full_cli")
        role = str(data["role"])
        tier = str(data["tier"])
        modes = profiles.setdefault("modes", {})
        tier_cfg = modes.setdefault(mode_name, {}).setdefault("tiers", {}).setdefault(tier, {})
        old_cfg = tier_cfg.get(role)
        if isinstance(old_cfg, dict):
            new_cfg = dict(old_cfg)
        else:
            new_cfg = {"executor_type": "cli_agent"}
        new_cfg.update({
            "executor_type": "cli_agent",
            "cli_agent": data["cli_agent"],
            "default": data["model"],
        })
        tier_cfg[role] = new_cfg
        _write_yaml(profiles_path, profiles)
        data["status"] = "applied"
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        data["old_config"] = old_cfg
        data["new_config"] = new_cfg
        _write_yaml(path, data)
        console.print(yaml.safe_dump({"status": "applied", "proposal_id": proposal, "role": role}, sort_keys=False).rstrip())

    @models_app.command("doctor")
    def doctor_models() -> None:
        """Audit model routing policy and high-cost defaults."""
        from model_resolver import validate_model_configuration
        from config_loader import load_agentlab_configs

        check = validate_model_configuration(load_agentlab_configs(project_root))
        issues = list(check.get("issues") or []) + _doctor_issues(project_root)
        status = "fail" if any(item.get("severity") == "error" for item in issues) else "pass"
        console.print(yaml.safe_dump({"status": status, "issue_count": len(issues), "issues": issues}, sort_keys=False, allow_unicode=True).rstrip())
        if status != "pass":
            raise typer.Exit(code=1)

    app.add_typer(models_app, name="models")
