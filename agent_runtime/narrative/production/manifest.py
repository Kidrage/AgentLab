"""Production manifest — content-addressed record of one chapter's v2 pipeline.

``chapter_production_manifest.yml`` records hashes and receipts for every
step in the v2 production path.  Phase 1R keeps this focused on the
production seam; any broader memory snapshot belongs in a later phase.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ChapterProductionManifest:
    """Content-addressed record of one chapter's v2 production pipeline."""

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = dict(data)

    @property
    def chapter_id(self) -> int:
        return int(self._data.get("chapter_id") or 0)

    @property
    def brief_sha256(self) -> str:
        return str(self._data.get("creative_brief_sha256") or "")

    @property
    def prose_sha256(self) -> str:
        return str(self._data.get("fiction_draft_sha256") or "")

    @property
    def delta_sha256(self) -> str:
        return str(self._data.get("state_delta_sha256") or "")

    @property
    def status(self) -> str:
        return str(self._data.get("status") or "draft")

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_production_manifest(
    *,
    chapter_id: int,
    creative_brief_path: str | Path | None = None,
    fiction_draft_path: str | Path | None = None,
    state_delta_path: str | Path | None = None,
    writer_model: str = "",
    writer_cost: dict[str, Any] | None = None,
) -> ChapterProductionManifest:
    """Create a ``chapter_production_manifest.yml`` for one v2 chapter.

    All hashes are computed from actual filesystem artifacts.
    """
    data: dict[str, Any] = {
        "schema_version": 2,
        "chapter_id": chapter_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_only": True,
        "production_modified": False,
        "writer_model": writer_model,
        "writer_cost": writer_cost or {},
    }

    if creative_brief_path:
        bp = Path(creative_brief_path)
        if bp.is_file():
            data["creative_brief_sha256"] = hashlib.sha256(
                bp.read_bytes()
            ).hexdigest()

    if fiction_draft_path:
        fp = Path(fiction_draft_path)
        if fp.is_file():
            data["fiction_draft_sha256"] = hashlib.sha256(
                fp.read_bytes()
            ).hexdigest()

    if state_delta_path:
        sp = Path(state_delta_path)
        if sp.is_file():
            data["state_delta_sha256"] = hashlib.sha256(
                sp.read_bytes()
            ).hexdigest()

    data["status"] = (
        "complete"
        if all(
            data.get(k)
            for k in (
                "creative_brief_sha256",
                "fiction_draft_sha256",
                "state_delta_sha256",
            )
        )
        else "draft"
    )

    return ChapterProductionManifest(data)
