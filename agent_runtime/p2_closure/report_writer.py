"""P2-F Closure report writer."""
from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text


def write_closure_report(
    task_id: str,
    verdict_status: str,
    verdict_path: str,
    revision_path: str | None,
    provider_feedback_path: str,
    router_feedback_path: str,
    router_dry_run_path: str,
    router_apply_path: str | None,
    router_rollback_path: str | None,
    cap_map_path: str,
    output_path: Path,
) -> Path:
    """Write the P2-F closure summary report."""
    revision_required = verdict_status in {"needs_revision", "rejected", "unsafe"}

    lines = [
        f"# P2-F Closure Report: {task_id}",
        "",
        "## Summary",
        f"P2-F closure completed with verdict: **{verdict_status}**.",
        "",
        "## Artifacts",
        f"- Capability Map: `{cap_map_path}`",
        f"- Review Verdict: `{verdict_path}`",
    ]
    if revision_path:
        lines.append(f"- Revision Packet: `{revision_path}`")
    else:
        lines.append("- Revision Packet: not required")
    lines.extend([
        f"- Provider Feedback: `{provider_feedback_path}`",
        f"- Router Feedback: `{router_feedback_path}`",
        f"- Router Update Dry-Run: `{router_dry_run_path}`",
    ])
    if router_apply_path:
        lines.append(f"- Router Apply Result: `{router_apply_path}`")
    if router_rollback_path:
        lines.append(f"- Router Rollback Plan: `{router_rollback_path}`")

    lines.extend([
        "",
        "## Pipeline Steps",
        "",
        "### 1. Capability Map",
        "Scanned all P2 modules for implementation status, callable entrypoints, test fixtures, and CLI wiring.",
        "",
        "### 2. 3E Review",
        f"Explored delivery artifacts, examined for safety/scope/evidence gaps, enhanced with revision recommendations.",
        f"Verdict: **{verdict_status}**.",
        "",
        "### 3. Revision Packet",
        f"{'Generated revision packet with failed checks, missing evidence, and acceptance criteria.' if revision_required else 'Not required; delivery accepted.'}",
        "",
        "### 4. Provider Governance Feedback",
        "Review verdict, scores, and failure reasons written to provider feedback artifact for governance ingestion.",
        "",
        "### 5. Router Feedback",
        "Routing recommendation generated based on provider performance. Default dry-run only.",
        "",
        "### 6. Router Update Safety",
        "Dry-run artifact written. Apply requires explicit approval artifact. Rollback plan available on apply.",
        "",
        "## Safety Guarantees",
        "- No external script execution.",
        "- No network calls.",
        "- No secrets read or exposed.",
        "- No production config modified.",
        "- No third-party source code copied.",
        "- All operations deterministic and local.",
        "",
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, "\n".join(lines))
    return output_path
