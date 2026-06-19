from __future__ import annotations


def build_milestone_graph(roadmap: dict) -> dict:
    milestones = roadmap.get("milestones") or []
    edges = []
    for index in range(len(milestones) - 1):
        edges.append(
            {
                "from": milestones[index]["milestone_id"],
                "to": milestones[index + 1]["milestone_id"],
                "condition": "previous_phase_accepted",
            }
        )
    return {"nodes": milestones, "edges": edges, "resume_safe": True}
