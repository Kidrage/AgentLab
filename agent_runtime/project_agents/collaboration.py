"""Reusable expert collaboration DAGs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CollaborationNode:
    id: str
    agent_id: str
    kind: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollaborationPlan:
    domain: str
    nodes: tuple[CollaborationNode, ...]


_PLANS = {
    "narrative": (
        CollaborationNode("world-check", "world", "expert-check"),
        CollaborationNode("character-check", "character", "expert-check"),
        CollaborationNode("timeline-check", "timeline", "expert-check"),
        CollaborationNode("foreshadow-check", "foreshadow", "expert-check"),
        CollaborationNode(
            "writer",
            "writer",
            "production",
            (
                "world-check",
                "character-check",
                "timeline-check",
                "foreshadow-check",
            ),
        ),
        CollaborationNode("checker", "checker", "verification", ("writer",)),
        CollaborationNode("reviewer", "reviewer", "review", ("checker",)),
    ),
    "software": (
        CollaborationNode("architecture", "architecture", "expert-check"),
        CollaborationNode("coder", "coder", "production", ("architecture",)),
        CollaborationNode("test", "test", "verification", ("coder",)),
        CollaborationNode("security", "security", "expert-check", ("coder",)),
        CollaborationNode(
            "reviewer", "reviewer", "review", ("test", "security")
        ),
    ),
    "audio": (
        CollaborationNode("dsp", "dsp", "expert-check"),
        CollaborationNode("mix", "mix", "production", ("dsp",)),
        CollaborationNode(
            "listener-qa", "listener_qa", "verification", ("mix",)
        ),
        CollaborationNode(
            "reviewer", "reviewer", "review", ("listener-qa",)
        ),
    ),
    "generic": (
        CollaborationNode("domain-check", "domain_expert", "expert-check"),
        CollaborationNode(
            "producer", "producer", "production", ("domain-check",)
        ),
        CollaborationNode("reviewer", "reviewer", "review", ("producer",)),
    ),
}


class ExpertCollaborationPlanner:
    def plan(
        self,
        domain: str,
        *,
        available_agent_ids: Iterable[str] | None = None,
    ) -> CollaborationPlan:
        normalized = domain.casefold()
        if normalized in {"code", "coding", "software", "code_engineering"}:
            normalized = "software"
        elif normalized in {"novel", "story", "longform_narrative"}:
            normalized = "narrative"
        elif normalized not in _PLANS:
            normalized = "generic"
        nodes = list(_PLANS[normalized])
        if normalized == "narrative" and available_agent_ids is not None:
            available = set(available_agent_ids)
            specialist_nodes = tuple(
                node
                for node in (
                    CollaborationNode(
                        "mystery-check",
                        "mystery_keeper",
                        "expert-check",
                    ),
                    CollaborationNode(
                        "style-check",
                        "style_guardian",
                        "expert-check",
                    ),
                )
                if node.agent_id in available
            )
            if specialist_nodes:
                writer_index = next(
                    index
                    for index, node in enumerate(nodes)
                    if node.id == "writer"
                )
                writer = nodes[writer_index]
                nodes[writer_index:writer_index] = specialist_nodes
                nodes[writer_index + len(specialist_nodes)] = CollaborationNode(
                    writer.id,
                    writer.agent_id,
                    writer.kind,
                    writer.depends_on
                    + tuple(node.id for node in specialist_nodes),
                )
        return CollaborationPlan(domain=normalized, nodes=tuple(nodes))
