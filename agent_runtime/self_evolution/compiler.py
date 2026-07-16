"""Deterministic bridge compiler for component-managed AgentLab roles."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import yaml

from agent_runtime.routing.dynamic_selector import DynamicRouteSelector
from agent_runtime.routing.route_catalog import RouteCatalog
from agent_runtime.runtime_registry import RuntimeRegistry, TaskDemand

from .models import ComponentManifest, ManifestValidationError
from .role_catalog import RoleCatalog


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class RoleComponentCompiler:
    """Compile one role manifest into reviewable runtime bridge artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.registry = RuntimeRegistry.load(self.root)
        self.catalog = RoleCatalog.load(self.root)

    def compile(self, manifest: ComponentManifest, out_dir: Path) -> dict[str, Any]:
        if manifest.kind != "agent_role":
            raise ManifestValidationError(["RoleComponentCompiler only accepts agent_role manifests"])
        manifest.require_valid()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        issues = self._preflight_issues(manifest)
        spec = manifest.spec
        binding = spec.get("worker_binding") or {}
        runtime = spec.get("runtime_demand") or {}
        allowed_workers = [str(item) for item in binding.get("allowed_workers") or []]
        candidate_routes = self.registry.candidates_for(manifest.display_name)
        if not candidate_routes:
            candidate_routes = self.registry.whitelisted_route_templates(
                allowed_workers=allowed_workers,
            )
        demand = TaskDemand(
            role=manifest.display_name,
            capability_weights={
                str(name): float(value)
                for name, value in (runtime.get("capability_weights") or {}).items()
            },
            required_modalities=tuple(str(item).lower() for item in runtime.get("required_modalities") or []),
            quality_floor=float(runtime.get("quality_floor") or 0.82),
            data_class=str(runtime.get("data_class") or "private"),
            predicted_input_tokens=max(0, int(runtime.get("predicted_input_tokens") or 5000)),
            predicted_output_tokens=max(0, int(runtime.get("predicted_output_tokens") or 2500)),
            predicted_quota_percent=max(0.0, float(runtime.get("predicted_quota_percent") or 0.0)),
            risk_reserve_percent=max(0.0, float(runtime.get("risk_reserve_percent") or 0.0)),
            long_batch=bool(runtime.get("long_batch", False)),
            checkpoint_complete=True,
        )
        decision = DynamicRouteSelector(self.registry).select(
            demand,
            candidate_route_ids=candidate_routes,
        )
        selected_worker = ""
        invocation_contract = ""
        if decision.get("status") == "selected":
            route_id = str(decision["route_id"])
            identity = self.registry.route_identity(route_id)
            shell = self.registry.shells.get(identity.shell_id) or {}
            selected_worker = str(shell.get("worker_id") or identity.shell_id)
            invocation_contract = str(
                (binding.get("invocation_contracts") or {}).get(selected_worker) or ""
            )
            issues.extend(
                self._invocation_contract_issues(
                    selected_worker,
                    invocation_contract,
                )
            )
        else:
            issues.append("missing_runtime_route")

        files: list[Path] = []
        files.append(_write_yaml(out_dir / "manifest_snapshot.yml", manifest.to_dict()))
        files.append(
            _write_yaml(
                out_dir / "agent_profile.yml",
                {
                    "role_id": manifest.component_id,
                    "display_name": manifest.display_name,
                    "status": manifest.status,
                    "source_template_path": spec.get("template_path"),
                    "template_path": (
                        f"config/generated/roles/{manifest.component_id}/worker_prompt.md"
                    ),
                    "responsibility": spec.get("responsibility"),
                    "boundary": spec.get("boundary"),
                    "permissions": spec.get("permissions") or {},
                    "source": "component_manifest",
                },
            )
        )
        files.append(
            _write_yaml(
                out_dir / "artifact_contract.yml",
                {
                    "role": manifest.display_name,
                    "inputs": (spec.get("artifacts") or {}).get("inputs") or [],
                    "outputs": (spec.get("artifacts") or {}).get("outputs") or [],
                    "default_report": spec.get("default_report"),
                    "execution_surface": "single_run_local_report",
                    "output_count": 1,
                    "candidate_only": True,
                    "production_write": False,
                },
            )
        )
        files.append(
            _write_yaml(
                out_dir / "role_requirement.yml",
                {
                    "role": manifest.display_name,
                    **dict(spec.get("role_requirements") or {}),
                },
            )
        )
        files.append(
            _write_yaml(
                out_dir / "worker_binding.yml",
                {
                    "role": manifest.display_name,
                    "allowed_workers": allowed_workers,
                    "default_deny_unlisted_workers": True,
                    "required_session": True,
                    "session_creation_authority": "agentlab_runtime_dispatch",
                    "invocation_contracts": dict(binding.get("invocation_contracts") or {}),
                },
            )
        )
        receipt = {
            "schema_version": 1,
            "receipt_type": "component_model_selection",
            "role": manifest.display_name,
            "manifest_fingerprint": manifest.fingerprint,
            "demand": asdict(demand),
            "candidate_route_templates": candidate_routes,
            "decision": decision,
            "selected_worker": selected_worker or None,
            "invocation_contract_override": invocation_contract or None,
            "whitelist_authority": "config/runtime_registry.yml",
            "silent_fallback_allowed": False,
        }
        files.append(_write_yaml(out_dir / "model_selection_receipt.yml", receipt))
        files.append(
            _write_yaml(
                out_dir / "runtime_binding.yml",
                {
                    "role": manifest.display_name,
                    "dynamic_runtime_required": True,
                    "status": "selected" if decision.get("status") == "selected" else "blocked",
                    "selected_route_template": decision.get("route_id"),
                    "selected_worker": selected_worker or None,
                    "invocation_contract": invocation_contract or None,
                    "checkpoint_only_reselection": True,
                    "provider_install_allowed": False,
                    "credential_mutation_allowed": False,
                },
            )
        )
        files.append(
            _write_yaml(
                out_dir / "protocol_binding.yml",
                {
                    "role": manifest.display_name,
                    "required_session": True,
                    "session_creation_authority": "agentlab_runtime_dispatch",
                    "self_review_allowed": False,
                    "self_promotion_allowed": False,
                    "human_merge_gate": True,
                    "activation": "on_config_reload_after_merge",
                },
            )
        )
        files.append(
            _write_yaml(
                out_dir / "init_templates.yml",
                {
                    "role": manifest.display_name,
                    "templates": dict(spec.get("init_artifacts") or {}),
                },
            )
        )
        route_catalog = RouteCatalog.from_file(
            self.root / "config" / "routing_rules.yml"
        )
        registered_routes = sorted(
            route_key
            for route_key in route_catalog.routes
            if manifest.display_name in route_catalog.agents_for(route_key)
        )
        files.append(
            _write_yaml(
                out_dir / "workflow_binding.yml",
                {
                    "role": manifest.display_name,
                    "activation_mode": (
                        "registered_route"
                        if registered_routes
                        else "explicit_role_session"
                    ),
                    "registered_routes": registered_routes,
                    "normal_route_selection": bool(registered_routes),
                    "explicit_role_session_available": True,
                    "auto_route_insertion": False,
                    "route_pack_required_for_default_selection": not bool(
                        registered_routes
                    ),
                    "boundary": (
                        "A new role is runnable after merge through an AgentLab-created "
                        "bound role session. Default mission routing requires a separately "
                        "reviewed route-pack registration."
                    ),
                },
            )
        )
        prompt_path = out_dir / "worker_prompt.md"
        prompt_path.write_text(self._worker_prompt(manifest), encoding="utf-8")
        files.append(prompt_path)
        compatibility = {
            "schema_version": 1,
            "component_id": manifest.component_id,
            "manifest_fingerprint": manifest.fingerprint,
            "status": "pass" if not issues else "blocked",
            "issues": issues,
            "generated_files": [
                {
                    "path": str(path.relative_to(out_dir)),
                    "sha256": _file_hash(path),
                }
                for path in files
            ],
        }
        _write_yaml(out_dir / "compatibility_manifest.yml", compatibility)
        return compatibility

    def _preflight_issues(self, manifest: ComponentManifest) -> list[str]:
        issues = [
            f"runtime_registry:{item['scope']}:{item['issue']}"
            for item in self.registry.validate()
        ]
        existing = self.catalog.get(manifest.display_name)
        if existing and not manifest.replaces_legacy:
            same_component = (
                existing.source == "component_manifest" and existing.role_id == manifest.component_id
            )
            if not same_component:
                issues.append("role_name_collision")
        bindings = _read_yaml(self.root / "config" / "agent_role_bindings.yml")
        workers = bindings.get("workers") or {}
        allowed = (manifest.spec.get("worker_binding") or {}).get("allowed_workers") or []
        for worker in allowed:
            if worker not in workers:
                issues.append(f"unknown_worker:{worker}")
        outputs = set((manifest.spec.get("artifacts") or {}).get("outputs") or [])
        for role in self.catalog.roles():
            if role.display_name == manifest.display_name and manifest.replaces_legacy:
                continue
            collision = outputs & set(role.required_outputs)
            if collision:
                issues.append(
                    f"artifact_output_collision:{role.display_name}:{','.join(sorted(collision))}"
                )
        return issues

    def _invocation_contract_issues(self, worker: str, contract_name: str) -> list[str]:
        if not contract_name:
            return [f"missing_invocation_contract_for_worker:{worker}"]
        contracts = _read_yaml(self.root / "config" / "worker_invocation_contracts.yml").get(
            "contracts", {}
        )
        contract = contracts.get(contract_name) if isinstance(contracts, Mapping) else None
        if not isinstance(contract, Mapping):
            return [f"unknown_invocation_contract:{contract_name}"]
        contract_worker = str(contract.get("worker_id") or "")
        if contract_worker != worker:
            return [
                f"invocation_contract_worker_mismatch:{contract_name}:{contract_worker}:{worker}"
            ]
        return []

    def _worker_prompt(self, manifest: ComponentManifest) -> str:
        spec = manifest.spec
        inputs = "\n".join(f"- {item}" for item in (spec.get("artifacts") or {}).get("inputs") or [])
        outputs = "\n".join(f"- {item}" for item in (spec.get("artifacts") or {}).get("outputs") or [])
        source_template = self.root / str(spec.get("template_path") or "")
        source_instructions = ""
        if source_template.is_file():
            source_instructions = (
                "\n\n## Source Role Instructions\n\n"
                + source_template.read_text(encoding="utf-8").strip()
            )
        return (
            f"# {manifest.display_name}\n\n"
            f"## Responsibility\n\n{spec.get('responsibility')}\n\n"
            f"## Boundary\n\n{spec.get('boundary')}\n\n"
            f"## Required Inputs\n\n{inputs or '- None'}\n\n"
            f"## Required Outputs\n\n{outputs}\n\n"
            "Return exactly one complete AGENTLAB_EDIT block for the declared output. "
            f"Use `{spec.get('default_report')}` as the marker path. Do not wrap the "
            "block in a code fence or return any second artifact. Return only a run-local "
            "candidate; do not modify production, credentials, provider registration, or "
            "approval state."
            f"{source_instructions}\n"
        )
