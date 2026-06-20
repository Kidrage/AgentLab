"""M1-2 Mission Compiler v2 — deterministic project-level compilation.

All classifiers are rule-based (keyword/pattern matching). No LLM calls.
"""

from __future__ import annotations

from agent_runtime.brain.mission_contract import build_mission_contract

__all__ = ["build_mission_contract"]
