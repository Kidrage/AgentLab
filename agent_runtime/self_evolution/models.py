"""Schemas and validation for governed component manifests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import re
from typing import Any, Mapping

import yaml


SUPPORTED_KINDS = {
    "agent_role",
    "worker_binding",
    "skill",
    "route_pack",
    "runtime_adapter",
    "core_module",
}
ACTIVE_STATUSES = {"active", "candidate", "inactive"}
MATERIALIZABLE_KINDS = {"agent_role"}
RESERVED_RUN_CONTROL_ARTIFACTS = {
    "01_supervisor_plan.md",
    "07_validation_report.md",
    "08_audit_report.md",
    "09_archive_update.md",
    "USER_DECISION_REQUIRED.md",
    "artifact_manifest.yml",
    "artifact_lineage.yml",
    "artifact_promotion_plan.yml",
    "archive_receipt.yml",
    "brain_decisions.yml",
    "compression_trace.yml",
    "context_budget.yml",
    "context_pack.yml",
    "context_profile.yml",
    "cost_ledger.yml",
    "execution_log.yml",
    "lifecycle.yml",
    "mission_contract.yml",
    "progress.yml",
    "repo_manifest.json",
    "resource_ledger.yml",
    "self_check_report.yml",
    "state.yml",
    "supervisor_plan.md",
    "sync_report.yml",
    "task_card.yml",
    "task_snapshot.yml",
    "user_request.md",
    "verification_report.md",
    "workflow_plan.yml",
}
COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)$",
    re.IGNORECASE,
)
FORBIDDEN_ROLE_PERMISSION_KEYS = {
    "auto_merge",
    "credential_management",
    "direct_production_write",
    "install_provider",
    "register_provider",
    "secret_access",
}
DECLARED_PERMISSION_KEYS = FORBIDDEN_ROLE_PERMISSION_KEYS | {
    "can_edit_source",
    "can_run_shell",
    "dependencies",
    "external_write",
    "network",
    "shell_policy",
    "source_write_policy",
}


class ManifestValidationError(ValueError):
    """Raised when a component manifest cannot enter the evolution lifecycle."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = list(issues)
        super().__init__("invalid component manifest: " + "; ".join(self.issues))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _validate_relative_path(value: str, field_name: str, issues: list[str]) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        issues.append(f"{field_name} must be a safe relative path")


def _scan_for_secrets(value: Any, path: tuple[str, ...], issues: list[str]) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_for_secrets(item, (*path, str(index)), issues)
        return
    if not isinstance(value, Mapping):
        return
    for key, item in value.items():
        key_text = str(key)
        nested = (*path, key_text)
        if SECRET_KEY_RE.search(key_text) and item not in (None, "", "user_managed"):
            issues.append("inline secret is forbidden at " + ".".join(nested))
        _scan_for_secrets(item, nested, issues)


@dataclass(frozen=True, slots=True)
class ComponentManifest:
    """Canonical declarative contract for one evolvable AgentLab component."""

    data: dict[str, Any]
    source_path: Path | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        source_path: Path | None = None,
        validate: bool = True,
    ) -> "ComponentManifest":
        manifest = cls(deepcopy(dict(value)), source_path=source_path)
        if validate:
            manifest.require_valid()
        return manifest

    @classmethod
    def load(cls, path: Path, *, validate: bool = True) -> "ComponentManifest":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, Mapping):
            raise ManifestValidationError(["manifest root must be a mapping"])
        return cls.from_mapping(raw, source_path=Path(path), validate=validate)

    @property
    def api_version(self) -> str:
        return str(self.data.get("api_version") or "")

    @property
    def kind(self) -> str:
        return str(self.data.get("kind") or "")

    @property
    def metadata(self) -> dict[str, Any]:
        return _mapping(self.data.get("metadata"))

    @property
    def spec(self) -> dict[str, Any]:
        return _mapping(self.data.get("spec"))

    @property
    def component_id(self) -> str:
        return str(self.metadata.get("id") or "")

    @property
    def display_name(self) -> str:
        return str(self.metadata.get("display_name") or self.component_id)

    @property
    def version(self) -> str:
        return str(self.metadata.get("version") or "")

    @property
    def status(self) -> str:
        return str(self.metadata.get("status") or "candidate")

    @property
    def replaces_legacy(self) -> bool:
        return bool(self.metadata.get("replaces_legacy", False))

    @property
    def materializer_available(self) -> bool:
        return self.kind in MATERIALIZABLE_KINDS

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.data,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def with_status(self, status: str) -> "ComponentManifest":
        data = deepcopy(self.data)
        data.setdefault("metadata", {})["status"] = status
        return ComponentManifest.from_mapping(data, source_path=self.source_path)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.data)

    def validation_issues(self) -> list[str]:
        issues: list[str] = []
        if self.api_version != "agentlab/v1":
            issues.append("api_version must be agentlab/v1")
        if self.kind not in SUPPORTED_KINDS:
            issues.append(f"unsupported component kind: {self.kind or '<missing>'}")
        if not COMPONENT_ID_RE.fullmatch(self.component_id):
            issues.append("metadata.id must be lower_snake_case with 3-64 characters")
        if not self.display_name.strip():
            issues.append("metadata.display_name is required")
        if not VERSION_RE.fullmatch(self.version):
            issues.append("metadata.version must be semantic version x.y.z")
        if self.status not in ACTIVE_STATUSES:
            issues.append(f"unsupported metadata.status: {self.status}")
        if not self.spec:
            issues.append("spec is required")
        _scan_for_secrets(self.data, (), issues)
        self._validate_permissions(issues)
        if self.kind == "agent_role":
            self._validate_agent_role(issues)
        else:
            self._validate_proposal_only_component(issues)
        return issues

    def _validate_agent_role(self, issues: list[str]) -> None:
        spec = self.spec
        for field_name in ("responsibility", "boundary", "template_path", "default_report"):
            if not str(spec.get(field_name) or "").strip():
                issues.append(f"spec.{field_name} is required for agent_role")
        for field_name in ("template_path", "default_report"):
            value = str(spec.get(field_name) or "")
            if value:
                _validate_relative_path(value, f"spec.{field_name}", issues)
        template_path = PurePosixPath(str(spec.get("template_path") or ""))
        if template_path.parts and (
            template_path.parts[0] != "agent_templates" or template_path.suffix != ".md"
        ):
            issues.append("spec.template_path must reference agent_templates/*.md")
        init_artifacts = _mapping(spec.get("init_artifacts"))
        for name in init_artifacts:
            _validate_relative_path(str(name), f"spec.init_artifacts.{name}", issues)
        default_report = str(spec.get("default_report") or "")
        if default_report and default_report not in init_artifacts:
            issues.append("spec.init_artifacts must declare spec.default_report")

        artifacts = _mapping(spec.get("artifacts"))
        outputs = _string_list(artifacts.get("outputs"))
        if not outputs:
            issues.append("spec.artifacts.outputs must not be empty")
        elif len(outputs) != 1:
            issues.append(
                "v1 agent_role materialization supports exactly one output artifact"
            )
        for index, path in enumerate(_string_list(artifacts.get("inputs")) + outputs):
            _validate_relative_path(path, f"spec.artifacts[{index}]", issues)
        if default_report and default_report not in {Path(path).name for path in outputs}:
            issues.append("spec.default_report must match one declared output basename")
        if len(outputs) == 1:
            output_parts = PurePosixPath(outputs[0]).parts
            if (
                len(output_parts) != 3
                or output_parts[:2] != ("runs", "task_xxxx")
                or output_parts[-1] != default_report
            ):
                issues.append(
                    "v1 agent_role output must be runs/task_xxxx/<default_report>"
                )
            if output_parts and output_parts[-1] in RESERVED_RUN_CONTROL_ARTIFACTS:
                issues.append(
                    "agent_role output collides with a reserved run-control artifact"
                )
        if default_report and set(init_artifacts) != {default_report}:
            issues.append(
                "v1 agent_role init_artifacts must contain only spec.default_report"
            )

        role_requirements = _mapping(spec.get("role_requirements"))
        if not _string_list(role_requirements.get("required_capabilities")):
            issues.append("spec.role_requirements.required_capabilities must not be empty")

        worker_binding = _mapping(spec.get("worker_binding"))
        allowed_workers = _string_list(worker_binding.get("allowed_workers"))
        if not allowed_workers:
            issues.append("spec.worker_binding.allowed_workers must not be empty")
        if worker_binding.get("required_session") is not True:
            issues.append("spec.worker_binding.required_session must be true")
        invocation_contracts = _mapping(worker_binding.get("invocation_contracts"))
        for worker in allowed_workers:
            if not str(invocation_contracts.get(worker) or "").strip():
                issues.append(
                    f"spec.worker_binding.invocation_contracts.{worker} is required"
                )

        runtime_demand = _mapping(spec.get("runtime_demand"))
        weights = _mapping(runtime_demand.get("capability_weights"))
        if not weights:
            issues.append("spec.runtime_demand.capability_weights must not be empty")
        for name, value in weights.items():
            try:
                score = float(value)
            except (TypeError, ValueError):
                issues.append(f"runtime capability weight {name!r} must be numeric")
                continue
            if score <= 0:
                issues.append(f"runtime capability weight {name!r} must be positive")
        try:
            quality_floor = float(runtime_demand.get("quality_floor", 0.82))
        except (TypeError, ValueError):
            issues.append("spec.runtime_demand.quality_floor must be numeric")
        else:
            if not 0 < quality_floor <= 1:
                issues.append("spec.runtime_demand.quality_floor must be in (0, 1]")
        for field_name in ("predicted_input_tokens", "predicted_output_tokens"):
            if field_name not in runtime_demand:
                continue
            try:
                token_count = int(runtime_demand[field_name])
            except (TypeError, ValueError):
                issues.append(f"spec.runtime_demand.{field_name} must be an integer")
            else:
                if token_count < 0:
                    issues.append(f"spec.runtime_demand.{field_name} must not be negative")
        forbidden_runtime_keys = {"model", "model_id", "provider", "provider_id", "api_key"}
        direct_runtime_keys = forbidden_runtime_keys & set(runtime_demand)
        if direct_runtime_keys:
            issues.append(
                "runtime demand must not hardcode models or providers: "
                + ", ".join(sorted(direct_runtime_keys))
            )

    def _validate_permissions(self, issues: list[str]) -> None:
        permissions = _mapping(self.spec.get("permissions"))
        unknown = sorted(set(permissions) - DECLARED_PERMISSION_KEYS)
        if unknown:
            issues.append("unsupported permission keys: " + ", ".join(unknown))
        for key in FORBIDDEN_ROLE_PERMISSION_KEYS:
            if permissions.get(key) not in (None, False):
                issues.append(f"spec.permissions.{key} must be false for self-evolution")
        elevated = any(
            permissions.get(key) not in (None, False, [], {})
            for key in ("network", "external_write", "dependencies")
        )
        if elevated and not str(self.metadata.get("security_approval_ref") or "").strip():
            issues.append("elevated permissions require metadata.security_approval_ref")
        source_write_policy = permissions.get("source_write_policy")
        allowed_write_policies = {
            None,
            "never",
            "supervisor_approved_files_only",
            "artifact_contract_outputs_only",
        }
        if source_write_policy not in allowed_write_policies:
            issues.append("spec.permissions.source_write_policy is unsupported")
        if not permissions.get("can_edit_source", False) and source_write_policy not in {
            None,
            "never",
        }:
            issues.append("source_write_policy must be never when can_edit_source is false")

    def _validate_proposal_only_component(self, issues: list[str]) -> None:
        if not str(self.spec.get("objective") or "").strip():
            issues.append("spec.objective is required for proposal-only components")
        if not isinstance(self.spec.get("interfaces"), Mapping):
            issues.append("spec.interfaces mapping is required for proposal-only components")
        if not isinstance(self.spec.get("validation"), Mapping):
            issues.append("spec.validation mapping is required for proposal-only components")

    def require_valid(self) -> None:
        issues = self.validation_issues()
        if issues:
            raise ManifestValidationError(issues)
