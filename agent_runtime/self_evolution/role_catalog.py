"""Single read interface for legacy and component-managed AgentLab roles."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

import yaml

from .models import ComponentManifest, ManifestValidationError


LEGACY_DEFAULT_REPORTS = {
    "Supervisor": "01_supervisor_plan.md",
    "RepoScout": "02_reposcout_report.md",
    "Researcher": "03_research_notes.md",
    "Observer": "observation_report.yml",
    "InterfaceMapper": "04_interface_map.md",
    "PromptEngineer": "05_coder_prompt.md",
    "Coder": "06_implementation_report.md",
    "ArtifactProducer": "artifact_producer_report.md",
    "Writer": "fiction_draft.md",
    "NarrativePlanner": "revision_or_rewrite_proposal.yml",
    "Reviewer": "fiction_review.yml",
    "Scribe": "continuity_ledger.yml",
    "TesterAuditor": "08_audit_report.md",
    "Verifier": "verification_report.md",
    "Archivist": "09_archive_update.md",
}
LEGACY_INIT_ARTIFACTS = {
    "Coder": {"05_coder_prompt.md": "# Coder Handoff Prompt\n\nTBD\n"},
    "Reviewer": {"fiction_review.yml": "status: tbd\nfindings: []\n"},
    "Scribe": {"continuity_ledger.yml": "status: tbd\nentries: []\n"},
    "TesterAuditor": {"07_validation_report.md": "# Validation Report\n\nTBD\n"},
}
COMPONENT_ROLE_GENERATED_FILES = {
    "agent_profile.yml",
    "artifact_contract.yml",
    "init_templates.yml",
    "manifest_snapshot.yml",
    "model_selection_receipt.yml",
    "protocol_binding.yml",
    "role_requirement.yml",
    "runtime_binding.yml",
    "worker_binding.yml",
    "worker_prompt.md",
    "workflow_binding.yml",
}


def normalize_role(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def role_key(value: Any) -> str:
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", str(value).strip()).lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _placeholder_for(path: str) -> str:
    if Path(path).suffix in {".yml", ".yaml"}:
        return "status: tbd\n"
    title = Path(path).stem.replace("_", " ").title()
    return f"# {title}\n\nTBD\n"


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    role_id: str
    display_name: str
    source: str
    status: str
    responsibility: str
    boundary: str
    template_path: str
    default_report: str
    init_artifacts: dict[str, str] = field(default_factory=dict)
    required_inputs: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    preferred_capabilities: tuple[str, ...] = ()
    forbidden_capabilities: tuple[str, ...] = ()
    default_risk_ceiling: str = "medium"
    human_approval_required_for: tuple[str, ...] = ()
    allowed_workers: tuple[str, ...] = ()
    required_session: bool = True
    runtime_demand: dict[str, Any] = field(default_factory=dict)
    invocation_contracts: dict[str, str] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    replaces_legacy: bool = False
    manifest_path: str | None = None

    @property
    def normalized_name(self) -> str:
        return normalize_role(self.display_name)

    @property
    def key(self) -> str:
        return self.role_id or role_key(self.display_name)


class RoleCatalog:
    """Merge legacy role declarations with active component manifests."""

    def __init__(
        self,
        root: Path,
        roles: Mapping[str, RoleDefinition],
        *,
        issues: list[str] | None = None,
        blocked_component_roles: set[str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._roles = dict(roles)
        self.issues = list(issues or [])
        self._blocked_component_display_names = set(blocked_component_roles or set())
        self._blocked_component_roles = {
            normalize_role(name) for name in self._blocked_component_display_names
        }

    @classmethod
    def load(cls, root: Path, *, include_inactive: bool = False) -> "RoleCatalog":
        root = Path(root).resolve()
        roles = cls._load_legacy_roles(root)
        issues: list[str] = []
        blocked_component_roles: set[str] = set()

        def block_legacy_component(component_id: str) -> None:
            for key, definition in list(roles.items()):
                if definition.role_id != component_id:
                    continue
                blocked_component_roles.add(definition.display_name)
                roles.pop(key, None)

        manifest_root = root / "config" / "components" / "agents"
        if manifest_root.exists():
            for path in sorted(manifest_root.glob("*.yml")):
                if path.is_symlink() or not path.is_file():
                    block_legacy_component(path.stem)
                    issues.append(
                        f"{path.relative_to(root)}: component manifest must be a regular file"
                    )
                    continue
                try:
                    manifest = ComponentManifest.load(path)
                except (OSError, yaml.YAMLError, ManifestValidationError) as exc:
                    block_legacy_component(path.stem)
                    issues.append(f"{path.relative_to(root)}: {exc}")
                    continue
                if manifest.kind != "agent_role":
                    block_legacy_component(manifest.component_id or path.stem)
                    issues.append(f"{path.relative_to(root)}: kind must be agent_role")
                    continue
                if manifest.status != "active" and not include_inactive:
                    continue
                bundle_issues = cls._generated_bundle_issues(root, manifest)
                if bundle_issues:
                    blocked_component_roles.add(manifest.display_name)
                    roles.pop(normalize_role(manifest.display_name), None)
                    issues.extend(
                        f"{path.relative_to(root)}: {issue}"
                        for issue in bundle_issues
                    )
                    continue
                definition = cls._from_manifest(manifest, path, root)
                key = definition.normalized_name
                existing = roles.get(key)
                if existing and not manifest.replaces_legacy:
                    issues.append(
                        f"component role {definition.display_name} collides with {existing.source} "
                        "without metadata.replaces_legacy"
                    )
                    continue
                roles[key] = definition
        return cls(
            root,
            roles,
            issues=issues,
            blocked_component_roles=blocked_component_roles,
        )

    @staticmethod
    def _generated_bundle_issues(
        root: Path,
        manifest: ComponentManifest,
    ) -> list[str]:
        """Validate the complete compiler-owned role bundle before activation."""

        generated_root = (
            root / "config" / "generated" / "roles" / manifest.component_id
        )
        compatibility_path = generated_root / "compatibility_manifest.yml"
        if generated_root.is_symlink() or not generated_root.is_dir():
            return ["generated role bundle is missing or is not a regular directory"]
        if compatibility_path.is_symlink() or not compatibility_path.is_file():
            return ["generated compatibility manifest is missing or is not regular"]
        try:
            compatibility = _read_yaml(compatibility_path)
        except (OSError, yaml.YAMLError) as exc:
            return [f"generated compatibility manifest is invalid: {exc}"]
        issues: list[str] = []
        if compatibility.get("status") != "pass":
            issues.append("generated compatibility status is not pass")
        if compatibility.get("component_id") != manifest.component_id:
            issues.append("generated compatibility component_id does not match")
        if compatibility.get("manifest_fingerprint") != manifest.fingerprint:
            issues.append("generated compatibility manifest fingerprint does not match")

        declared_items = compatibility.get("generated_files")
        if not isinstance(declared_items, list) or not declared_items:
            issues.append("generated compatibility file inventory is empty")
            declared_items = []
        declared: dict[str, str] = {}
        for index, item in enumerate(declared_items):
            if not isinstance(item, Mapping):
                issues.append(f"generated file inventory item {index} is invalid")
                continue
            raw_path = str(item.get("path") or "")
            relative = PurePosixPath(raw_path)
            if (
                not raw_path
                or relative.is_absolute()
                or ".." in relative.parts
                or raw_path == "compatibility_manifest.yml"
            ):
                issues.append(f"generated file inventory path is unsafe: {raw_path!r}")
                continue
            if raw_path in declared:
                issues.append(f"generated file inventory path is duplicated: {raw_path}")
                continue
            declared[raw_path] = str(item.get("sha256") or "")

        actual: set[str] = set()
        for candidate in generated_root.rglob("*"):
            relative = candidate.relative_to(generated_root).as_posix()
            if candidate.is_symlink():
                issues.append(f"generated role bundle contains symlink: {relative}")
            elif candidate.is_file() and relative != "compatibility_manifest.yml":
                actual.add(relative)
        if set(declared) != actual:
            issues.append("generated compatibility inventory does not match bundle files")
        if set(declared) != COMPONENT_ROLE_GENERATED_FILES:
            issues.append("generated compatibility inventory is not the v1 role bundle")
        if "worker_prompt.md" not in declared:
            issues.append("generated compatibility inventory omits worker_prompt.md")
        for relative, expected_hash in sorted(declared.items()):
            candidate = generated_root.joinpath(*PurePosixPath(relative).parts)
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if not expected_hash or sha256(candidate.read_bytes()).hexdigest() != expected_hash:
                issues.append(f"generated file hash mismatch: {relative}")
        snapshot_path = generated_root / "manifest_snapshot.yml"
        if (
            snapshot_path.is_symlink()
            or not snapshot_path.is_file()
            or _read_yaml(snapshot_path) != manifest.to_dict()
        ):
            issues.append("generated manifest snapshot does not match source manifest")
        return issues

    @staticmethod
    def _load_legacy_roles(root: Path) -> dict[str, RoleDefinition]:
        registry = _read_yaml(root / "config" / "agent_registry.yml").get("agents") or {}
        bindings = _read_yaml(root / "config" / "agent_role_bindings.yml")
        role_bindings = bindings.get("roles") or {}
        requirements = _read_yaml(root / "config" / "agent_role_requirements.yml").get("roles") or {}
        demands = (
            _read_yaml(root / "config" / "routing_policy.yml")
            .get("runtime_routing", {})
            .get("role_demands", {})
        )
        names = list(dict.fromkeys([*registry.keys(), *role_bindings.keys()]))
        roles: dict[str, RoleDefinition] = {}
        for display_name in names:
            agent = registry.get(display_name) if isinstance(registry.get(display_name), Mapping) else {}
            binding = (
                role_bindings.get(display_name)
                if isinstance(role_bindings.get(display_name), Mapping)
                else {}
            )
            key = role_key(display_name)
            requirement = requirements.get(key) or requirements.get(key.replace("_", "")) or {}
            demand = demands.get(key) or demands.get(key.replace("_", "")) or {}
            outputs = tuple(_list(agent.get("required_outputs")))
            report = LEGACY_DEFAULT_REPORTS.get(display_name)
            if not report and outputs:
                report = Path(outputs[0]).name
            report = report or f"{key}_report.md"
            init_artifacts = dict(LEGACY_INIT_ARTIFACTS.get(display_name, {}))
            init_artifacts.setdefault(report, _placeholder_for(report))
            roles[normalize_role(display_name)] = RoleDefinition(
                role_id=key,
                display_name=str(display_name),
                source="legacy_adapter",
                status="active",
                responsibility=str(agent.get("role") or f"AgentLab {display_name} role."),
                boundary=str(
                    agent.get("source_write_policy")
                    or "Bound by the declared role session and artifact contract."
                ),
                template_path=str(agent.get("template_path") or ""),
                default_report=report,
                init_artifacts=init_artifacts,
                required_inputs=tuple(_list(agent.get("required_inputs"))),
                required_outputs=outputs,
                required_capabilities=tuple(_list(requirement.get("required_capabilities"))),
                preferred_capabilities=tuple(_list(requirement.get("preferred_capabilities"))),
                forbidden_capabilities=tuple(_list(requirement.get("forbidden_capabilities"))),
                default_risk_ceiling=str(requirement.get("default_risk_ceiling") or "medium"),
                human_approval_required_for=tuple(
                    _list(requirement.get("human_approval_required_for"))
                ),
                allowed_workers=tuple(_list(binding.get("allowed_workers"))),
                required_session=bool(binding.get("required_session", True)),
                runtime_demand=dict(demand) if isinstance(demand, Mapping) else {},
                invocation_contracts={},
                permissions={
                    "can_edit_source": bool(agent.get("can_edit_source", False)),
                    "can_run_shell": bool(agent.get("can_run_shell", False)),
                    "source_write_policy": agent.get("source_write_policy"),
                },
            )
        return roles

    @staticmethod
    def _from_manifest(manifest: ComponentManifest, path: Path, root: Path) -> RoleDefinition:
        spec = manifest.spec
        artifacts = spec.get("artifacts") if isinstance(spec.get("artifacts"), Mapping) else {}
        requirements = (
            spec.get("role_requirements")
            if isinstance(spec.get("role_requirements"), Mapping)
            else {}
        )
        binding = (
            spec.get("worker_binding")
            if isinstance(spec.get("worker_binding"), Mapping)
            else {}
        )
        init_artifacts = (
            spec.get("init_artifacts")
            if isinstance(spec.get("init_artifacts"), Mapping)
            else {}
        )
        generated_prompt = (
            root
            / "config"
            / "generated"
            / "roles"
            / manifest.component_id
            / "worker_prompt.md"
        )
        effective_template = (
            str(generated_prompt.relative_to(root))
            if generated_prompt.exists()
            else str(spec.get("template_path") or "")
        )
        return RoleDefinition(
            role_id=manifest.component_id,
            display_name=manifest.display_name,
            source="component_manifest",
            status=manifest.status,
            responsibility=str(spec.get("responsibility") or ""),
            boundary=str(spec.get("boundary") or ""),
            template_path=effective_template,
            default_report=str(spec.get("default_report") or ""),
            init_artifacts={str(name): str(content) for name, content in init_artifacts.items()},
            required_inputs=tuple(_list(artifacts.get("inputs"))),
            required_outputs=tuple(_list(artifacts.get("outputs"))),
            required_capabilities=tuple(_list(requirements.get("required_capabilities"))),
            preferred_capabilities=tuple(_list(requirements.get("preferred_capabilities"))),
            forbidden_capabilities=tuple(_list(requirements.get("forbidden_capabilities"))),
            default_risk_ceiling=str(requirements.get("default_risk_ceiling") or "medium"),
            human_approval_required_for=tuple(
                _list(requirements.get("human_approval_required_for"))
            ),
            allowed_workers=tuple(_list(binding.get("allowed_workers"))),
            required_session=bool(binding.get("required_session", True)),
            runtime_demand=dict(spec.get("runtime_demand") or {}),
            invocation_contracts={
                str(worker): str(contract)
                for worker, contract in (binding.get("invocation_contracts") or {}).items()
            },
            permissions=dict(spec.get("permissions") or {}),
            replaces_legacy=manifest.replaces_legacy,
            manifest_path=str(path.relative_to(root)),
        )

    def get(self, role: str) -> RoleDefinition | None:
        return self._roles.get(normalize_role(role))

    def component_role_blocked(self, role: str) -> bool:
        return normalize_role(role) in self._blocked_component_roles

    def require(self, role: str) -> RoleDefinition:
        result = self.get(role)
        if result is None:
            raise KeyError(f"unknown AgentLab role: {role}")
        return result

    def roles(self) -> list[RoleDefinition]:
        return sorted(self._roles.values(), key=lambda item: item.display_name)

    def names(self) -> list[str]:
        return [item.display_name for item in self.roles()]

    def default_reports(self) -> dict[str, str]:
        return {item.display_name: item.default_report for item in self.roles()}

    def role_keys(self) -> dict[str, str]:
        return {normalize_role(item.display_name): item.key for item in self.roles()}

    def init_templates(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for item in self.roles():
            templates = dict(item.init_artifacts)
            if item.default_report and item.default_report not in templates:
                templates[item.default_report] = _placeholder_for(item.default_report)
            result[item.display_name] = templates
        return result

    def responsibility_catalog(self) -> dict[str, dict[str, str]]:
        return {
            item.display_name: {
                "responsibility": item.responsibility,
                "boundary": item.boundary,
            }
            for item in self.roles()
        }

    def agent_configs(
        self,
        source: Mapping[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return the effective legacy-compatible role execution view."""

        if source is None:
            source = _read_yaml(self.root / "config" / "agent_registry.yml").get("agents") or {}
        result = {
            str(name): deepcopy(dict(config))
            for name, config in source.items()
            if isinstance(config, Mapping)
            and normalize_role(name) not in self._blocked_component_roles
        }
        for item in self.roles():
            if item.source != "component_manifest":
                continue
            can_edit = bool(item.permissions.get("can_edit_source", False))
            can_shell = bool(item.permissions.get("can_run_shell", False))
            effective = deepcopy(result.get(item.display_name, {}))
            effective.update({
                "role": item.responsibility,
                "boundary": item.boundary,
                "template_path": item.template_path,
                "model_profile": effective.get("model_profile") or item.key,
                "required_inputs": list(item.required_inputs),
                "required_outputs": list(item.required_outputs),
                "can_edit_source": can_edit,
                "can_run_shell": can_shell,
                "can_write_agent_docs": False,
                "source_write_policy": item.permissions.get("source_write_policy")
                or ("supervisor_approved_files_only" if can_edit else "never"),
                "shell_policy": item.permissions.get("shell_policy")
                or ("bounded_role_session" if can_shell else "inspect_only"),
                "execution_owner": "registered_worker",
                "component_manifest": item.manifest_path,
            })
            result[item.display_name] = effective
        return result

    def merged_role_bindings(
        self,
        source: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = deepcopy(
            dict(source)
            if source is not None
            else _read_yaml(self.root / "config" / "agent_role_bindings.yml")
        )
        roles = data.setdefault("roles", {})
        workers = data.setdefault("workers", {})
        for role_name in list(roles):
            if normalize_role(role_name) in self._blocked_component_roles:
                roles.pop(role_name, None)
        for worker_config in workers.values():
            if not isinstance(worker_config, dict):
                continue
            worker_config["allowed_roles"] = [
                role
                for role in _list(worker_config.get("allowed_roles"))
                if normalize_role(role) not in self._blocked_component_roles
            ]
            forbidden = _list(worker_config.get("forbidden_roles"))
            for blocked in self._blocked_component_display_names:
                if normalize_role(blocked) not in {
                    normalize_role(role) for role in forbidden
                }:
                    forbidden.append(blocked)
            worker_config["forbidden_roles"] = forbidden
        component_roles = [item for item in self.roles() if item.source == "component_manifest"]
        for item in component_roles:
            roles[item.display_name] = {
                "allowed_workers": list(item.allowed_workers),
                "required_session": item.required_session,
                "source": "component_manifest",
            }
            for worker_name, worker_config in workers.items():
                if not isinstance(worker_config, dict):
                    continue
                allowed = _list(worker_config.get("allowed_roles"))
                forbidden = _list(worker_config.get("forbidden_roles"))
                if worker_name in item.allowed_workers:
                    if item.display_name not in allowed:
                        allowed.append(item.display_name)
                    forbidden = [role for role in forbidden if role != item.display_name]
                else:
                    allowed = [role for role in allowed if role != item.display_name]
                    if item.display_name not in forbidden:
                        forbidden.append(item.display_name)
                worker_config["allowed_roles"] = allowed
                worker_config["forbidden_roles"] = forbidden
        return data

    def validate(self) -> list[str]:
        issues = list(self.issues)
        bindings = self.merged_role_bindings()
        workers = bindings.get("workers") or {}
        for item in self.roles():
            if not item.responsibility.strip():
                issues.append(f"{item.display_name}: responsibility is missing")
            if not item.boundary.strip():
                issues.append(f"{item.display_name}: boundary is missing")
            if not item.allowed_workers:
                issues.append(f"{item.display_name}: allowed_workers is empty")
            if item.source == "component_manifest" and not (
                self.root / item.template_path
            ).is_file():
                issues.append(
                    f"{item.display_name}: generated role template is missing: "
                    f"{item.template_path}"
                )
            for worker in item.allowed_workers:
                if worker not in workers:
                    issues.append(f"{item.display_name}: unknown worker {worker}")
        return issues
