"""Restricted project-memory writer for Archivist reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path

import yaml

from atomic_io import atomic_write_text
from config_loader import load_agentlab_configs
from patch_applicator import AppliedEdit, apply_all_patches, parse_edit_blocks, strip_edit_blocks_from_report


@dataclass
class MemoryWriteResult:
    edit_blocks_found: int
    applied: int
    failed: int
    results: list[AppliedEdit]
    allowed_files: list[str]
    fallback_applied: bool = False
    fallback_path: str | None = None
    mirror_path: str | None = None
    mirror_error: str | None = None

    @property
    def ok(self) -> bool:
        return (self.applied > 0 or self.fallback_applied) and self.failed == 0

    @property
    def error(self) -> str | None:
        if self.edit_blocks_found == 0 and not self.fallback_applied:
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def remote_repo_root(agentlab_root: Path) -> Path | None:
    """Resolve optional SMB/NFS mounted AgentLab mirror root.

    Local project memory remains authoritative. If the user mounts a remote
    repository, AgentLab can mirror durable memory writes there by setting
    `AGENTLAB_REMOTE_REPO_ROOT`; otherwise it uses the configured TrueNAS mount
    only when that mount already exists.
    """
    env_path = os.getenv("AGENTLAB_REMOTE_REPO_ROOT") or os.getenv("AGENTLAB_REMOTE_AGENTLAB_ROOT")
    if env_path:
        return Path(env_path).expanduser()

    configs = load_agentlab_configs(agentlab_root)
    mount_path = (
        configs.get("backup_policy", {})
        .get("targets", {})
        .get("truenas", {})
        .get("mount_path")
    )
    if mount_path:
        candidate = Path(str(mount_path)).expanduser()
        if candidate.exists():
            return candidate
    return None


def mirror_memory_file(agentlab_root: Path, local_path: Path) -> tuple[str | None, str | None]:
    """Best-effort mirror of one memory file to SMB/NFS remote repo root."""
    root = remote_repo_root(agentlab_root)
    if root is None:
        return None, None
    try:
        relative = local_path.resolve().relative_to(agentlab_root.resolve())
        target = root / relative
        atomic_write_text(target, local_path.read_text(encoding="utf-8"))
        return str(target), None
    except Exception as exc:
        return None, str(exc)


def fallback_memory_entry(project_root: Path, llm_output: str) -> str:
    report = strip_edit_blocks_from_report(llm_output).strip() or "(empty Archivist report)"
    if len(report) > 1600:
        report = report[:1600].rstrip() + "\n... (truncated)"
    return (
        f"\n## {utc_now()} - Archivist fallback memory write\n\n"
        "- Status: fallback_applied\n"
        "- Reason: Archivist output did not include structured AGENTLAB_EDIT blocks.\n"
        "- Safety: appended only to approved project memory file `agent_docs/07_DEVELOPMENT_LOG.md`.\n"
        f"- Project: {project_root.name}\n\n"
        "### Archivist report excerpt\n\n"
        f"{report}\n"
    )


def apply_fallback_memory_write(agentlab_root: Path, project_root: Path, llm_output: str, allowed: set[str]) -> MemoryWriteResult:
    """Append a durable fallback memory entry when Archivist omits edit blocks."""
    target_rel = "agent_docs/07_DEVELOPMENT_LOG.md"
    if target_rel not in allowed:
        return MemoryWriteResult(
            0,
            0,
            1,
            [AppliedEdit(path=target_rel, success=False, error="Fallback memory file is not allowed by memory_policy.yml")],
            sorted(allowed),
        )

    target = project_root / target_rel
    existing = target.read_text(encoding="utf-8") if target.exists() else "# Development Log\n"
    atomic_write_text(target, existing.rstrip() + "\n" + fallback_memory_entry(project_root, llm_output))
    mirror_path, mirror_error = mirror_memory_file(agentlab_root, target)
    return MemoryWriteResult(
        0,
        1,
        0,
        [AppliedEdit(path=target_rel, success=True, matched_count=1)],
        sorted(allowed),
        fallback_applied=True,
        fallback_path=str(target),
        mirror_path=mirror_path,
        mirror_error=mirror_error,
    )


def _apply_html_yaml_merge(project_root: Path, file_path: str, html_content: str, allowed: set[str]) -> AppliedEdit:
    """Handle an HTML-style edit block containing YAML for a .yml memory file.

    The html_content is expected to be pure YAML (possibly wrapped in ```yaml fences).
    The content is treated as a new top-level key to merge into the existing YAML file.
    """
    normalized_path = file_path.lstrip("/")
    if normalized_path not in allowed:
        return AppliedEdit(path=normalized_path, success=False,
                           error=f"File not allowed for memory writes: {normalized_path}")

    target = project_root / normalized_path
    try:
        if not target.exists():
            return AppliedEdit(path=normalized_path, success=False,
                               error=f"Memory file does not exist: {target}")
        existing_text = target.read_text(encoding="utf-8")
    except Exception as exc:
        return AppliedEdit(path=normalized_path, success=False, error=f"Read error: {exc}")

    # Strip optional ```yaml / ``` fences
    content = html_content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        # Remove first fence line (```yaml or ```)
        if lines:
            lines = lines[1:]
        # Remove last fence line if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        new_data = yaml.safe_load(content)
    except Exception as exc:
        return AppliedEdit(path=normalized_path, success=False,
                           error=f"YAML parse error in HTML edit block: {exc}")

    if not isinstance(new_data, dict):
        return AppliedEdit(path=normalized_path, success=False,
                           error="HTML edit block content is not a YAML mapping")

    try:
        existing_data = yaml.safe_load(existing_text) or {}
    except Exception as exc:
        return AppliedEdit(path=normalized_path, success=False,
                           error=f"Could not parse existing YAML: {exc}")

    if not isinstance(existing_data, dict):
        return AppliedEdit(path=normalized_path, success=False,
                           error=f"Existing {normalized_path} is not a YAML mapping")

    # Deep-merge: new keys override existing ones
    def deep_merge(base: dict, overlay: dict) -> dict:
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    merged = deep_merge(existing_data, new_data)
    try:
        atomic_write_text(target, yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))
    except Exception as exc:
        return AppliedEdit(path=normalized_path, success=False, error=f"Write error: {exc}")

    return AppliedEdit(path=normalized_path, success=True, matched_count=1)


def apply_archivist_memory_edits(agentlab_root: Path, project_root: Path, llm_output: str) -> MemoryWriteResult:
    """Apply Archivist AGENTLAB_EDIT blocks only to approved agent_docs files.

    Handles two block formats:
    - <<<AGENTLAB_EDIT path >>> with SEARCH/REPLACE pairs (for all files)
    - <!-- AGENTLAB_EDIT: path --> with YAML content (for .yml files — deep merge)
    """
    blocks = parse_edit_blocks(llm_output)
    allowed = allowed_memory_files(agentlab_root)

    # Detect HTML-style blocks separately before parse_edit_blocks consumes them
    # (parse_edit_blocks already extracts both formats)
    html_blocks = [b for b in blocks if "html_block_content" in b]
    sr_blocks = [b for b in blocks if "html_block_content" not in b]

    if not blocks:
        return apply_fallback_memory_write(agentlab_root, project_root, llm_output, allowed)

    results: list[AppliedEdit] = []

    # Process standard SEARCH/REPLACE blocks
    if sr_blocks:
        sr_results = apply_all_patches(
            llm_output=llm_output,
            project_root=project_root,
            allowed_files=allowed,
        )
        results.extend(sr_results)

    # Process HTML-style blocks (YAML merge for .yml files)
    for block in html_blocks:
        result = _apply_html_yaml_merge(
            project_root, block["path"], block["html_block_content"], allowed
        )
        results.append(result)

    applied = len([r for r in results if r.success])
    failed = len([r for r in results if not r.success])
    mirror_path = None
    mirror_error = None
    for result in results:
        if result.success:
            mirrored, error = mirror_memory_file(agentlab_root, project_root / result.path)
            mirror_path = mirror_path or mirrored
            mirror_error = mirror_error or error
    return MemoryWriteResult(len(blocks), applied, failed, results, sorted(allowed), mirror_path=mirror_path, mirror_error=mirror_error)


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
    if summary.fallback_applied:
        lines.append(f"- Fallback memory write: applied ({summary.fallback_path})")
    if summary.mirror_path:
        lines.append(f"- Remote mirror: {summary.mirror_path}")
    if summary.mirror_error:
        lines.append(f"- Remote mirror warning: {summary.mirror_error}")
    if summary.error:
        lines.append(f"- Blocking reason: {summary.error}")
    return "\n".join(lines) + "\n"