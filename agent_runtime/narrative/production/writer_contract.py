"""Writer v2 contract — prose-only output, AgentLab-owned receipts.

Writer v2 produces exactly one artifact: ``fiction_draft.md``.  The Writer
does NOT self-generate continuity ledgers, state transition proposals, or
delivery receipts.  AgentLab owns those artifacts and produces them through
the StateProjector and DeltaVerifier after prose selection.

The AgentLab receipt is issued from observed execution data (provider, model,
call ID or equivalent) and is hash-bound to the selected prose.  Writer output
must not be able to supply or overwrite the receipt.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

# The Writer v2 produces only prose.
WRITER_V2_REQUIRED_OUTPUTS: tuple[str, ...] = ("fiction_draft.md",)

# These v1 outputs are forbidden in v2 Writer output.
WRITER_V2_FORBIDDEN_OUTPUTS: tuple[str, ...] = (
    "continuity_ledger.yml",
    "state_transition_proposal.yml",
    "narrative_delivery_receipt.yml",
)

_UNSAFE_PATH_PATTERNS: tuple[str, ...] = ("..",)
_ABSOLUTE_PATH_PREFIX: str = os.sep


def _has_complete_provenance(provider: str, model: str, call_id: str) -> bool:
    """Return whether all observed execution identifiers are non-blank."""
    return all((value or "").strip() for value in (provider, model, call_id))


def _apply_prose_length_contract(
    result: dict[str, Any],
    prose_length_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if result["status"] != "pass" or prose_length_contract is None:
        return result
    from agent_runtime.narrative.quality.prose_length import (
        evaluate_han_character_contract,
    )

    length_result = evaluate_han_character_contract(
        str(result.get("canonical_prose") or ""),
        prose_length_contract,
    )
    result["han_character_count"] = length_result["han_character_count"]
    result["prose_length_contract"] = length_result["contract"]
    if length_result["status"] != "pass":
        result["status"] = "blocked"
        result["issues"] = [str(length_result["issue"])]
        result["prose_sha256"] = ""
        result["canonical_prose"] = ""
        result["agentlab_receipt"] = None
    return result


def _apply_prose_conventions_contract(
    result: dict[str, Any],
    *,
    chapter_context: Mapping[str, Any] | None = None,
    prose_conventions_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if result["status"] != "pass":
        return result
    from agent_runtime.narrative.quality.prose_conventions import (
        evaluate_prose_conventions,
    )

    report = evaluate_prose_conventions(
        str(result.get("canonical_prose") or ""),
        chapter_context=chapter_context,
        policy=prose_conventions_policy,
    )
    result["prose_conventions"] = report
    # Only deterministic mechanical errors belong to the Writer contract.
    # Rhetorical fatigue remains visible for the Editor revision lane.
    if report["mechanical_status"] == "blocked":
        result["status"] = "blocked"
        result["issues"] = [
            f"prose_conventions:{issue['id']}:{issue.get('locator', 'chapter')}"
            for issue in report["issues"]
            if issue["severity"] == "blocked"
        ]
        result["prose_sha256"] = ""
        result["canonical_prose"] = ""
        result["agentlab_receipt"] = None
    return result


def _issuer_receipt(
    prose_sha256: str,
    *,
    provider: str = "",
    model: str = "",
    call_id: str = "",
) -> dict[str, Any]:
    """Build an AgentLab-issued receipt from observed execution data.

    The receipt is NOT a constant boolean.  It carries the actual observed
    provider, model, and call ID (or equivalent) so it can be independently
    verified.  Writer output never supplies or overwrites this data.

    All three provenance fields must be non-empty — missing provenance makes
    the receipt untrustable and the result status must be "blocked".
    """
    return {
        "schema_version": 2,
        "issuer": "AgentLab",
        "issuer_role": "writer_contract_validator",
        "prose_sha256": prose_sha256,
        "observed_provider": provider.strip(),
        "observed_model": model.strip(),
        "observed_call_id": call_id.strip(),
        "writer_cannot_overwrite": True,
    }


class WriterV2Contract:
    """Validate Writer v2 output against the prose-only contract."""

    @staticmethod
    def validate_materialized_outputs(
        materialized: dict[str, str],
        *,
        provider: str = "",
        model: str = "",
        call_id: str = "",
        prose_length_contract: Mapping[str, Any] | None = None,
        chapter_context: Mapping[str, Any] | None = None,
        prose_conventions_policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check that Writer produced exactly ``fiction_draft.md`` and nothing else.

        Returns a validation dict with ``schema_version``, ``status``,
        ``issues``, ``prose_sha256``, and an AgentLab-issued receipt.
        """
        issues: list[str] = []
        names = set(materialized)

        # Required.
        if "fiction_draft.md" not in names:
            issues.append("missing_fiction_draft_md")
            return WriterV2Contract._result(
                "blocked", issues, provider=provider, model=model, call_id=call_id
            )

        # Forbidden v1 artifacts.
        for forbidden in WRITER_V2_FORBIDDEN_OUTPUTS:
            if forbidden in names:
                issues.append(f"writer_v2_must_not_produce:{forbidden}")

        # Any unexpected output other than fiction_draft.md.
        unexpected = names - {"fiction_draft.md"}
        if unexpected:
            issues.extend(
                f"unexpected_writer_v2_output:{name}"
                for name in sorted(unexpected)
            )

        prose = materialized["fiction_draft.md"]
        if not prose.strip():
            issues.append("fiction_draft_md_is_empty")

        # Require observed provenance on all success paths.  A missing
        # or whitespace-only provider, model, or call_id makes the receipt
        # untrustable — the result must be blocked even when every other
        # check passes.  This mirrors validate_edit_blocks provenance gate.
        if not issues and not _has_complete_provenance(provider, model, call_id):
            issues.append("missing_observed_provenance")

        result = _apply_prose_length_contract(
            WriterV2Contract._result(
                "pass" if not issues else "blocked",
                issues,
                prose,
                provider=provider,
                model=model,
                call_id=call_id,
            ),
            prose_length_contract,
        )
        return _apply_prose_conventions_contract(
            result,
            chapter_context=chapter_context,
            prose_conventions_policy=prose_conventions_policy,
        )

    @staticmethod
    def validate_edit_blocks(
        blocks: list[dict[str, Any]],
        *,
        task_id: str = "",
        provider: str = "",
        model: str = "",
        call_id: str = "",
        prose_length_contract: Mapping[str, Any] | None = None,
        chapter_context: Mapping[str, Any] | None = None,
        prose_conventions_policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate parsed edit blocks from Writer output for v2 compliance.

        Every non-fiction block is rejected.  Duplicate fiction blocks, blank
        content, absolute paths, traversal (``..``), and cross-run paths all
        block the run.  On any issue, no ``fiction_draft.md`` is written.

        Args:
            blocks: Parsed AGENTLAB_EDIT blocks from Writer output.
            task_id: Expected task_id for cross-run detection.

        Returns:
            Validation result with status, issues, prose_sha256, and receipt.
        """
        issues: list[str] = []
        fiction_seen = False
        prose_content = ""
        normalized_task_id = task_id.strip()
        if not normalized_task_id:
            issues.append("missing_task_id")
        expected_run = (
            f"runs/{normalized_task_id}/" if normalized_task_id else None
        )

        for i, block in enumerate(blocks):
            raw_path = str(block.get("path") or "").strip().replace("\\", "/")
            # Normalize path separators.
            normalized = raw_path

            # --- Path safety checks ------------------------------------------
            # Reject absolute paths.
            if normalized.startswith(_ABSOLUTE_PATH_PREFIX):
                issues.append(f"absolute_path_rejected:block[{i}]:{normalized}")
                continue

            # Reject traversal.
            parts = Path(normalized).parts
            if any(p in _UNSAFE_PATH_PATTERNS for p in parts):
                issues.append(f"traversal_path_rejected:block[{i}]:{normalized}")
                continue

            # Extract basename for content classification.
            name = Path(normalized).name

            # --- Content extraction ------------------------------------------
            value = str(block.get("html_block_content") or "").strip()
            # Also try plain content field.
            if not value:
                value = str(block.get("content") or "").strip()

            # --- Non-fiction rejection ---------------------------------------
            if name != "fiction_draft.md":
                # Any file that is not fiction_draft.md is a non-fiction block.
                # This catches arbitrary scorecard/metadata names.
                issues.append(
                    f"non_fiction_block_rejected:block[{i}]:{name}"
                )
                continue

            # --- fiction_draft.md specific checks ----------------------------
            # Duplicate fiction block.
            if fiction_seen:
                issues.append(f"duplicate_fiction_draft_block:block[{i}]")
                continue
            fiction_seen = True

            # Blank content.
            if not value:
                issues.append("fiction_draft_block_empty")
                continue

            # Cross-run path detection — require *exact* match against
            # runs/<task_id>/fiction_draft.md.  Substring matching and
            # prefix-component matching both leave false-green gaps:
            # runs/task_ch01/sub/fiction_draft.md and
            # runs/task_ch01_extra/fiction_draft.md must both be rejected.
            # The target path must have exactly three components:
            # ("runs", task_id, "fiction_draft.md").
            if expected_run and normalized:
                norm_parts = Path(normalized).parts
                if (
                    len(norm_parts) != 3
                    or norm_parts[0] != "runs"
                    or norm_parts[1] != normalized_task_id
                    or norm_parts[2] != "fiction_draft.md"
                ):
                    issues.append(
                        f"cross_run_path_rejected:block[{i}]:{normalized}"
                    )
                    continue

            prose_content = value

        if not fiction_seen:
            issues.append("missing_fiction_draft_md")

        # Require observed provenance on all success paths.  A missing
        # provider, model, or call ID makes the receipt untrustable — the
        # result must be blocked even when every other check passes.
        if not issues and not _has_complete_provenance(provider, model, call_id):
            issues.append("missing_observed_provenance")

        result = WriterV2Contract._result(
            "pass" if not issues else "blocked",
            issues,
            prose_content,
            provider=provider,
            model=model,
            call_id=call_id,
        )
        result = _apply_prose_length_contract(result, prose_length_contract)
        return _apply_prose_conventions_contract(
            result,
            chapter_context=chapter_context,
            prose_conventions_policy=prose_conventions_policy,
        )

    @staticmethod
    def _result(
        status: str,
        issues: list[str],
        prose: str = "",
        *,
        provider: str = "",
        model: str = "",
        call_id: str = "",
    ) -> dict[str, Any]:
        # Canonicalise prose bytes exactly as they will be written to disk —
        # one trailing newline, no other trailing whitespace.  The hash must
        # equal hashlib.sha256(fiction_draft.md.read_bytes()).hexdigest().
        canonical = (prose.rstrip() + "\n") if prose else ""
        prose_hash = (
            hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if canonical.strip()
            else ""
        )

        # Only attach receipt on success.  Blocked results must carry no
        # receipt — the receipt file on disk must not be written either.
        # Provenance enforcement happens at the edit-block level
        # (validate_edit_blocks) where actual provider info is available.
        receipt = (
            _issuer_receipt(
                prose_hash,
                provider=provider,
                model=model,
                call_id=call_id,
            )
            if status == "pass"
            else None
        )
        return {
            "schema_version": 2,
            "status": status,
            "issues": issues,
            "prose_sha256": prose_hash,
            "canonical_prose": canonical,
            "non_prose_output_count": sum(
                1 for i in issues
                if "must_not_produce" in i
                or "unexpected" in i
                or "non_fiction_block_rejected" in i
            ),
            "writer_self_receipt_present": any(
                "narrative_delivery_receipt" in i or "writer_receipt" in i
                for i in issues
            ),
            "agentlab_receipt": receipt,
        }


def validate_writer_v2_output(
    materialized: dict[str, str],
    *,
    provider: str = "",
    model: str = "",
    call_id: str = "",
    prose_length_contract: Mapping[str, Any] | None = None,
    chapter_context: Mapping[str, Any] | None = None,
    prose_conventions_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Public entry-point: validate Writer v2 materialized outputs."""
    return WriterV2Contract.validate_materialized_outputs(
        materialized,
        provider=provider,
        model=model,
        call_id=call_id,
        prose_length_contract=prose_length_contract,
        chapter_context=chapter_context,
        prose_conventions_policy=prose_conventions_policy,
    )
