"""ContextCompiler — assembles immutable, hash-bound shared narrative context.

Wraps ``context_bundle.build_context_bundle`` with narrative-domain validation,
relevance filtering, role-slice assembly, and metric reporting.  Does NOT call
providers or mutate production.

Key invariants:
- Creative brief is validated with ``validate_creative_brief`` before any bundle
  write; every declared source hash is recomputed and stale/mismatched entries
  block compilation.
- CreativeBrief bytes and SHA256 are included in the content-addressed manifest
  identity — storing only its source files is not sufficient.
- Predecessor chapter identity is explicit: ``predecessor_chapter_id`` must
  equal ``chapter_id - 1`` for chapter_id > 1, and predecessor prose bytes are
  bound by SHA256.  Chapter 1 remains predecessor-free.
- Cross-slice duplication is removed before bundle construction: a file already
  in shared context cannot remain private; a file requested by multiple roles
  becomes shared once.  ``duplicate_context_ratio`` is derived from actual
  naive-versus-unique byte counts.
- Advisory pattern signals are advisory only.  Any signal containing
  authoritative fields (status, pass, accept, seal, promotion) is rejected
  instead of being returned with ``advisory=true``.  Caller-owned values are
  never mutated.
- Canon snapshot and hard state are always required.  Optional inputs are
  selected by explicit relevance only.
- Unrelated chapter prose is never loaded.
- The shared context manifest is built once and reused by hash.
- Each role gets the same shared bundle ID plus only its private slice.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.narrative.efficiency.context_bundle import build_context_bundle
from agent_runtime.narrative.production.brief_compiler import (
    CreativeBrief,
    validate_creative_brief,
)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

# Authoritative fields that MUST NOT appear in advisory pattern signals.
_AUTHORITATIVE_SIGNAL_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "literary_status",
        "literary_pass",
        "pass",
        "accept",
        "accepted",
        "seal",
        "promotion",
        "promotion_status",
        "promote",
    }
)


@dataclass
class ContextRequest:
    """Input to ContextCompiler.compile()."""

    chapter_id: int

    # ---- required inputs ---------------------------------------------------
    creative_brief: CreativeBrief
    canon_snapshot_path: Path
    hard_state_path: Path

    # ---- required when chapter_id > 1 -------------------------------------
    predecessor_prose_path: Path | None = None
    predecessor_chapter_id: int | None = None
    predecessor_prose_sha256: str | None = None

    # ---- optional, selected by explicit relevance only ---------------------
    voice_memory_paths: list[Path] = field(default_factory=list)
    life_debt_paths: list[Path] = field(default_factory=list)
    pattern_signal_paths: list[Path] = field(default_factory=list)
    reader_question_paths: list[Path] = field(default_factory=list)

    # ---- role-specific private slices --------------------------------------
    role_slices: dict[str, list[Path]] = field(default_factory=dict)

    # ---- output configuration ----------------------------------------------
    output_dir: Path | None = None
    source_root: Path | None = None


@dataclass
class ContextResult:
    """Output of ContextCompiler.compile()."""

    chapter_id: int
    status: str  # "pass" | "blocked"

    # Bundle identity
    context_bundle_id: str = ""
    manifest_path: str = ""
    manifest_sha256: str = ""
    reused: bool = False

    # Evidence records — every loaded file records relative path, bytes, sha256.
    shared_files: list[dict[str, Any]] = field(default_factory=list)
    role_specific_files: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # Metrics — derive from actual loaded records, never estimated.
    total_files_loaded: int = 0
    total_bytes_loaded: int = 0
    duplicate_context_ratio: float = 0.0
    duplicate_bytes_saved: int = 0

    # Advisory pattern signals.  Authoritative fields (status, pass, accept,
    # seal, promotion) are rejected — a signal with any of those keys is
    # excluded.  The ``advisory`` flag is always true on included signals;
    # downstream consumers must enforce the constraint.
    pattern_signals: list[dict[str, Any]] = field(default_factory=list)

    # Validation issues (empty → pass).
    issues: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ContextCompiler
# ---------------------------------------------------------------------------


class ContextCompiler:
    """Assemble immutable, hash-bound shared narrative context and role slices.

    Usage::

        result = ContextCompiler.compile(ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=Path("canon/canon_snapshot.yml"),
            hard_state_path=Path("state/hard_state.yml"),
            predecessor_prose_path=Path("prose/ch024.md"),
            predecessor_chapter_id=24,
            output_dir=Path("bundles"),
            source_root=Path("."),
        ))
        assert result.status == "pass"
    """

    @staticmethod
    def compile(request: ContextRequest) -> ContextResult:
        """Validate inputs, build the shared bundle, and return a ContextResult."""
        issues: list[str] = []

        # ---- 1. Validate required inputs -----------------------------------
        if request.chapter_id <= 0:
            issues.append("chapter_id_must_be_positive")

        # 1a. Creative brief — validate with the canonical validator AND
        #     recompute every declared source hash.  Stale or mismatched
        #     source hashes block compilation.
        creative_brief_bytes: bytes = b""
        creative_brief_sha256: str = ""
        if request.creative_brief is None:
            issues.append("creative_brief_is_required")
        else:
            brief_dict = request.creative_brief.to_dict()
            brief_issues = validate_creative_brief(brief_dict)
            if brief_issues:
                for bi in brief_issues:
                    issues.append(f"creative_brief_validation:{bi}")

            if request.creative_brief.chapter_id != request.chapter_id:
                issues.append(
                    f"creative_brief_chapter_mismatch:"
                    f"brief={request.creative_brief.chapter_id}"
                    f" request={request.chapter_id}"
                )

            # Recompute every declared source hash and block stale/mismatched.
            for src_key, declared_hash in request.creative_brief.source_hashes.items():
                src_path = Path(src_key)
                if not src_path.is_file():
                    issues.append(
                        f"creative_brief_source_file_missing:{src_key}"
                    )
                else:
                    try:
                        observed = hashlib.sha256(
                            src_path.read_bytes()
                        ).hexdigest()
                    except OSError:
                        issues.append(
                            f"creative_brief_source_unreadable:{src_key}"
                        )
                    else:
                        if observed != declared_hash:
                            issues.append(
                                f"creative_brief_source_hash_mismatch:"
                                f"{src_key}:declared={declared_hash}"
                                f":observed={observed}"
                            )

            # Compute canonical CreativeBrief bytes and SHA256 for the
            # content-addressed manifest identity.
            creative_brief_bytes = json.dumps(
                brief_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            creative_brief_sha256 = hashlib.sha256(creative_brief_bytes).hexdigest()

        if request.canon_snapshot_path is None:
            issues.append("canon_snapshot_path_is_required")
        elif not request.canon_snapshot_path.is_file():
            issues.append(
                f"canon_snapshot_not_found:{request.canon_snapshot_path}"
            )

        if request.hard_state_path is None:
            issues.append("hard_state_path_is_required")
        elif not request.hard_state_path.is_file():
            issues.append(
                f"hard_state_not_found:{request.hard_state_path}"
            )

        # ---- 2. Predecessor boundary with explicit provenance --------------
        predecessor_sha256: str = ""
        if request.chapter_id > 1:
            # Require explicit predecessor chapter identity.
            if request.predecessor_chapter_id is None:
                issues.append(
                    "predecessor_chapter_id_is_required_when_chapter_id_greater_than_one"
                )
            elif request.predecessor_chapter_id != request.chapter_id - 1:
                issues.append(
                    f"wrong_predecessor_chapter_id:"
                    f"expected={request.chapter_id - 1}"
                    f" got={request.predecessor_chapter_id}"
                )

            if request.predecessor_prose_path is None:
                issues.append(
                    "predecessor_prose_is_required_when_chapter_id_greater_than_one"
                )
            elif not request.predecessor_prose_path.is_file():
                issues.append(
                    f"predecessor_prose_not_found:"
                    f"{request.predecessor_prose_path}"
                )
            else:
                # Bind predecessor prose bytes by SHA256 for provenance.
                predecessor_sha256 = hashlib.sha256(
                    request.predecessor_prose_path.read_bytes()
                ).hexdigest()
                if (
                    request.predecessor_prose_sha256 is not None
                    and request.predecessor_prose_sha256 != predecessor_sha256
                ):
                    issues.append(
                        "predecessor_prose_hash_mismatch:"
                        f"declared={request.predecessor_prose_sha256}:"
                        f"observed={predecessor_sha256}"
                    )

        # Chapter 1 MUST NOT require predecessor prose or identity.
        if request.chapter_id == 1:
            if request.predecessor_prose_path is not None:
                issues.append("chapter_1_must_not_have_predecessor_prose")
            if request.predecessor_chapter_id is not None:
                issues.append("chapter_1_must_not_have_predecessor_chapter_id")
            if request.predecessor_prose_sha256 is not None:
                issues.append("chapter_1_must_not_have_predecessor_prose_sha256")

        # ---- 3. Validate optional paths (explicit relevance only) ----------
        for category, paths in (
            ("voice_memory", request.voice_memory_paths),
            ("life_debt", request.life_debt_paths),
            ("pattern_signal", request.pattern_signal_paths),
            ("reader_question", request.reader_question_paths),
        ):
            for p in paths:
                if not p.is_file():
                    issues.append(f"{category}_not_found:{p}")

        pattern_signals: list[dict[str, Any]] = []
        for path in request.pattern_signal_paths:
            if not path.is_file():
                continue
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:
                issues.append(
                    f"pattern_signal_unreadable:{path}:{type(exc).__name__}"
                )
                continue
            items = raw if isinstance(raw, list) else [raw]
            for item in items:
                if not isinstance(item, dict):
                    continue
                signal = copy.deepcopy(item)
                forbidden = _authoritative_signal_fields(signal)
                if forbidden:
                    issues.append(
                        "authoritative_pattern_signal_field:"
                        + ",".join(sorted(forbidden))
                    )
                    continue
                signal["advisory"] = True
                pattern_signals.append(signal)

        # ---- 4. Validate role slice paths ----------------------------------
        for role, paths in request.role_slices.items():
            for p in paths:
                if not p.is_file():
                    issues.append(f"role_slice_not_found:{role}:{p}")

        if issues:
            return ContextResult(
                chapter_id=request.chapter_id,
                status="blocked",
                issues=issues,
            )

        # ---- 5. Determine source root --------------------------------------
        source_root = request.source_root or Path.cwd()
        output_dir = request.output_dir or Path.cwd() / "bundles"

        # ---- 6. Collect shared files ---------------------------------------
        shared_files: list[Path] = []

        # 6a. Canon snapshot (always).
        shared_files.append(request.canon_snapshot_path)

        # 6b. Hard state (always).
        shared_files.append(request.hard_state_path)

        # 6c. Predecessor prose (only when chapter_id > 1).
        if request.chapter_id > 1 and request.predecessor_prose_path is not None:
            shared_files.append(request.predecessor_prose_path)

        # 6d. Creative brief source files (from source_hashes).
        # Hashes were already validated in step 1a.
        if request.creative_brief is not None:
            for src_path_str in request.creative_brief.source_hashes:
                src_path = Path(src_path_str)
                if src_path.is_file() and src_path not in shared_files:
                    shared_files.append(src_path)

        # ---- 7. Collect optional files (explicit relevance only) -----------
        optional_shared: list[Path] = []
        for paths in (
            request.voice_memory_paths,
            request.life_debt_paths,
            request.reader_question_paths,
        ):
            for p in paths:
                if p not in shared_files and p not in optional_shared:
                    optional_shared.append(p)

        # Pattern signal files are NOT added to shared context — they are
        # advisory metadata, not narrative input.

        # ---- 8. Cross-slice deduplication -----------------------------------
        # A file already in shared context cannot remain private; a file
        # requested by multiple roles becomes shared once.

        # Deduplicate shared files (preserve insertion order).
        shared_seen: set[str] = set()
        deduped_shared: list[Path] = []
        for p in shared_files + optional_shared:
            key = str(p.resolve())
            if key not in shared_seen:
                shared_seen.add(key)
                deduped_shared.append(p)

        # Files requested by more than one role become shared before any role
        # slice is emitted, so the first role cannot retain a duplicate.
        role_occurrences: dict[str, tuple[Path, set[str]]] = {}
        for role, paths in request.role_slices.items():
            for path in paths:
                key = str(path.resolve())
                if key not in role_occurrences:
                    role_occurrences[key] = (path, set())
                role_occurrences[key][1].add(role)
        for key, (path, roles) in role_occurrences.items():
            if len(roles) > 1 and key not in shared_seen:
                shared_seen.add(key)
                deduped_shared.append(path)

        # Build role-specific file map, removing every file now in shared.
        role_specific_map: dict[str, list[Path]] = {}
        for role, paths in sorted(request.role_slices.items()):
            role_deduped: list[Path] = []
            role_seen: set[str] = set()
            for p in paths:
                key = str(p.resolve())
                if key in shared_seen or key in role_seen:
                    continue
                role_seen.add(key)
                role_deduped.append(p)
            if role_deduped:
                role_specific_map[role] = role_deduped

        # ---- 9. Compute naive-vs-unique metrics for duplicate ratio ---------
        # Naive total: sum of bytes if every file in every slice were loaded
        # independently (shared × 1 + sum over roles of their files).
        naive_shared_bytes = sum(
            len(Path(p).read_bytes())
            for p in shared_files + optional_shared
            if Path(p).is_file()
        )
        naive_role_bytes = sum(
            len(Path(p).read_bytes())
            for paths in request.role_slices.values()
            for p in paths
            if Path(p).is_file()
        )
        naive_total = naive_shared_bytes + naive_role_bytes

        # Unique total: bytes of distinct files actually loaded.
        unique_paths: set[str] = set(shared_seen)
        for paths in request.role_slices.values():
            for p in paths:
                key = str(p.resolve())
                if key not in shared_seen:
                    unique_paths.add(key)
        unique_total = sum(
            len(Path(p).read_bytes()) for p_key in unique_paths
            if (p := Path(p_key)).is_file()
        )

        duplicate_bytes_saved = max(0, naive_total - unique_total)
        duplicate_context_ratio = (
            duplicate_bytes_saved / naive_total if naive_total > 0 else 0.0
        )

        # ---- 10. Build the context bundle -----------------------------------
        try:
            bundle = build_context_bundle(
                output_dir,
                source_root=source_root,
                canon_snapshot_sha256=_sha256_file(request.canon_snapshot_path),
                chapter_window=[request.chapter_id],
                shared_files=deduped_shared,
                role_specific_files=role_specific_map,
                creative_brief=json.loads(creative_brief_bytes.decode("utf-8")),
                creative_brief_sha256=creative_brief_sha256,
                predecessor_sha256=predecessor_sha256 or None,
            )
        except Exception as exc:
            return ContextResult(
                chapter_id=request.chapter_id,
                status="blocked",
                issues=[f"bundle_build_failed:{type(exc).__name__}:{exc}"],
            )

        # ---- 11. Compute metrics from actual loaded records -----------------
        shared_records: list[dict[str, Any]] = list(
            bundle.get("shared_files") or []
        )
        role_records: dict[str, list[dict[str, Any]]] = {}
        for role, records in (bundle.get("role_specific_files") or {}).items():
            role_records[str(role)] = list(records)

        total_files = len(shared_records) + sum(
            len(recs) for recs in role_records.values()
        )
        total_bytes = sum(
            int(r.get("bytes", 0)) for r in shared_records
        ) + sum(
            int(r.get("bytes", 0))
            for recs in role_records.values()
            for r in recs
        )

        # ---- 12. Return result ----------------------------------------------
        return ContextResult(
            chapter_id=request.chapter_id,
            status="pass",
            context_bundle_id=str(bundle.get("context_bundle_id") or ""),
            manifest_path=str(bundle.get("manifest_path") or ""),
            manifest_sha256=str(bundle.get("manifest_sha256") or ""),
            reused=bool(bundle.get("reused")),
            shared_files=shared_records,
            role_specific_files=role_records,
            total_files_loaded=total_files,
            total_bytes_loaded=total_bytes,
            duplicate_context_ratio=duplicate_context_ratio,
            duplicate_bytes_saved=duplicate_bytes_saved,
            pattern_signals=pattern_signals,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Return lowercase 64-hex SHA-256 of *path* contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authoritative_signal_fields(value: Any) -> set[str]:
    """Return forbidden authority keys found anywhere in a signal."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _AUTHORITATIVE_SIGNAL_FIELDS:
                found.add(normalized)
            found.update(_authoritative_signal_fields(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_authoritative_signal_fields(child))
    return found
