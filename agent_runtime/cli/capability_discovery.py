"""Metadata-only capability search and radar commands."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer
import yaml
from rich.console import Console

from atomic_io import atomic_write_yaml
from agent_runtime.capability_audit import (
    audit_capability_archive,
    audition_capability_archive,
)
from agent_runtime.capability_discovery import (
    CapabilityDiscoveryError,
    GitHubSourceAdapter,
    LocalAgentSkillsAdapter,
    McpRegistrySourceAdapter,
)
from agent_runtime.capability_promotion import (
    evaluate_capability_promotion,
    evaluate_capability_rollback,
)
from agent_runtime.capability_vault import (
    CapabilityPackage,
    CapabilityVaultError,
    load_private_capability_vault,
)

RADAR_QUERIES = {
    "code": "agent coding tool",
    "agents": "agent skill MCP",
    "narrative": "longform narrative writing agent",
    "media": "media generation MCP",
    "research": "research retrieval agent tool",
}


def register_capability_discovery_commands(
    app: typer.Typer,
    agentlab_root: Path,
    console: Console,
) -> None:
    capability_app = typer.Typer(
        help="Quarantined metadata-only capability discovery.",
        no_args_is_help=True,
    )

    def discover(query: str, source: str) -> dict:
        candidates: list[dict] = []
        failures: list[dict[str, str]] = []
        selected = (
            {"local", "github", "mcp"}
            if source == "all"
            else {item.strip() for item in source.split(",") if item.strip()}
        )
        unknown = selected - {"local", "github", "mcp"}
        if unknown:
            raise CapabilityDiscoveryError(
                f"unknown discovery source: {sorted(unknown)[0]}"
            )
        adapters: list[tuple[str, Callable[[], list[dict]]]] = []
        if "local" in selected:
            adapters.append(
                (
                    "local",
                    lambda: LocalAgentSkillsAdapter(
                        agentlab_root / "skills" / "active"
                    ).search(query),
                )
            )
        if "github" in selected:
            adapters.append(("github", lambda: GitHubSourceAdapter().search(query)))
        if "mcp" in selected:
            adapters.append(("mcp", lambda: McpRegistrySourceAdapter().search(query)))
        for name, operation in adapters:
            try:
                candidates.extend(operation())
            except (CapabilityDiscoveryError, OSError, TimeoutError) as exc:
                failures.append({"source": name, "error": type(exc).__name__})
        return {
            "schema_version": "capability-discovery-result/v1",
            "status": "pass" if not failures else "partial",
            "query": query,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "source_failures": failures,
            "installation_performed": False,
            "promotion_performed": False,
        }

    def load_manifest(path: Path) -> dict:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise CapabilityDiscoveryError("capability manifest is unreadable") from exc
        if not isinstance(value, dict):
            raise CapabilityDiscoveryError("capability manifest must be a mapping")
        return value

    def load_mapping(path: Path, label: str) -> dict:
        value = load_manifest(path)
        if not isinstance(value, dict):
            raise CapabilityDiscoveryError(f"{label} must be a mapping")
        return value

    def maybe_record(result: dict, record_vault: bool) -> None:
        if not record_vault or result.get("status") != "approved":
            return
        try:
            record = load_private_capability_vault(
                agentlab_root
            ).record_lifecycle_decision(result)
        except CapabilityVaultError as exc:
            raise CapabilityDiscoveryError(str(exc)) from exc
        result["vault_record"] = record

    @capability_app.command("search")
    def search(
        mode: str = typer.Option("task", "--mode"),
        query: str = typer.Option(..., "--query"),
        project: str = typer.Option(..., "--project"),
        source: str = typer.Option("all", "--source"),
    ) -> None:
        """Search for a current task gap; results remain quarantined metadata."""
        if mode != "task":
            raise typer.BadParameter("--mode must be task")
        try:
            result = discover(query, source)
        except CapabilityDiscoveryError as exc:
            raise typer.BadParameter(str(exc)) from exc
        result["mode"] = mode
        result["project"] = project
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @capability_app.command("radar")
    def radar(
        profile: str = typer.Option(..., "--profile"),
        source: str = typer.Option("all", "--source"),
    ) -> None:
        """Run one profile scan; scheduling belongs to the configured Runtime."""
        query = RADAR_QUERIES.get(profile)
        if query is None:
            raise typer.BadParameter(
                "--profile must be code, agents, narrative, media, or research"
            )
        try:
            result = discover(query, source)
        except CapabilityDiscoveryError as exc:
            raise typer.BadParameter(str(exc)) from exc
        result["mode"] = "radar"
        result["profile"] = profile
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @capability_app.command("audit")
    def audit(
        manifest: Path = typer.Option(..., "--manifest"),
        source_archive: Path = typer.Option(..., "--source-archive"),
        output: Path | None = typer.Option(None, "--output"),
    ) -> None:
        """Perform static archive, SBOM, boundary, and injection checks."""
        try:
            result = audit_capability_archive(
                load_manifest(manifest),
                source_archive=source_archive,
            )
        except CapabilityDiscoveryError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if output is not None:
            atomic_write_yaml(output, result)
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )
        if result["status"] != "pass":
            raise typer.Exit(code=1)

    @capability_app.command("audition")
    def audition(
        manifest: Path = typer.Option(..., "--manifest"),
        source_archive: Path = typer.Option(..., "--source-archive"),
        output: Path | None = typer.Option(None, "--output"),
    ) -> None:
        """Run the declared probe in a one-shot network-denied OS sandbox."""
        try:
            result = audition_capability_archive(
                load_manifest(manifest),
                source_archive=source_archive,
            )
        except CapabilityDiscoveryError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if output is not None:
            atomic_write_yaml(output, result)
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )
        if result["status"] != "pass":
            raise typer.Exit(code=1)

    @capability_app.command("inspect")
    def inspect(
        manifest: Path = typer.Option(..., "--manifest"),
    ) -> None:
        """Validate and display one package without loading or executing it."""
        try:
            package = CapabilityPackage.from_mapping(load_manifest(manifest))
        except (CapabilityDiscoveryError, CapabilityVaultError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        result = {
            "schema_version": "capability-inspection/v1",
            "status": "pass",
            "package_id": package.package_id,
            "package_type": package.package_type,
            "version": package.version,
            "source": {
                "revision": package.document["source"]["revision"],
                "digest": package.source_digest,
                "license": package.document["source"]["license"],
            },
            "capability_tags": package.document["capability_tags"],
            "permissions": package.document["permissions"],
            "network_boundary": package.document["network_boundary"],
            "data_boundary": package.document["data_boundary"],
            "requires_user_approval": package.requires_user_approval,
            "source_uri_redacted": True,
            "execution_performed": False,
        }
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @capability_app.command("promote")
    def promote(
        manifest: Path = typer.Option(..., "--manifest"),
        current_status: str = typer.Option(..., "--current-status"),
        target_status: str = typer.Option(..., "--target-status"),
        static_audit: Path = typer.Option(..., "--static-audit"),
        audition_receipt: Path = typer.Option(..., "--audition"),
        supervisor_review: Path = typer.Option(..., "--supervisor-review"),
        fixtures: Path = typer.Option(..., "--fixtures"),
        user_approval: Path | None = typer.Option(None, "--user-approval"),
        canary_health: Path | None = typer.Option(None, "--canary-health"),
        output: Path | None = typer.Option(None, "--output"),
        record_vault: bool = typer.Option(
            True,
            "--record-vault/--no-record-vault",
        ),
    ) -> None:
        """Evaluate and record a hash-bound canary or active transition."""
        try:
            fixture_document = yaml.safe_load(
                fixtures.read_text(encoding="utf-8")
            )
            fixture_items = (
                fixture_document.get("fixtures")
                if isinstance(fixture_document, dict)
                else fixture_document
            )
            if not isinstance(fixture_items, list) or any(
                not isinstance(item, dict) for item in fixture_items
            ):
                raise CapabilityDiscoveryError(
                    "fixtures must be a list of mappings"
                )
            result = evaluate_capability_promotion(
                load_mapping(manifest, "manifest"),
                current_status=current_status,
                target_status=target_status,
                static_audit=load_mapping(static_audit, "static audit"),
                audition=load_mapping(audition_receipt, "audition"),
                supervisor_review=load_mapping(
                    supervisor_review, "supervisor review"
                ),
                fixture_results=fixture_items,
                user_approval_receipt=(
                    load_mapping(user_approval, "user approval")
                    if user_approval
                    else None
                ),
                canary_health=(
                    load_mapping(canary_health, "canary health")
                    if canary_health
                    else None
                ),
            )
            maybe_record(result, record_vault)
        except (
            OSError,
            UnicodeError,
            yaml.YAMLError,
            CapabilityDiscoveryError,
        ) as exc:
            raise typer.BadParameter(str(exc)) from exc
        if output is not None:
            atomic_write_yaml(output, result)
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )
        if result["status"] != "approved":
            raise typer.Exit(code=1)

    @capability_app.command("rollback")
    def rollback(
        manifest: Path = typer.Option(..., "--manifest"),
        current_status: str = typer.Option(..., "--current-status"),
        health_receipt: Path = typer.Option(..., "--health-receipt"),
        output: Path | None = typer.Option(None, "--output"),
        record_vault: bool = typer.Option(
            True,
            "--record-vault/--no-record-vault",
        ),
    ) -> None:
        """Rollback a canary or active package after failure or digest drift."""
        try:
            result = evaluate_capability_rollback(
                load_mapping(manifest, "manifest"),
                current_status=current_status,
                health_receipt=load_mapping(
                    health_receipt, "health receipt"
                ),
            )
            maybe_record(result, record_vault)
        except CapabilityDiscoveryError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if output is not None:
            atomic_write_yaml(output, result)
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )
        if result["status"] != "approved":
            raise typer.Exit(code=1)

    app.add_typer(capability_app, name="capability")
