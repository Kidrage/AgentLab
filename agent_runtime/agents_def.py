"""Placeholder agent definitions for AgentLab Phase 2A."""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    template_path: Path
    can_edit_source: bool = False


def build_agent_specs(agentlab_root: Path) -> list[AgentSpec]:
    """Return reusable agent specs without constructing live LLM agents yet."""
    templates = agentlab_root / "agent_templates"
    return [
        AgentSpec("Supervisor", "Plans and coordinates the task", templates / "supervisor.md"),
        AgentSpec("RepoScout", "Maps repository context", templates / "reposcout.md"),
        AgentSpec("Coder", "Proposes minimal implementation changes", templates / "coder.md"),
        AgentSpec("TesterAuditor", "Validates and audits results", templates / "tester_auditor.md"),
        AgentSpec("Archivist", "Updates run records and project memory", templates / "archivist.md"),
        AgentSpec("Researcher", "Collects external or reference context", templates / "researcher.md"),
        AgentSpec("InterfaceMapper", "Tracks boundaries and contracts", templates / "interface_mapper.md"),
    ]


def agent_names(specs: Iterable[AgentSpec]) -> list[str]:
    return [spec.name for spec in specs]
