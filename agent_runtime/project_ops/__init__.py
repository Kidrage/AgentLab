"""AgentLab ProjectOps layer.

S2.5 adds repository hygiene, project routing, task compaction, agent
contribution observability, and compact agent packet contracts.
"""

from .agent_contributions import load_agent_contributions, record_agent_contribution, summarize_agent_contributions
from .agent_packet import load_agent_packet, render_agent_packet_markdown, write_agent_packet
from .project_router import init_project, project_status, route_invocation_to_project
from .repo_hygiene import scan_repository_root
from .task_compaction import compact_task

__all__ = [
    "compact_task",
    "init_project",
    "load_agent_contributions",
    "load_agent_packet",
    "project_status",
    "record_agent_contribution",
    "render_agent_packet_markdown",
    "route_invocation_to_project",
    "scan_repository_root",
    "summarize_agent_contributions",
    "write_agent_packet",
]
