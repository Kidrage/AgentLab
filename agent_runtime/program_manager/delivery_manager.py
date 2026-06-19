from __future__ import annotations


def build_delivery_manifest(project_brain_dir: str, acceptance_history: dict) -> dict:
    return {
        "project_brain_dir": project_brain_dir,
        "accepted_phases": [
            item.get("phase_id") for item in acceptance_history.get("entries") or [] if item.get("accepted")
        ],
        "delivery_ready": all(item.get("accepted") for item in acceptance_history.get("entries") or []),
        "required_package_files": [
            "final_summary.md",
            "artifacts/",
            "evidence/",
            "acceptance_history.md",
            "risks_and_limitations.md",
            "reproduction_commands.md",
            "next_steps.md",
        ],
    }
