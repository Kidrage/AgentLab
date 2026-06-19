from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


def write_phase_summary(project_brain_dir: Path, phase_id: str, summary: dict) -> Path:
    out = project_brain_dir / "phase_summaries" / f"{phase_id}.md"
    lines = [
        f"# Phase Summary: {phase_id}",
        "",
        f"- verdict: {summary.get('verdict', 'unknown')}",
        f"- outputs: {', '.join(summary.get('outputs', []) or [])}",
        f"- risks: {', '.join(summary.get('risks', []) or [])}",
        f"- next_action: {summary.get('next_action', 'review')}",
        "",
        "Raw history intentionally omitted; this is a compact recovery summary.",
    ]
    atomic_write_text(out, "\n".join(lines) + "\n")
    return out


def write_snapshot(project_brain_dir: Path, name: str, payload: dict) -> Path:
    out = project_brain_dir / "snapshots" / f"{name}.yml"
    atomic_write_yaml(out, payload)
    return out
