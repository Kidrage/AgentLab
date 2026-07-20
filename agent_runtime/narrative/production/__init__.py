"""Narrative production v2 module — prose-only Writer, creative briefs, state projection.

Central runtime files (narrative_delivery.py, narrative_eval.py,
writer_output_materializer.py) delegate to this module through thin adapters.
Do not add narrative policy to the generic job engine or code-task route.
"""

from agent_runtime.narrative.production.brief_compiler import (
    BriefCompiler,
    ChapterFunction,
    CreativeBrief,
    compile_creative_brief,
    validate_creative_brief,
)
from agent_runtime.narrative.production.chapter_engine import (
    ChapterEngine,
    ChapterOutcome,
    ChapterRequest,
)
from agent_runtime.narrative.production.context_compiler import (
    ContextCompiler,
    ContextRequest,
    ContextResult,
)
from agent_runtime.narrative.production.delta_verifier import (
    DeltaVerifier,
    verify_state_delta,
)
from agent_runtime.narrative.production.manifest import (
    ChapterProductionManifest,
    create_production_manifest,
)
from agent_runtime.narrative.production.state_projector import (
    StateDelta,
    StateProjector,
    project_state,
)
from agent_runtime.narrative.production.writer_contract import (
    WriterV2Contract,
    validate_writer_v2_output,
)
from agent_runtime.narrative.production.writer_packet_preview import (
    WriterPacketPreview,
    build_writer_packet_preview,
)
from agent_runtime.narrative.production.literary_memory import (
    MEMORY_CATEGORIES,
    LiteraryMemoryResult,
    compile_literary_memory_snapshot,
)

__all__ = [
    # Brief
    "BriefCompiler",
    "ChapterFunction",
    "CreativeBrief",
    "compile_creative_brief",
    "validate_creative_brief",
    # Writer
    "WriterV2Contract",
    "validate_writer_v2_output",
    "WriterPacketPreview",
    "build_writer_packet_preview",
    "MEMORY_CATEGORIES",
    "LiteraryMemoryResult",
    "compile_literary_memory_snapshot",
    # State
    "StateDelta",
    "StateProjector",
    "project_state",
    # Delta verification
    "DeltaVerifier",
    "verify_state_delta",
    # Engine
    "ChapterEngine",
    "ChapterOutcome",
    "ChapterRequest",
    # Context
    "ContextCompiler",
    "ContextRequest",
    "ContextResult",
    # Manifest
    "ChapterProductionManifest",
    "create_production_manifest",
]
