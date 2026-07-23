"""Opt-in diagnostics for narrative production and audit workflows."""

from .telemetry import NARRATIVE_DIAGNOSTICS_ENV, record_narrative_invocation

__all__ = ["NARRATIVE_DIAGNOSTICS_ENV", "record_narrative_invocation"]
