"""DeltaVerifier — independent validation of state deltas against prose.

Every hard fact and soft observation in a ``narrative_state_delta.yml`` must
reference an exact evidence location that exists in the prose.  The verifier
checks this independently; it does not trust the delta author.

Retrying verification must not rerun Writer.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

# Paragraph-level locator: "¶12" or "¶12-15" or "L34" or "L34-38"
_LOCATOR_RE = re.compile(r"^([¶¶]|L)\s*(\d+)(?:\s*[-–—]\s*(\d+))?$")


class DeltaVerifier:
    """Independent prose→delta verification.

    Does NOT call any provider.  Checks that:
    - the delta's prose hash matches the actual prose file;
    - every evidence location resolves to real text in the prose;
    - hard facts and soft observations are structurally well-formed;
    - no fact appears in both hard and soft categories for the same location.
    """

    @staticmethod
    def verify(
        prose_path: str | Path,
        delta: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify a state delta against its bound prose.

        Args:
            prose_path: Path to ``fiction_draft.md``.
            delta: The state delta dict (as from ``StateDelta.to_dict()``).

        Returns:
            Verification result with ``status``, ``issues``, ``hash_match``,
            ``unresolvable_locations``, ``fact_count``, ``observation_count``.
        """
        issues: list[str] = []
        path = Path(prose_path)
        if not path.is_file():
            return DeltaVerifier._result(
                "blocked", ["prose_file_missing"], delta
            )

        prose_text = path.read_text(encoding="utf-8")
        actual_hash = hashlib.sha256(prose_text.encode("utf-8")).hexdigest()
        claimed_hash = str(delta.get("prose_sha256") or "")

        hash_match = actual_hash == claimed_hash
        if not hash_match:
            issues.append("prose_hash_mismatch")

        prose_lines = prose_text.splitlines()
        unresolvable: list[str] = []

        # Verify hard facts.
        hard_facts = delta.get("hard_facts")
        if not isinstance(hard_facts, list):
            issues.append("hard_facts_must_be_list")
            hard_facts = []

        for i, fact in enumerate(hard_facts):
            if not isinstance(fact, dict):
                issues.append(f"invalid_hard_fact:{i}")
                continue
            loc = fact.get("evidence_location", "")
            category = fact.get("category", "")
            content = fact.get("content", "")
            if not isinstance(category, str) or not category.strip():
                issues.append(f"hard_fact_missing_category:{i}")
            if not isinstance(content, str) or not content.strip():
                issues.append(f"hard_fact_missing_content:{i}")
            if isinstance(loc, str) and loc.strip():
                if not DeltaVerifier._locator_resolves(loc, prose_lines):
                    unresolvable.append(f"hard:{i}:{loc}")
            else:
                issues.append(f"hard_fact_missing_location:{i}")

        # Verify soft observations.
        soft = delta.get("soft_observations")
        if not isinstance(soft, list):
            issues.append("soft_observations_must_be_list")
            soft = []

        for i, obs in enumerate(soft):
            if not isinstance(obs, dict):
                issues.append(f"invalid_soft_observation:{i}")
                continue
            loc = obs.get("evidence_location", "")
            category = obs.get("category", "")
            observation = obs.get("observation", "")
            if not isinstance(category, str) or not category.strip():
                issues.append(f"soft_observation_missing_category:{i}")
            if not isinstance(observation, str) or not observation.strip():
                issues.append(f"soft_observation_missing_content:{i}")
            if isinstance(loc, str) and loc.strip():
                if not DeltaVerifier._locator_resolves(loc, prose_lines):
                    unresolvable.append(f"soft:{i}:{loc}")
            else:
                issues.append(f"soft_observation_missing_location:{i}")

        # Cross-category duplication check.
        hard_locs = {
            str(f.get("evidence_location", ""))
            for f in hard_facts
            if isinstance(f, dict)
        }
        soft_locs = {
            str(o.get("evidence_location", ""))
            for o in soft
            if isinstance(o, dict)
        }
        overlap = hard_locs & soft_locs
        if overlap:
            issues.append(
                f"evidence_location_used_in_both_hard_and_soft:{','.join(sorted(overlap))}"
            )

        if unresolvable:
            issues.append(f"unresolvable_locations:{len(unresolvable)}")

        node_local_retry = bool(delta.get("node_local_retry_only", True))
        if not node_local_retry:
            issues.append("node_local_retry_only_must_be_true")

        return DeltaVerifier._result(
            "pass" if not issues else "blocked",
            issues,
            delta,
            hash_match,
            unresolvable,
            len(hard_facts),
            len(soft),
        )

    @staticmethod
    def _locator_resolves(loc: str, lines: list[str]) -> bool:
        """Check whether a ¶N, ¶N-M, LN, or LN-M locator exists in *lines*."""
        m = _LOCATOR_RE.match(loc.strip())
        if not m:
            return False
        start = int(m.group(2))
        end_str = m.group(3)
        end = int(end_str) if end_str else start
        max_line = len(lines)
        return 1 <= start <= max_line and 1 <= end <= max_line

    @staticmethod
    def _result(
        status: str,
        issues: list[str],
        delta: dict[str, Any],
        hash_match: bool = False,
        unresolvable: list[str] | None = None,
        fact_count: int = 0,
        obs_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "status": status,
            "issues": issues,
            "chapter_id": delta.get("chapter_id"),
            "prose_hash_match": hash_match,
            "unresolvable_locations": unresolvable or [],
            "hard_fact_count": fact_count,
            "soft_observation_count": obs_count,
            "writer_rerun_required": False,
            "node_local_retry_allowed": True,
        }


def verify_state_delta(
    prose_path: str | Path,
    delta: dict[str, Any],
) -> dict[str, Any]:
    """Public entry-point: independent delta verification."""
    return DeltaVerifier.verify(prose_path, delta)
