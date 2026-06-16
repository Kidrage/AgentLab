"""P2-G Context Governance kernel.

Deterministic, fixture-friendly utilities for classifying information,
choosing compression/budget policy, and writing context artifacts.
No network, OCR, crawler, database, or LLM compression is performed here.
"""

from .context_pack import build_context_artifacts, write_context_artifacts, context_summary
from .schemas import ContextProfile, ContextBudget, ContextPack

__all__ = [
    "ContextProfile",
    "ContextBudget",
    "ContextPack",
    "build_context_artifacts",
    "write_context_artifacts",
    "context_summary",
]