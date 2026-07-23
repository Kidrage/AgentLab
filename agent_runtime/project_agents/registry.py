"""Explicit project Agent registry backed by canonical project truth."""

from __future__ import annotations

import re
from agent_runtime.project_truth import (
    CanonicalCommitReceipt,
    ChangeSet,
    ProjectTruthConflict,
    ProjectTruthStore,
    ResourceChange,
)

from .contract import AgentContract, AgentContractViolation, scope_matches
from .models import AgentManifest


class AgentRegistryError(RuntimeError):
    """Base project Agent registry failure."""


class AgentRegistryConflict(AgentRegistryError):
    """A duplicate, stale, or invalid manifest transition."""


_AGENT_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_STATUSES = {"active", "paused", "archived"}
_SOURCES = {"factory", "user", "recommendation"}
_PREFIX = "agents.manifest."


class ProjectAgentRegistry:
    """Expose only explicit, versioned project Agent resources."""

    def __init__(self, truth: ProjectTruthStore):
        self.truth = truth

    def register(
        self,
        manifest: AgentManifest,
        *,
        expected_snapshot_id: str,
        actor_id: str,
        source: str,
        approved: bool,
        trusted_template: bool = False,
    ) -> CanonicalCommitReceipt:
        self._validate_manifest(manifest)
        if source not in _SOURCES:
            raise AgentRegistryConflict(f"unsupported agent source {source!r}")
        if not approved and not (source == "factory" and trusted_template):
            raise AgentContractViolation(
                f"{source} agent creation requires approval"
            )
        try:
            self.get(manifest.id)
        except AgentContractViolation:
            pass
        else:
            raise AgentRegistryConflict(f"agent {manifest.id!r} already exists")
        return self._commit_manifest(
            manifest,
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
            reason=f"Register project agent from {source}.",
            idempotency_key=(
                f"agent-create:{manifest.id}:r{manifest.manifest_revision}:"
                f"{expected_snapshot_id}"
            ),
        )

    def update(
        self,
        manifest: AgentManifest,
        *,
        expected_snapshot_id: str,
        actor_id: str,
        approved: bool,
        reason: str,
    ) -> CanonicalCommitReceipt:
        self._validate_manifest(manifest)
        current = self.get(manifest.id)
        if manifest.manifest_revision != current.manifest_revision + 1:
            raise AgentRegistryConflict("manifest revision must increase by exactly one")
        if self._expands_authority(current, manifest) and not approved:
            raise AgentContractViolation("agent authority expansion requires approval")
        return self._commit_manifest(
            manifest,
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
            reason=reason,
            idempotency_key=(
                f"agent-update:{manifest.id}:r{manifest.manifest_revision}:"
                f"{expected_snapshot_id}"
            ),
        )

    def register_many(
        self,
        manifests: tuple[AgentManifest, ...],
        *,
        expected_snapshot_id: str,
        actor_id: str,
        source: str,
        approved: bool,
        trusted_template: bool = False,
    ) -> CanonicalCommitReceipt:
        """Register a complete team in one canonical compare-and-swap."""
        if not manifests:
            raise AgentRegistryConflict("agent team must not be empty")
        if len({item.id for item in manifests}) != len(manifests):
            raise AgentRegistryConflict("agent team contains duplicate ids")
        for manifest in manifests:
            self._validate_manifest(manifest)
            try:
                self.get(manifest.id)
            except AgentContractViolation:
                continue
            raise AgentRegistryConflict(f"agent {manifest.id!r} already exists")
        if source not in _SOURCES:
            raise AgentRegistryConflict(f"unsupported agent source {source!r}")
        if not approved and not (source == "factory" and trusted_template):
            raise AgentContractViolation(
                f"{source} agent creation requires approval"
            )
        try:
            return self.truth.commit(
                ChangeSet(
                    project_id=self.truth.current().project_id,
                    expected_snapshot_id=expected_snapshot_id,
                    actor_id=actor_id,
                    idempotency_key=(
                        f"agent-team-create:{source}:{expected_snapshot_id}:"
                        + ",".join(sorted(item.id for item in manifests))
                    ),
                    reason=f"Register project agent team from {source}.",
                    resources=tuple(
                        ResourceChange(
                            key=f"{_PREFIX}{manifest.id}",
                            content=manifest.to_dict(),
                        )
                        for manifest in manifests
                    ),
                )
            )
        except ProjectTruthConflict as exc:
            raise AgentRegistryConflict(str(exc)) from exc

    def get(self, agent_id: str) -> AgentManifest:
        resource = self.truth.current().resources.get(f"{_PREFIX}{agent_id}")
        if resource is None:
            raise AgentContractViolation(f"agent {agent_id!r} is not registered")
        if not isinstance(resource.content, dict):
            raise AgentRegistryConflict("stored agent manifest is malformed")
        return AgentManifest.from_dict(resource.content)

    def list(self, *, include_archived: bool = True) -> list[AgentManifest]:
        manifests = [
            AgentManifest.from_dict(resource.content)
            for key, resource in self.truth.current().resources.items()
            if key.startswith(_PREFIX) and isinstance(resource.content, dict)
        ]
        if not include_archived:
            manifests = [item for item in manifests if item.status != "archived"]
        return sorted(manifests, key=lambda item: item.id)

    def assert_can_read(self, agent_id: str, scope: str) -> None:
        AgentContract(self.get(agent_id)).assert_read(scope)

    def assert_can_write(self, agent_id: str, scope: str) -> None:
        AgentContract(self.get(agent_id)).assert_write(scope)

    def assert_can_approve(self, agent_id: str, scope: str) -> None:
        AgentContract(self.get(agent_id)).assert_approve(scope)

    def _commit_manifest(
        self,
        manifest: AgentManifest,
        *,
        expected_snapshot_id: str,
        actor_id: str,
        reason: str,
        idempotency_key: str,
    ) -> CanonicalCommitReceipt:
        try:
            return self.truth.commit(
                ChangeSet(
                    project_id=self.truth.current().project_id,
                    expected_snapshot_id=expected_snapshot_id,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    reason=reason,
                    resources=(
                        ResourceChange(
                            key=f"{_PREFIX}{manifest.id}",
                            content=manifest.to_dict(),
                        ),
                    ),
                )
            )
        except ProjectTruthConflict as exc:
            raise AgentRegistryConflict(str(exc)) from exc

    @staticmethod
    def _validate_manifest(manifest: AgentManifest) -> None:
        if not isinstance(manifest, AgentManifest):
            raise AgentRegistryConflict("manifest must use AgentManifest schema")
        if not _AGENT_ID.fullmatch(manifest.id):
            raise AgentRegistryConflict("agent id must be stable lowercase identifier")
        required = {
            "name": manifest.name,
            "version": manifest.version,
            "role": manifest.role,
            "description": manifest.description,
            "runtime_role": manifest.runtime_role,
            "model_profile": manifest.model_profile,
            "budget_profile": manifest.budget_profile,
        }
        if any(not value.strip() for value in required.values()):
            raise AgentRegistryConflict("manifest identity and runtime fields are required")
        if manifest.status not in _STATUSES:
            raise AgentRegistryConflict(f"invalid agent status {manifest.status!r}")
        if manifest.manifest_revision < 1:
            raise AgentRegistryConflict("manifest revision must be positive")
        for scope in (
            *manifest.read_scope,
            *manifest.write_scope,
            *manifest.approval_scope,
        ):
            if not scope or any(character in scope for character in "\0\n\r"):
                raise AgentRegistryConflict("agent scopes must be non-empty single lines")

    @staticmethod
    def _expands_authority(
        previous: AgentManifest, candidate: AgentManifest
    ) -> bool:
        return any(
            not any(scope_matches(old, new) for old in previous_scopes)
            for previous_scopes, candidate_scopes in (
                (previous.read_scope, candidate.read_scope),
                (previous.write_scope, candidate.write_scope),
                (previous.approval_scope, candidate.approval_scope),
            )
            for new in candidate_scopes
        ) or bool(set(candidate.tool_permission) - set(previous.tool_permission))
