"""ChapterEngine — thin public API for v2 narrative production.

Orchestrates the v2 chapter path:
  BriefCompiler → prose-only Writer → *selection gate* → StateProjector → DeltaVerifier

The engine is a structural scaffold.  It does NOT call providers or mutate
production.  Actual Writer invocation is handled by the existing role-session
machinery; this module validates inputs/outputs and records evidence.

Key invariants:
- StateProjector runs ONLY after a prose candidate is explicitly selected.
- Valid Writer output that is NOT selected must not trigger StateProjector.
- Selected prose without a populated projected delta returns
  ``needs_state_projection``, not a passing empty skeleton.
- Projector/verifier retry NEVER triggers a Writer re-run.
- Temporary files are cleaned in ``finally``.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable

from agent_runtime.narrative.production.brief_compiler import (
    CreativeBrief,
    compile_creative_brief,
    validate_creative_brief,
)
from agent_runtime.narrative.production.delta_verifier import (
    verify_state_delta,
)
from agent_runtime.narrative.production.state_projector import (
    StateDelta,
    project_state,
)
from agent_runtime.narrative.production.writer_contract import (
    validate_writer_v2_output,
)
from agent_runtime.narrative.quality.prose_length import (
    build_han_character_contract,
)
from agent_runtime.narrative.state_store import narrative_payload_sha256


@dataclass
class ChapterRequest:
    """Input to ChapterEngine.run()."""

    chapter_id: int
    # v1 backward-compat: a legacy state plan dict.
    legacy_state_plan: dict[str, Any] | None = None
    # v2-native: a pre-built creative brief dict.
    creative_brief: dict[str, Any] | None = None
    # Paths to source context (for hash binding).
    source_paths: list[str] = field(default_factory=list)
    # Previously materialized Writer output (after role-session returns).
    writer_output: dict[str, str] | None = None
    # Path to previous chapter's state delta for continuity.
    previous_delta_path: str | None = None
    # Allow retry of projector/verifier without Writer re-run.
    node_local_retry: bool = True
    # EXPLICIT selection gate: prose must be selected before projection.
    prose_selected: bool = False
    # Pre-populated state delta.  When provided and non-empty, the engine
    # skips StateProjector and proceeds directly to delta verification.
    # This is the reachable pass path: an external operator (Scribe or
    # narrow projector) populates hard facts / soft observations, then
    # re-enters ChapterEngine with the populated delta for verification.
    state_delta: dict[str, Any] | None = None
    # Observed Writer execution provenance.  These must be non-empty for
    # Writer v2 validation to succeed — missing or whitespace provenance
    # blocks before any prose or receipt write.
    provider: str = ""
    model: str = ""
    call_id: str = ""
    # Injectable post-selection projector seam.  Tests and background nodes
    # can supply a spy or a narrow projector without process-global state.
    projector: Callable[..., StateDelta] | None = None
    # Optional project-scoped prose policy. Global Chinese dialogue mechanics
    # remain active when this is omitted.
    prose_conventions_policy: dict[str, Any] | None = None
    # Optional final-acceptance seam. Both values must be supplied together;
    # the store itself verifies accepted seal and previous-state hashes.
    narrative_state_store: Any | None = None
    verified_commit: dict[str, Any] | None = None


@dataclass
class ChapterOutcome:
    """Result of ChapterEngine.run()."""

    chapter_id: int
    status: str  # pass | blocked | needs_writer | needs_local_prose_repair | needs_state_projection | needs_selection
    creative_brief: CreativeBrief | None = None
    writer_validation: dict[str, Any] | None = None
    state_delta: StateDelta | None = None
    delta_verification: dict[str, Any] | None = None
    issues: list[str] = field(default_factory=list)
    writer_rerun_needed: bool = False
    writer_local_repair_needed: bool = False
    selected_prose_sha256: str = ""
    state_commit_receipt: dict[str, Any] | None = None
    # Public call-order log: proves projector is called only after selection.
    # Each entry: {call_index, kind, chapter_id, prose_selected}.
    projector_call_log: list[dict[str, Any]] = field(default_factory=list)


class ChapterEngine:
    """Structural orchestrator for v2 chapter production.

    This engine does NOT invoke providers.  It:
    1. Compiles/validates the creative brief.
    2. Validates Writer v2 output (prose-only).
    3. **Selection gate**: only selected prose triggers projection.
    4. Creates a state delta skeleton after prose is confirmed.
    5. Verifies the delta independently.

    Step 4–5 retry without Writer re-run is the default.
    Temporary files are always cleaned in ``finally``.
    """

    @staticmethod
    def run(request: ChapterRequest) -> ChapterOutcome:
        """Execute the v2 chapter path for *request*."""
        issues: list[str] = []
        selected_prose_sha256 = ""

        # Per-run projector call log — no process-global state.
        _call_log: list[dict[str, Any]] = []

        # Helper: build outcome with the local call log attached.
        def _outcome(**kwargs: Any) -> ChapterOutcome:
            kwargs.setdefault("chapter_id", request.chapter_id)
            kwargs.setdefault("projector_call_log", list(_call_log))
            kwargs.setdefault("selected_prose_sha256", selected_prose_sha256)
            return ChapterOutcome(**kwargs)

        def _verified_pass_outcome(
            *,
            brief: CreativeBrief,
            writer_val: dict[str, Any],
            delta: StateDelta,
            delta_ver: dict[str, Any],
        ) -> ChapterOutcome:
            store = request.narrative_state_store
            commit = request.verified_commit
            if store is None and commit is None:
                return _outcome(
                    status="pass",
                    creative_brief=brief,
                    writer_validation=writer_val,
                    state_delta=delta,
                    delta_verification=delta_ver,
                    issues=issues,
                    writer_rerun_needed=False,
                )
            if store is None or commit is None:
                return _outcome(
                    status="blocked",
                    creative_brief=brief,
                    writer_validation=writer_val,
                    state_delta=delta,
                    delta_verification=delta_ver,
                    issues=["state_commit_requires_store_and_verified_commit"],
                    writer_rerun_needed=False,
                )
            if commit.get("artifact_sha256") != selected_prose_sha256:
                return _outcome(
                    status="blocked",
                    creative_brief=brief,
                    writer_validation=writer_val,
                    state_delta=delta,
                    delta_verification=delta_ver,
                    issues=["state_commit_selected_prose_hash_mismatch"],
                    writer_rerun_needed=False,
                )
            commit_verification = commit.get("delta_verification")
            commit_verification = (
                commit_verification
                if isinstance(commit_verification, dict)
                else {}
            )
            commit_seal = commit.get("seal")
            commit_seal = commit_seal if isinstance(commit_seal, dict) else {}
            expected_binding = {
                "artifact_sha256": selected_prose_sha256,
                "brief_sha256": narrative_payload_sha256(brief.to_dict()),
                "source_projection_sha256": narrative_payload_sha256(
                    delta.to_dict()
                ),
                "verification_result_sha256": narrative_payload_sha256(delta_ver),
            }
            binding_matches = (
                commit.get("chapter") == request.chapter_id
                and commit.get("brief_sha256") == expected_binding["brief_sha256"]
                and commit.get("source_projection_sha256")
                == expected_binding["source_projection_sha256"]
                and commit_verification.get("source_projection_sha256")
                == expected_binding["source_projection_sha256"]
                and commit_verification.get("verification_result_sha256")
                == expected_binding["verification_result_sha256"]
                and all(
                    commit_seal.get(field) == value
                    for field, value in expected_binding.items()
                )
            )
            if not binding_matches:
                return _outcome(
                    status="blocked",
                    creative_brief=brief,
                    writer_validation=writer_val,
                    state_delta=delta,
                    delta_verification=delta_ver,
                    issues=["state_commit_current_run_binding_mismatch"],
                    writer_rerun_needed=False,
                )
            try:
                receipt = store.commit(commit)
            except Exception as exc:
                return _outcome(
                    status="blocked",
                    creative_brief=brief,
                    writer_validation=writer_val,
                    state_delta=delta,
                    delta_verification=delta_ver,
                    issues=[f"state_commit_failed:{type(exc).__name__}"],
                    writer_rerun_needed=False,
                )
            return _outcome(
                status="pass",
                creative_brief=brief,
                writer_validation=writer_val,
                state_delta=delta,
                delta_verification=delta_ver,
                state_commit_receipt=receipt,
                issues=issues,
                writer_rerun_needed=False,
            )

        # ---- 1. Creative brief --------------------------------------------
        brief: CreativeBrief | None = None
        if request.creative_brief is not None:
            brief_issues = validate_creative_brief(request.creative_brief)
            if brief_issues:
                return _outcome(
                    chapter_id=request.chapter_id,
                    status="blocked",
                    issues=[f"brief:{i}" for i in brief_issues],
                )
            brief = CreativeBrief(request.creative_brief)
        elif request.legacy_state_plan is not None:
            try:
                brief = compile_creative_brief(
                    request.legacy_state_plan,
                    chapter_id=request.chapter_id,
                    source_paths=request.source_paths,
                )
            except ValueError as exc:
                return _outcome(
                    chapter_id=request.chapter_id,
                    status="blocked",
                    issues=[f"brief_compilation:{exc}"],
                )
        else:
            return _outcome(
                chapter_id=request.chapter_id,
                status="blocked",
                issues=["no_brief_or_state_plan"],
            )

        # ---- 2. Writer v2 validation --------------------------------------
        if request.writer_output is None:
            return _outcome(
                chapter_id=request.chapter_id,
                status="needs_writer",
                creative_brief=brief,
                issues=[],
            )

        writer_val = validate_writer_v2_output(
            request.writer_output,
            provider=request.provider,
            model=request.model,
            call_id=request.call_id,
            prose_length_contract=build_han_character_contract(
                brief.word_count_target
            ),
            chapter_context={
                "chapter": request.chapter_id,
                "chapter_position": brief.to_dict().get("chapter_position"),
            },
            prose_conventions_policy=request.prose_conventions_policy,
        )
        if writer_val["status"] != "pass":
            issues.append("writer_v2_validation_failed")
            conventions = writer_val.get("prose_conventions") or {}
            return _outcome(
                chapter_id=request.chapter_id,
                status=(
                    "needs_local_prose_repair"
                    if conventions.get("local_repair_needed")
                    else "blocked"
                ),
                creative_brief=brief,
                writer_validation=writer_val,
                issues=issues + writer_val.get("issues", []),
                writer_rerun_needed=bool(
                    conventions.get("writer_rerun_needed")
                ),
                writer_local_repair_needed=bool(
                    conventions.get("local_repair_needed")
                ),
            )

        # ---- 3. EXPLICIT selection gate ------------------------------------
        # Valid Writer output that is not selected must NOT trigger
        # StateProjector.
        if not request.prose_selected:
            return _outcome(
                chapter_id=request.chapter_id,
                status="needs_selection",
                creative_brief=brief,
                writer_validation=writer_val,
                issues=["prose_not_selected_state_projection_blocked"],
                writer_rerun_needed=False,
            )

        # ---- 4. State projection or pre-populated delta -------------------
        selected_prose_sha256 = str(writer_val.get("prose_sha256") or "")
        prose_content = str(writer_val.get("canonical_prose") or "")
        prose_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".md",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(prose_content)
                prose_path = tmp.name

            # Pre-populated delta path (reachable pass path).
            if request.state_delta is not None:
                # Verify the delta is bound to the exact prose.
                from agent_runtime.narrative.production.state_projector import (
                    StateDelta,
                )
                delta = StateDelta(request.state_delta)

                # ---- 4a. Empty delta gate ----------------------------------
                if delta.is_empty:
                    return _outcome(
                        chapter_id=request.chapter_id,
                        status="needs_state_projection",
                        creative_brief=brief,
                        writer_validation=writer_val,
                        state_delta=delta,
                        issues=["empty_projection_requires_state_population"],
                        writer_rerun_needed=False,
                    )

                # ---- 4b. Verify hash binding --------------------------------
                delta_dict = delta.to_dict()
                delta_ver = verify_state_delta(prose_path, delta_dict)

                if delta_ver["status"] != "pass":
                    if request.node_local_retry and delta_ver.get(
                        "node_local_retry_allowed"
                    ):
                        issues.append("delta_verification_blocked_retry_allowed")
                    else:
                        issues.append("delta_verification_blocked")
                    return _outcome(
                        chapter_id=request.chapter_id,
                        status="blocked",
                        creative_brief=brief,
                        writer_validation=writer_val,
                        state_delta=delta,
                        delta_verification=delta_ver,
                        issues=issues + delta_ver.get("issues", []),
                        writer_rerun_needed=False,
                    )

                # ---- 4c. Reachable pass ------------------------------------
                return _verified_pass_outcome(
                    brief=brief,
                    writer_val=writer_val,
                    delta=delta,
                    delta_ver=delta_ver,
                )

            # Skeleton path (projector creates empty delta; never reaches pass).
            projector = request.projector or project_state
            _call_log.append(
                {
                    "call_index": len(_call_log),
                    "kind": "state_projector",
                    "chapter_id": request.chapter_id,
                    "prose_selected": True,
                }
            )
            delta = projector(
                prose_path,
                chapter_id=request.chapter_id,
                previous_delta_path=request.previous_delta_path,
            )

            # ---- 4d. Empty projection gate ---------------------------------
            # Selected prose whose projected delta is still empty (no facts,
            # no observations) must NOT pass as a completed outcome.
            if delta.is_empty:
                return _outcome(
                    chapter_id=request.chapter_id,
                    status="needs_state_projection",
                    creative_brief=brief,
                    writer_validation=writer_val,
                    state_delta=delta,
                    issues=["empty_projection_requires_state_population"],
                    writer_rerun_needed=False,
                )

            # ---- 5. Delta verification -------------------------------------
            delta_dict = delta.to_dict()
            delta_ver = verify_state_delta(prose_path, delta_dict)

            if delta_ver["status"] != "pass":
                if request.node_local_retry and delta_ver.get(
                    "node_local_retry_allowed"
                ):
                    issues.append("delta_verification_blocked_retry_allowed")
                else:
                    issues.append("delta_verification_blocked")
                return _outcome(
                    chapter_id=request.chapter_id,
                    status="blocked",
                    creative_brief=brief,
                    writer_validation=writer_val,
                    state_delta=delta,
                    delta_verification=delta_ver,
                    issues=issues + delta_ver.get("issues", []),
                    writer_rerun_needed=False,
                )

            # ---- 6. Success -------------------------------------------------
            return _verified_pass_outcome(
                brief=brief,
                writer_val=writer_val,
                delta=delta,
                delta_ver=delta_ver,
            )

        except FileNotFoundError:
            return _outcome(
                chapter_id=request.chapter_id,
                status="blocked",
                creative_brief=brief,
                writer_validation=writer_val,
                issues=["state_projection_prose_missing"],
                writer_rerun_needed=False,
            )
        except Exception as exc:
            return _outcome(
                chapter_id=request.chapter_id,
                status="blocked",
                creative_brief=brief,
                writer_validation=writer_val,
                issues=[f"state_projection_failed:{type(exc).__name__}"],
                writer_rerun_needed=False,
            )

        finally:
            # Always clean temporary prose file.
            if prose_path is not None:
                try:
                    os.unlink(prose_path)
                except OSError:
                    pass
