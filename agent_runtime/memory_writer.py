"""Restricted project-memory writer for Archivist reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config_loader import load_agentlab_configs
from patch_applicator import AppliedEdit, apply_all_patches, parse_edit_blocks


@dataclass
class MemoryWriteResult:
    edit_blocks_found: int
    applied: int
    failed: int
    results: list[AppliedEdit]
    allowed_files: list[str]

    @property
    def ok(self) -> bool:
        return self.edit_blocks_found > 0 and self.applied > 0 and self.failed == 0

    @property
    def error(self) -> str | None:
        if self.edit_blocks_found == 0:
            return "Archivist did not provide structured AGENTLAB_EDIT blocks for agent_docs."
        if self.applied == 0:
            return "Archivist memory edits were not applied."
        if self.failed:
            return "One or more Archivist memory edits failed."
        return None


def allowed_memory_files(agentlab_root: Path) -> set[str]:
    configs = load_agentlab_configs(agentlab_root)
    records = configs.get("memory_policy", {}).get("records", {})
    configured = records.get("project_memory", []) or []
    allowed = {f"agent_docs/{str(name).lstrip('/')}" for name in configured}
    if allowed:
        return allowed
    return {
        "agent_docs/00_CONTEXT_PACK.md",
        "agent_docs/01_REPO_MAP.md",
        "agent_docs/02_TASK_LEDGER.yml",
        "agent_docs/03_DECISION_LOG.md",
        "agent_docs/04_INTERFACE_REGISTRY.md",
        "agent_docs/05_CHANGELOG_AGENT.md",
        "agent_docs/06_RISK_REGISTER.md",
        "agent_docs/07_DEVELOPMENT_LOG.md",
        "agent_docs/08_CODEX_DIALOGUE_LOG.md",
        "agent_docs/09_COST_LEDGER.yml",
        "agent_docs/10_SYNC_LEDGER.yml",
    }


def apply_archivist_memory_edits(agentlab_root: Path, project_root: Path, llm_output: str) -> MemoryWriteResult:
    """Apply Archivist AGENTLAB_EDIT blocks only to approved agent_docs files."""
    blocks = parse_edit_blocks(llm_output)
    allowed = allowed_memory_files(agentlab_root)
    if not blocks:
        return MemoryWriteResult(0, 0, 0, [], sorted(allowed))

    results = apply_all_patches(
        llm_output=llm_output,
        project_root=project_root,
        allowed_files=allowed,
    )
    applied = len([r for r in results if r.success])
    failed = len([r for r in results if not r.success])
    return MemoryWriteResult(len(blocks), applied, failed, results, sorted(allowed))


def format_memory_write_section(summary: MemoryWriteResult) -> str:
    lines = [
        "## Memory Application Results",
        "",
        f"- Structured edit blocks found: {summary.edit_blocks_found}",
        f"- Agent_docs edits applied: {summary.applied}",
        f"- Agent_docs edits failed: {summary.failed}",
    ]
    if summary.results:
        lines.append("- Results:")
        for result in summary.results:
            status = "applied" if result.success else "failed"
            detail = result.warning or result.error or f"matches={result.matched_count}"
            lines.append(f"  - {result.path}: {status} ({detail})")
    if summary.error:
        lines.append(f"- Blocking reason: {summary.error}")
    return "\n".join(lines) + "\n"
