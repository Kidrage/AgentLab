from __future__ import annotations

from pathlib import Path
import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


def write_phase_summary(project_brain_dir: Path, phase_id: str, summary: dict) -> Path:
    """Generate and write a compact phase summary MD file."""
    # Write to both directories for compatibility (phase_summaries/phase_id.md and phase_summaries/phase_id_summary.md)
    summaries_dir = project_brain_dir / "phase_summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Phase Summary: {phase_id}",
        "",
        f"- verdict: {summary.get('verdict', 'unknown')}",
        f"- outputs: {', '.join(summary.get('outputs', []) or [])}",
        f"- risks: {', '.join(summary.get('risks', []) or [])}",
        f"- next_action: {summary.get('next_action', summary.get('recommended_next_action', 'review'))}",
        "",
        "Raw history intentionally omitted; this is a compact recovery summary.",
    ]
    md_content = "\n".join(lines) + "\n"

    # Write multiple naming patterns for safety
    out1 = summaries_dir / f"{phase_id}.md"
    out2 = summaries_dir / f"{phase_id}_summary.md"
    atomic_write_text(out1, md_content)
    atomic_write_text(out2, md_content)

    return out1


def write_snapshot(project_brain_dir: Path, name: str, payload: dict) -> Path:
    """Write project state snapshot to context_snapshots/ and snapshots/."""
    snapshots_dir = project_brain_dir / "snapshots"
    context_snapshots_dir = project_brain_dir / "context_snapshots"

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    context_snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Normalize name (e.g. 001 -> snapshot_001)
    filename = f"{name}.yml" if name.endswith(".yml") else f"{name}.yml"
    if not filename.startswith("snapshot_") and filename != "initial.yml":
        filename = f"snapshot_{filename}"

    out1 = snapshots_dir / filename
    out2 = context_snapshots_dir / filename

    atomic_write_yaml(out1, payload)
    atomic_write_yaml(out2, payload)

    return out1


def build_project_snapshot(project_brain_dir: Path) -> dict:
    """Load and compile all project memory states into a single snapshot dict."""
    state = {}
    
    # Files to include in the snapshot
    state_files = {
        "project_brief": "project_brief.yml",
        "roadmap": "roadmap.yml",
        "milestone_graph": "milestone_graph.yml",
        "decision_log": "decision_log.yml",
        "acceptance_history": "acceptance_history.yml",
        "unresolved_questions": "unresolved_questions.yml",
        "known_risks": "known_risks.yml",
        "architecture_state": "architecture_state.yml",
        "current_phase": "current_phase.yml",
    }

    for key, filename in state_files.items():
        file_path = project_brain_dir / filename
        if file_path.exists():
            try:
                state[key] = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
            except Exception:
                state[key] = {}
        else:
            state[key] = {}

    return state


def compact_project_memory(project_brain_dir: Path) -> dict:
    """Compact append-only logs and remove temporary items to maintain memory hygiene."""
    # Ensure decision log is cleaned and compacted
    decision_log_path = project_brain_dir / "decision_log.yml"
    if decision_log_path.exists():
        try:
            data = yaml.safe_load(decision_log_path.read_text(encoding="utf-8")) or {"entries": []}
            # Deduplicate entries by unique ID if present
            seen = set()
            deduped = []
            for entry in data.get("entries") or []:
                entry_key = entry.get("decision_id") or str(entry)
                if entry_key not in seen:
                    seen.add(entry_key)
                    deduped.append(entry)
            atomic_write_yaml(decision_log_path, {"entries": deduped})
        except Exception:
            pass

    return {"status": "memory_compacted"}
