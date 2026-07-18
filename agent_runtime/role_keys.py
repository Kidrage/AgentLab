"""Canonical AgentLab role-key normalization.

Role names appear as public PascalCase names, profile snake_case keys, and a
small set of CLI aliases. Keep that translation in one dependency-free module
so registries, matrix generation, and runtime dispatch cannot drift apart.
"""

from __future__ import annotations


ROLE_KEY_TO_CANONICAL = {
    "supervisor": "Supervisor",
    "reposcout": "RepoScout",
    "researcher": "Researcher",
    "observer": "Observer",
    "interface_mapper": "InterfaceMapper",
    "prompt_engineer": "PromptEngineer",
    "coder": "Coder",
    "artifact_producer": "ArtifactProducer",
    "narrative_planner": "NarrativePlanner",
    "writer": "Writer",
    "reviewer": "Reviewer",
    "visual_reviewer": "Reviewer",
    "scribe": "Scribe",
    "tester_auditor": "TesterAuditor",
    "verifier": "Verifier",
    "archivist": "Archivist",
}

_COMPACT_ALIASES = {
    "reposcout": "reposcout",
    "researcher": "researcher",
    "observer": "observer",
    "interfacemapper": "interface_mapper",
    "promptengineer": "prompt_engineer",
    "artifactproducer": "artifact_producer",
    "narrativeplanner": "narrative_planner",
    "visualreviewer": "visual_reviewer",
    "testerauditor": "tester_auditor",
}

CAPACITY_ROLE_ALIASES = {"visual_reviewer": "reviewer"}


def normalize_role_key(role: str) -> str:
    """Return the profile key for a public role name or CLI alias."""
    key = str(role or "").strip().replace("-", "_").replace(" ", "_").lower()
    if key in ROLE_KEY_TO_CANONICAL:
        return key
    return _COMPACT_ALIASES.get(key.replace("_", ""), key)


def canonical_role_name(role: str) -> str:
    """Return the public role name, preserving unknown names for diagnostics."""
    key = normalize_role_key(role)
    return ROLE_KEY_TO_CANONICAL.get(key, str(role))


def capacity_role_key(role: str) -> str:
    """Return the capacity-policy key for a profile role."""
    key = normalize_role_key(role)
    return CAPACITY_ROLE_ALIASES.get(key, key)
