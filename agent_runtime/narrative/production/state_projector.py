"""StateProjector — extracts narrative state deltas from prose after selection.

Runs *after* prose selection (not during Writer execution).  Produces a
``narrative_state_delta.yml`` that strictly separates hard facts from soft
literary observations, each bound to the prose SHA256 and an exact evidence
location (paragraph/line range).

Retrying the StateProjector or DeltaVerifier must NOT rerun Writer.

ChapterEngine owns the injectable call-order seam; this module remains a pure
prose-to-delta projector.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

class StateDelta:
    """One prose-bound state delta with hard/soft separation.

    Hard facts: timeline, character state, item/location truth, world rules.
    Soft observations: voice, emotional debt, life texture, scene function,
    reader knowledge gaps, rhetoric use, motif appearance.
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = dict(data)

    @property
    def prose_sha256(self) -> str:
        return str(self._data.get("prose_sha256") or "")

    @property
    def hard_facts(self) -> list[dict[str, Any]]:
        return list(self._data.get("hard_facts") or [])

    @property
    def soft_observations(self) -> list[dict[str, Any]]:
        return list(self._data.get("soft_observations") or [])

    @property
    def chapter_id(self) -> int:
        return int(self._data.get("chapter_id") or 0)

    @property
    def is_empty(self) -> bool:
        return not self.hard_facts and not self.soft_observations

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def evidence_locations(self) -> list[str]:
        """Every evidence locator referenced by any fact or observation."""
        locs: list[str] = []
        for fact in self.hard_facts:
            loc = fact.get("evidence_location")
            if isinstance(loc, str) and loc.strip():
                locs.append(loc.strip())
        for obs in self.soft_observations:
            loc = obs.get("evidence_location")
            if isinstance(loc, str) and loc.strip():
                locs.append(loc.strip())
        return locs


class StateProjector:
    """Post-selection state extraction.

    The projector is a deterministic scaffold that structures what a
    downstream model (Scribe or narrow projector) would populate.  It does
    NOT call any provider.  It creates a skeleton ``narrative_state_delta.yml``
    bound to the prose hash and ready for population.

    Retry semantics: on failure the projector may be re-invoked; it must
    never trigger a Writer re-run.
    """

    @staticmethod
    def create_skeleton(
        prose_path: str | Path,
        *,
        chapter_id: int,
        previous_delta_path: str | Path | None = None,
    ) -> StateDelta:
        """Create a skeleton delta bound to prose content.

        Args:
            prose_path: Path to ``fiction_draft.md``.
            chapter_id: The chapter this delta belongs to.
            previous_delta_path: Optional path to the previous chapter's
                delta for continuity reference.

        Returns:
            A skeleton ``StateDelta`` with bound prose hash; hard/soft
            sections are empty and ready for population.
        """
        prose = Path(prose_path)
        if not prose.is_file():
            raise FileNotFoundError(f"prose not found: {prose_path}")

        prose_content = prose.read_text(encoding="utf-8")
        prose_hash = hashlib.sha256(prose_content.encode("utf-8")).hexdigest()

        previous_hash = ""
        if previous_delta_path is not None:
            pp = Path(previous_delta_path)
            if pp.is_file():
                previous_hash = hashlib.sha256(
                    pp.read_bytes()
                ).hexdigest()

        data: dict[str, Any] = {
            "schema_version": 2,
            "chapter_id": chapter_id,
            "prose_sha256": prose_hash,
            "previous_delta_sha256": previous_hash or None,
            "hard_facts": [],
            "soft_observations": [],
            "retry_count": 0,
            "writer_rerun_triggered": False,
            "node_local_retry_only": True,
            "candidate_only": True,
            "production_modified": False,
        }
        return StateDelta(data)

    @staticmethod
    def record_hard_fact(
        delta: StateDelta,
        *,
        category: str,
        evidence_location: str,
        content: str,
        confidence: str = "confirmed",
    ) -> StateDelta:
        """Append one hard fact to the delta."""
        fact = {
            "category": category,
            "evidence_location": evidence_location,
            "content": content,
            "confidence": confidence,
        }
        data = delta.to_dict()
        data["hard_facts"] = [*delta.hard_facts, fact]
        return StateDelta(data)

    @staticmethod
    def record_soft_observation(
        delta: StateDelta,
        *,
        category: str,
        evidence_location: str,
        observation: str,
    ) -> StateDelta:
        """Append one soft literary observation to the delta."""
        obs = {
            "category": category,
            "evidence_location": evidence_location,
            "observation": observation,
        }
        data = delta.to_dict()
        data["soft_observations"] = [*delta.soft_observations, obs]
        return StateDelta(data)

    @staticmethod
    def bump_retry(delta: StateDelta) -> StateDelta:
        """Increment retry count (no Writer re-run)."""
        data = delta.to_dict()
        data["retry_count"] = delta._data.get("retry_count", 0) + 1
        return StateDelta(data)


def project_state(
    prose_path: str | Path,
    *,
    chapter_id: int,
    previous_delta_path: str | Path | None = None,
) -> StateDelta:
    """Public entry-point: create a prose-bound skeleton delta."""
    return StateProjector.create_skeleton(
        prose_path,
        chapter_id=chapter_id,
        previous_delta_path=previous_delta_path,
    )
