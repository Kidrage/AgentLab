"""Narrative job contracts shared by compilation and background execution."""

from agent_runtime.narrative.jobs.identity import (
    NarrativeJobIdentity,
    compile_narrative_job_identity,
)
from agent_runtime.narrative.jobs.crown_adapter import create_crown_audit_job_from_contract

__all__ = [
    "NarrativeJobIdentity",
    "compile_narrative_job_identity",
    "create_crown_audit_job_from_contract",
]
