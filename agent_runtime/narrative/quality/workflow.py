"""Scene-local revision, verification, re-audit, and blind selection closure."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

from agent_runtime.narrative.quality.blind_review import (
    select_candidate_after_blind_review,
)


SceneWriter = Callable[[str, dict[str, Any]], str]
CandidateCheck = Callable[[dict[str, str]], Mapping[str, Any]]
BlindJudge = Callable[[dict[str, dict[str, str]]], Mapping[str, Any]]


def _candidate_hash(scenes: Mapping[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(scenes, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def run_local_revision_closure(
    *,
    original_scenes: Mapping[str, str],
    revision_contract: Mapping[str, Any],
    writer: SceneWriter,
    deterministic_check: CandidateCheck,
    independent_reaudit: CandidateCheck,
    blind_judge: BlindJudge,
) -> dict[str, object]:
    """Change one contracted scene and replace nothing unless it wins cleanly."""
    if revision_contract.get("rewrite_scope") != "scene":
        raise ValueError("local revision closure requires a scene-scoped contract")
    target = str(revision_contract.get("target_scene") or "")
    if target not in original_scenes:
        raise ValueError("target scene is missing from the candidate")
    original = dict(original_scenes)
    revised = dict(original)
    replacement = writer(original[target], dict(revision_contract)).strip()
    if not replacement:
        raise ValueError("Writer returned an empty scene revision")
    revised[target] = replacement
    original_hash = _candidate_hash(original)
    revised_hash = _candidate_hash(revised)

    deterministic = dict(deterministic_check(revised))
    if deterministic.get("status") != "pass":
        return {
            "status": "retained_original",
            "selected_scenes": original,
            "selected_sha256": original_hash,
            "reason": "deterministic_revision_regression",
            "deterministic_check": deterministic,
        }
    reaudit = dict(independent_reaudit(revised))
    if (
        reaudit.get("status") != "pass"
        or reaudit.get("remaining_blocking")
        or reaudit.get("new_regressions")
    ):
        return {
            "status": "retained_original",
            "selected_scenes": original,
            "selected_sha256": original_hash,
            "reason": "independent_reaudit_blocked",
            "deterministic_check": deterministic,
            "independent_reaudit": reaudit,
        }

    order_key = hashlib.sha256(
        f"{revision_contract.get('revision_contract_id')}:{original_hash}:{revised_hash}".encode(
            "utf-8"
        )
    ).digest()[0]
    if order_key % 2:
        packet = {"A": original, "B": revised}
        mapping = {"A": original_hash, "B": revised_hash}
    else:
        packet = {"A": revised, "B": original}
        mapping = {"A": revised_hash, "B": original_hash}
    blind_receipt = dict(blind_judge(packet))
    blind_receipt.setdefault("remaining_blocking", reaudit.get("remaining_blocking") or [])
    blind_receipt.setdefault("new_regressions", reaudit.get("new_regressions") or [])
    selection = select_candidate_after_blind_review(
        original_sha256=original_hash,
        revised_sha256=revised_hash,
        blind_mapping=mapping,
        blind_receipt=blind_receipt,
    )
    accepted = bool(selection["replace_current_candidate"])
    return {
        **selection,
        "selected_scenes": revised if accepted else original,
        "deterministic_check": deterministic,
        "independent_reaudit": reaudit,
        "blind_receipt": blind_receipt,
        "blind_mapping_sha256": hashlib.sha256(
            json.dumps(mapping, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
