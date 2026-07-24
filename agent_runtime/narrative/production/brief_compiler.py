"""Chapter creative brief v2 — bounded editorial contract for Writer.

Replaces the legacy all-dimensions-every-chapter state plan with a v2 brief that
permits at most one primary and one secondary chapter function.  Static, life,
relationship, consequence, and atmosphere chapters are explicitly supported.

The brief compiler converts legacy v1 chapter state plans into v2 creative briefs
and validates both v2-native and converted briefs before Writer input.
"""

from __future__ import annotations

import enum
import hashlib
import os
import re
from pathlib import Path
from typing import Any

import yaml


class ChapterFunction(str, enum.Enum):
    """Allowed chapter functions.  At most one primary plus one secondary."""

    PLOT = "plot"
    CHARACTER = "character"
    RELATIONSHIP = "relationship"
    WORLD = "world"
    FORESHADOWING = "foreshadowing"
    EMOTION = "emotion"
    TIME = "time"
    STATIC = "static"
    LIFE = "life"
    RELATIONSHIP_ONLY = "relationship_only"
    CONSEQUENCE = "consequence"
    ATMOSPHERE = "atmosphere"


# Functions that require no mandated state change at all.
_NON_ADVANCING_FUNCTIONS: frozenset[str] = frozenset(
    {
        ChapterFunction.STATIC.value,
        ChapterFunction.LIFE.value,
        ChapterFunction.RELATIONSHIP_ONLY.value,
        ChapterFunction.CONSEQUENCE.value,
        ChapterFunction.ATMOSPHERE.value,
    }
)

BRIEF_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "chapter_id",
    "primary_function",
    "pov",
    "opposing_wants",
    "turn",
    "cost",
    "reader_question",
    "must_preserve",
    "creative_freedom",
    "source_hashes",
)

BRIEF_OPTIONAL_FIELDS: tuple[str, ...] = (
    "secondary_function",
    "recent_patterns_to_avoid",
    "risk_signals",
    "word_count_target",
    "must_not_repeat",
    "forbidden_facts",
    "fact_invention_policy",
)

_V1_DIMENSION_MAP: dict[str, str] = {
    "plot_state_changes": ChapterFunction.PLOT.value,
    "character_changes": ChapterFunction.CHARACTER.value,
    "character_state_change": ChapterFunction.CHARACTER.value,
    "relationship_or_worldline_changes": ChapterFunction.RELATIONSHIP.value,
    "relationship_or_worldline_change": ChapterFunction.RELATIONSHIP.value,
    "foreshadowing": ChapterFunction.FORESHADOWING.value,
    "foreshadowing_action": ChapterFunction.FORESHADOWING.value,
    "timeline": ChapterFunction.TIME.value,
    "timeline_slot": ChapterFunction.TIME.value,
}

_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(f.value for f in ChapterFunction)


# ---------------------------------------------------------------------------
# CreativeBrief type
# ---------------------------------------------------------------------------


class CreativeBrief:
    """Immutable creative brief for one chapter."""

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = dict(data)

    @property
    def chapter_id(self) -> int:
        return int(self._data["chapter_id"])

    @property
    def primary_function(self) -> str:
        return str(self._data["primary_function"])

    @property
    def secondary_function(self) -> str | None:
        val = self._data.get("secondary_function")
        return str(val) if val else None

    @property
    def pov(self) -> str:
        return str(self._data["pov"])

    @property
    def opposing_wants(self) -> str:
        return str(self._data["opposing_wants"])

    @property
    def turn(self) -> str:
        return str(self._data["turn"])

    @property
    def cost(self) -> str:
        return str(self._data["cost"])

    @property
    def reader_question(self) -> str:
        return str(self._data["reader_question"])

    @property
    def must_preserve(self) -> list[str]:
        return list(self._data.get("must_preserve") or [])

    @property
    def must_not_repeat(self) -> list[str]:
        return list(self._data.get("must_not_repeat") or [])

    @property
    def forbidden_facts(self) -> list[str]:
        return list(self._data.get("forbidden_facts") or [])

    @property
    def fact_invention_policy(self) -> dict[str, Any]:
        return dict(self._data.get("fact_invention_policy") or {})

    @property
    def creative_freedom(self) -> list[str]:
        return list(self._data.get("creative_freedom") or [])

    @property
    def recent_patterns_to_avoid(self) -> list[str]:
        return list(self._data.get("recent_patterns_to_avoid") or [])

    @property
    def risk_signals(self) -> list[str]:
        return list(self._data.get("risk_signals") or [])

    @property
    def source_hashes(self) -> dict[str, str]:
        return dict(self._data.get("source_hashes") or {})

    @property
    def word_count_target(self) -> tuple[int, int] | None:
        val = self._data.get("word_count_target")
        if isinstance(val, list) and len(val) == 2:
            return (int(val[0]), int(val[1]))
        return None

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


# ---------------------------------------------------------------------------
# Brief compilation
# ---------------------------------------------------------------------------


class BriefCompiler:
    """Compile legacy v1 chapter state plans into v2 creative briefs.

    Does not call any provider or mutate production.  Used as a read-time
    conversion before the Writer input.
    """

    @staticmethod
    def from_v1_state_plan(
        plan: dict[str, Any],
        *,
        chapter_id: int | None = None,
        source_paths: list[str] | None = None,
    ) -> CreativeBrief:
        """Convert a validated v1 chapter_state_plan entry to a v2 brief.

        Args:
            plan: One entry from a v1 ``chapter_state_plan`` list.
            chapter_id: Explicit override; inferred from ``plan["chapter"]``
                when absent.
            source_paths: Paths whose SHA256 are recorded in ``source_hashes``.

        Returns:
            A validated ``CreativeBrief``.
        """
        cid = chapter_id if chapter_id is not None else int(plan.get("chapter") or 0)
        if cid <= 0:
            raise ValueError("chapter_id is required and must be positive")

        # --- primary function: map the first populated v1 dimension ----------
        primary = BriefCompiler._infer_primary_function(plan)
        secondary = BriefCompiler._infer_secondary_function(plan, primary)

        # --- POV ------------------------------------------------------------
        pov = str(plan.get("pov") or plan.get("opening_state") or "").strip()
        if not pov:
            pov = "third_person_limited"

        # --- opposing wants -------------------------------------------------
        drive = plan.get("protagonist_drive")
        drive = drive if isinstance(drive, dict) else {}
        wants = str(
            plan.get("opposing_wants")
            or (
                f"{drive.get('current_goal')} vs {drive.get('obstacle')}"
                if drive.get("current_goal") and drive.get("obstacle")
                else ""
            )
            or plan.get("scene_goal")
            or ""
        ).strip()
        if not wants:
            wants = "character_desire_vs_obstacle"

        # --- turn -----------------------------------------------------------
        turn = str(
            plan.get("turn")
            or plan.get("irreversible_plot_change")
            or ""
        ).strip()

        # --- cost -----------------------------------------------------------
        cost = str(
            plan.get("cost")
            or plan.get("closing_state")
            or ""
        ).strip()

        # --- reader question ------------------------------------------------
        hook = plan.get("hook_contract")
        hook = hook if isinstance(hook, dict) else {}
        reader_q = str(
            plan.get("reader_question") or hook.get("reader_question") or ""
        ).strip()
        if not reader_q:
            reader_q = "what_happens_next"

        # --- must-preserve --------------------------------------------------
        must_preserve: list[str] = []
        mp_raw = plan.get("must_preserve")
        if isinstance(mp_raw, list):
            must_preserve = [str(item) for item in mp_raw if str(item).strip()]
        elif isinstance(mp_raw, str) and mp_raw.strip():
            must_preserve = [mp_raw.strip()]
        must_not_repeat: list[str] = []
        mnr_raw = plan.get("must_not_repeat")
        if isinstance(mnr_raw, list):
            must_not_repeat = [
                str(item) for item in mnr_raw if str(item).strip()
            ]
        elif isinstance(mnr_raw, str) and mnr_raw.strip():
            must_not_repeat = [mnr_raw.strip()]
        forbidden_facts: list[str] = []
        ff_raw = plan.get("forbidden_facts")
        if isinstance(ff_raw, list):
            forbidden_facts = [
                str(item) for item in ff_raw if str(item).strip()
            ]
        elif isinstance(ff_raw, str) and ff_raw.strip():
            forbidden_facts = [ff_raw.strip()]
        fact_invention_policy = (
            dict(plan.get("fact_invention_policy") or {})
            if isinstance(plan.get("fact_invention_policy"), dict)
            else {}
        )

        # --- creative freedom -----------------------------------------------
        creative: list[str] = []
        cf_raw = plan.get("creative_freedom")
        if isinstance(cf_raw, list):
            creative = [str(item) for item in cf_raw if str(item).strip()]
        elif isinstance(cf_raw, str) and cf_raw.strip():
            creative = [cf_raw.strip()]

        # --- source hashes --------------------------------------------------
        hashes: dict[str, str] = {}
        for src in source_paths or []:
            p = Path(src).resolve()
            if not p.is_file():
                raise FileNotFoundError(
                    f"source file missing or unreadable: {src}"
                )
            # Use canonical absolute path as key to preserve same-basename
            # paths without collision.  Hash raw bytes; require lowercase
            # 64-hex.  Never persist "unavailable" or "unknown" placeholders.
            hashes[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
            # Validate hex format: exactly 64 lowercase hex chars.
            if not re.fullmatch(r"[a-f0-9]{64}", hashes[str(p)]):
                raise ValueError(f"source hash is not 64-hex lowercase: {hashes[str(p)]}")

        # --- patterns / risks -----------------------------------------------
        patterns = []
        rp_raw = plan.get("recent_patterns_to_avoid")
        if isinstance(rp_raw, list):
            patterns = [str(item) for item in rp_raw if str(item).strip()]

        risks: list[str] = []
        rs_raw = plan.get("risk_signals")
        if isinstance(rs_raw, list):
            risks = [str(item) for item in rs_raw if str(item).strip()]

        # --- word count -----------------------------------------------------
        wc_target = None
        for field in ("target_character_range", "hard_character_range"):
            val = plan.get(field)
            if (
                isinstance(val, list)
                and len(val) == 2
                and all(isinstance(v, int) for v in val)
            ):
                wc_target = [int(val[0]), int(val[1])]
                break

        data: dict[str, Any] = {
            "schema_version": 2,
            "chapter_id": cid,
            "primary_function": primary,
            "pov": pov,
            "opposing_wants": wants,
            "turn": turn,
            "cost": cost,
            "reader_question": reader_q,
            "must_preserve": must_preserve,
            "must_not_repeat": must_not_repeat,
            "forbidden_facts": forbidden_facts,
            "creative_freedom": creative,
            "source_hashes": hashes,
            "v1_source": True,
        }
        if plan.get("schema_version") == "chapter-contract/v3":
            data["fact_invention_policy"] = fact_invention_policy
            data["v1_source"] = False
            data["chapter_position"] = plan.get("chapter_position")
            data["chapter_contract"] = {
                "protagonist_drive": drive,
                "character_intent_gate": plan.get("character_intent_gate") or {},
                "supporting_actor_states": plan.get("supporting_actor_states") or [],
                "hook_contract": hook,
                "foreshadow_actions": plan.get("foreshadow_actions") or [],
                "world_state_delta": plan.get("world_state_delta"),
                "fact_invention_policy": fact_invention_policy,
            }
        if secondary:
            data["secondary_function"] = secondary
        if patterns:
            data["recent_patterns_to_avoid"] = patterns
        if risks:
            data["risk_signals"] = risks
        if wc_target:
            data["word_count_target"] = wc_target

        # Validate the assembled brief.
        issues = validate_creative_brief(data)
        if issues:
            raise ValueError(
                f"v1→v2 brief conversion produced invalid brief: {'; '.join(issues)}"
            )
        return CreativeBrief(data)

    @staticmethod
    def _infer_primary_function(plan: dict[str, Any]) -> str:
        """Heuristic: return the first populated v1 dimension as the primary."""
        for v1_field, v2_func in _V1_DIMENSION_MAP.items():
            value = plan.get(v1_field)
            if isinstance(value, str) and value.strip():
                return v2_func
            if isinstance(value, list) and value:
                return v2_func
        # Fallback: inspect scene_goal and irreversible_plot_change text.
        goal = str(plan.get("scene_goal") or "").lower()
        if any(w in goal for w in ("关系", "relationship", "对话", "日常", "生活")):
            return ChapterFunction.RELATIONSHIP.value
        if any(w in goal for w in ("气氛", "氛围", "描写", "场景", "世界", "设定")):
            return ChapterFunction.WORLD.value
        return ChapterFunction.PLOT.value

    @staticmethod
    def _infer_secondary_function(
        plan: dict[str, Any], primary: str
    ) -> str | None:
        """Return the second populated v1 dimension (if any), skipping *primary*."""
        found: list[str] = []
        for v1_field, v2_func in _V1_DIMENSION_MAP.items():
            if v2_func == primary:
                continue
            value = plan.get(v1_field)
            if isinstance(value, str) and value.strip():
                found.append(v2_func)
            elif isinstance(value, list) and value:
                found.append(v2_func)
        return found[0] if found else None


# ---------------------------------------------------------------------------
# Brief validation
# ---------------------------------------------------------------------------

def validate_creative_brief(data: dict[str, Any]) -> list[str]:
    """Validate a creative brief (v2-native or converted).

    Returns a list of issue strings (empty → valid).
    """
    issues: list[str] = []

    if not isinstance(data, dict):
        return ["brief_root_must_be_mapping"]

    # --- schema_version ----------------------------------------------------
    sv = data.get("schema_version")
    if sv not in (2, "2"):
        issues.append("schema_version_must_be_2")

    # --- chapter_id --------------------------------------------------------
    cid = data.get("chapter_id")
    if not isinstance(cid, int) or cid <= 0:
        issues.append("chapter_id_must_be_positive_integer")

    # --- primary_function --------------------------------------------------
    pf = str(data.get("primary_function") or "").strip()
    if pf not in _ALLOWED_FUNCTIONS:
        issues.append(
            f"primary_function_invalid:{pf or '<missing>'}"
        )
    if pf in _NON_ADVANCING_FUNCTIONS:
        # Non-advancing functions must not have a secondary that IS advancing.
        sf = str(data.get("secondary_function") or "").strip()
        if sf and sf not in _NON_ADVANCING_FUNCTIONS:
            issues.append(
                f"non_advancing_primary_with_advancing_secondary:{pf}+{sf}"
            )

    # --- secondary_function ------------------------------------------------
    sf = data.get("secondary_function")
    if sf is not None:
        sf = str(sf).strip()
        if sf and sf not in _ALLOWED_FUNCTIONS:
            issues.append(f"secondary_function_invalid:{sf}")
        if isinstance(sf, str) and sf and sf == pf:
            issues.append("secondary_function_duplicates_primary")
        # Detect multiple secondary functions passed as list.
        if isinstance(data.get("secondary_function"), list):
            issues.append("secondary_function_must_be_single_string_not_list")

    # --- required text fields ----------------------------------------------
    for field in ("pov", "opposing_wants", "turn", "cost", "reader_question"):
        val = data.get(field)
        if not isinstance(val, str) or not val.strip():
            issues.append(f"missing_or_empty:{field}")
        elif val.strip().casefold() in {
            "what_happens_next",
            "what happens next",
            "character_desire_vs_obstacle",
            "character desire vs obstacle",
        }:
            issues.append(f"placeholder_not_allowed:{field}")

    # --- must_preserve -----------------------------------------------------
    mp = data.get("must_preserve")
    if not isinstance(mp, list) or not all(isinstance(v, str) for v in mp):
        issues.append("must_preserve_must_be_string_list")
    for field in ("must_not_repeat", "forbidden_facts"):
        value = data.get(field, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            issues.append(f"{field}_must_be_nonempty_string_list")
    fact_policy = data.get("fact_invention_policy")
    if fact_policy is not None:
        if not isinstance(fact_policy, dict):
            issues.append("fact_invention_policy_must_be_mapping")
        else:
            absent_rule = fact_policy.get("absent_fact_rule")
            if not isinstance(absent_rule, str) or not absent_rule.strip():
                issues.append("fact_invention_policy_absent_fact_rule_required")
            for field in (
                "allowed_scene_texture",
                "forbidden_persistent_fact_classes",
            ):
                value = fact_policy.get(field)
                if not (
                    isinstance(value, list)
                    and value
                    and all(
                        isinstance(item, str) and item.strip() for item in value
                    )
                ):
                    issues.append(
                        f"fact_invention_policy_{field}_must_be_nonempty_string_list"
                    )

    # --- creative_freedom --------------------------------------------------
    cf = data.get("creative_freedom")
    if not isinstance(cf, list) or not all(isinstance(v, str) for v in cf):
        issues.append("creative_freedom_must_be_string_list")

    # --- source_hashes -----------------------------------------------------
    sh = data.get("source_hashes")
    if not isinstance(sh, dict):
        issues.append("source_hashes_must_be_mapping")
    elif not sh:
        # Empty source_hashes blocks: every creative brief must carry at
        # least one canonical-path → SHA256 mapping.  No placeholder or
        # unavailable sentinel is accepted.
        issues.append("source_hashes_must_not_be_empty")
    else:
        for k, v in sh.items():
            if not isinstance(k, str) or not isinstance(v, str):
                issues.append(f"invalid_source_hash_entry:{k}")
                continue
            # Require lowercase 64-hex values.
            if not re.fullmatch(r"[a-f0-9]{64}", v):
                issues.append(f"source_hash_not_64_hex_lowercase:{k}:{v}")
            # Reject placeholder values.
            if v in ("unavailable", "unknown", ""):
                issues.append(f"source_hash_is_placeholder:{k}:{v}")
            # Require canonical absolute paths as keys.  Pathlib semantics
            # replace weak startswith("/") — empty, whitespace, relative,
            # dot-segment, double-slash, and root-directory keys all block.
            # A canonical key must be a non-empty stripped absolute path
            # with no "." or ".." segments and no redundant separators.
            if not isinstance(k, str) or not k.strip():
                issues.append(f"source_hash_key_empty_or_whitespace:{k!r}")
            elif not Path(k).is_absolute():
                issues.append(f"source_hash_key_not_canonical_absolute:{k}")
            else:
                # Raw-string dot-segment check (pathlib normalizes "." away).
                raw_segments = k.split(os.sep)
                if "." in raw_segments or ".." in raw_segments:
                    issues.append(f"source_hash_key_has_dot_segments:{k}")
                # Redundant // anywhere.
                if "//" in k:
                    issues.append(f"source_hash_key_not_canonical:{k}")
                # Root-only path.
                if k == "/":
                    issues.append(f"source_hash_key_not_canonical:{k}")
                # os.path.normpath catches trailing slashes and other forms.
                if os.path.normpath(k) != k:
                    issues.append(f"source_hash_key_not_canonical:{k}")
                source_path = Path(k)
                if str(source_path.resolve(strict=False)) != k:
                    issues.append(f"source_hash_key_not_canonical:{k}")
                # Native and converted briefs use the same trust boundary:
                # the path must identify a live file and its recorded digest
                # must match the current raw bytes.
                if not source_path.is_file():
                    issues.append(f"source_hash_key_not_file:{k}")
                else:
                    try:
                        observed_hash = hashlib.sha256(
                            source_path.read_bytes()
                        ).hexdigest()
                    except OSError:
                        issues.append(f"source_hash_key_not_file:{k}")
                    else:
                        if observed_hash != v:
                            issues.append(
                                f"source_hash_mismatch:{k}:{v}:{observed_hash}"
                            )

    # --- optional list fields (when present) --------------------------------
    for field in ("recent_patterns_to_avoid", "risk_signals"):
        val = data.get(field)
        if val is not None and (
            not isinstance(val, list)
            or not all(isinstance(v, str) for v in val)
        ):
            issues.append(f"{field}_must_be_string_list")

    # --- word_count_target (when present) -----------------------------------
    wc = data.get("word_count_target")
    if wc is not None and (
        not isinstance(wc, list)
        or len(wc) != 2
        or not all(isinstance(v, int) and v > 0 for v in wc)
        or wc[0] > wc[1]
    ):
        issues.append("word_count_target_invalid")

    return issues


def compile_creative_brief(
    plan: dict[str, Any],
    *,
    chapter_id: int | None = None,
    source_paths: list[str] | None = None,
) -> CreativeBrief:
    """Public entry-point: compile a v1 state plan into a v2 CreativeBrief."""
    return BriefCompiler.from_v1_state_plan(
        plan, chapter_id=chapter_id, source_paths=source_paths
    )
