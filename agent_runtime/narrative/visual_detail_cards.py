"""Deterministic visual continuity cards for longform narrative production.

The module turns human/model-authored structured facts into immutable prompt sets.
It does not generate images and cannot promote a card or an image into project canon.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from agent_runtime.narrative.user_acceptance import (
    _pinned_public_key,
    _verify_external_signature,
)
from agent_runtime.protocols.enforcement import check_role_binding
from agent_runtime.task_runtime_v2 import (
    EntityNotFound,
    InvalidTransition,
    LedgerIntegrityError,
    TaskRuntime,
)


SPEC_SCHEMA = "narrative-visual-detail-spec/v3"
PACK_SCHEMA = "narrative-visual-detail-card-pack/v3"
LEGACY_PACK_SCHEMA = "narrative-visual-detail-card-pack/v1"
LEGACY_V2_PACK_SCHEMA = "narrative-visual-detail-card-pack/v2"
LEGACY_V2_SPEC_SCHEMA = "narrative-visual-detail-spec/v2"
AWAITING_ACCEPTANCE = "awaiting_visual_generation_and_human_acceptance"

_KIND_CONTRACTS: dict[str, dict[str, list[str]]] = {
    "character": {
        "required_invariant_fields": [
            "gender",
            "facial_structure",
            "facial_features",
            "skin",
            "eyes",
            "hair_color",
            "hairstyle",
            "hair_accessories",
            "body",
            "hands",
            "signature_details",
            "negative_constraints",
        ],
        "required_variant_fields": [
            "state",
            "wardrobe",
            "grooming",
            "hairstyle",
            "hair_accessories",
            "wear_state",
        ],
        "required_shots": [
            "face-front-neutral",
            "face-three-quarter",
            "face-profile",
            "facial-features-detail",
            "hair-color-style-accessories-detail",
            "full-body-front",
            "full-body-back",
            "full-body-side",
            "hands-detail",
            "garment-construction-detail",
            "state-expression",
            "action-dynamic",
        ],
    },
    "map": {
        "required_invariant_fields": [
            "geography",
            "scale_and_orientation",
            "terrain",
            "water_system",
            "settlements",
            "routes_and_borders",
            "labels",
            "palette_and_style",
            "negative_constraints",
        ],
        "required_variant_fields": ["state", "overlays", "wear_state"],
        "required_shots": [
            "master-map",
            "terrain-relief",
            "route-overlay",
            "regional-detail",
        ],
    },
    "location": {
        "required_invariant_fields": [
            "architecture",
            "terrain_and_layout",
            "materials",
            "light_and_atmosphere",
            "palette",
            "weather_states",
            "signature_details",
            "negative_constraints",
        ],
        "required_variant_fields": ["state", "lighting", "seasonal_detail"],
        "required_shots": [
            "establishing-wide",
            "human-eye-level",
            "spatial-reverse",
            "material-detail",
            "weather-state",
        ],
    },
    "prop": {
        "required_invariant_fields": [
            "geometry_and_dimensions",
            "materials",
            "surface_and_color",
            "mechanism",
            "markings",
            "wear_and_damage",
            "handling_scale",
            "negative_constraints",
        ],
        "required_variant_fields": ["state", "context", "wear_state"],
        "required_shots": [
            "orthographic-front",
            "orthographic-back",
            "three-quarter",
            "material-detail",
            "mechanism-detail",
            "in-hand-scale",
        ],
    },
}

_LEGACY_KIND_CONTRACTS = deepcopy(_KIND_CONTRACTS)
_LEGACY_KIND_CONTRACTS["character"] = {
    "required_invariant_fields": [
        "facial_structure",
        "facial_features",
        "skin",
        "eyes",
        "hair",
        "body",
        "hands_and_nails",
        "signature_details",
        "negative_constraints",
    ],
    "required_variant_fields": [
        "state",
        "wardrobe",
        "grooming",
        "manicure",
        "wear_state",
    ],
    "required_shots": [
        "face-front-neutral",
        "face-three-quarter",
        "face-profile",
        "full-body-front",
        "full-body-back",
        "full-body-side",
        "hands-and-nails-detail",
        "garment-construction-detail",
        "state-expression",
        "action-dynamic",
    ],
}

_CHARACTER_DETAIL_FIELDS = {
    "facial_structure": ["face_shape", "forehead", "cheekbones", "jaw", "asymmetry"],
    "facial_features": ["brows", "nose", "lips", "ears", "distinguishing_marks"],
    "eyes": ["shape", "iris_color", "eyelids", "spacing", "gaze"],
    "hair_color": ["base", "undertone", "highlights"],
    "hairstyle": ["length", "texture", "parting", "structure"],
    "hair_accessories": ["primary", "materials", "placement", "secondary"],
}

_CHARACTER_VARIANT_HAIR_FIELDS = {
    "hairstyle": ["form", "front", "back", "texture_state"],
    "hair_accessories": ["items", "materials", "placement", "condition"],
}

_MALE_HAND_PROFILE_OPTIONS = {
    "proportion": {
        "long_narrow": "手掌偏窄、手指修长",
        "broad_square": "手掌宽厚、手指方直",
        "balanced": "手掌宽度中等、手指比例均衡",
        "compact_strong": "手掌紧凑有力、手指略短",
    },
    "joints": {
        "fine_straight": "关节细直、活动灵活",
        "prominent": "关节轮廓明显但无肿胀",
        "thick_straight": "关节粗直、握力感强",
    },
    "callus_pattern": {
        "none": "掌面无职业性厚茧",
        "sword_grip": "虎口与掌根有持剑薄茧",
        "bowstring": "拇指根部与食指侧有弓弦茧",
        "oar_rope": "掌心横向与指根有舟楫绳索茧",
        "brush_abacus": "中指执笔处与指腹有算盘薄茧",
        "manual_labor": "掌心与指根有劳作厚茧",
    },
    "marks": {
        "none": "双手无固定伤痕",
        "right_thenar_scar": "右手虎口有一道旧伤",
        "left_palm_line": "左掌有一道浅色线状旧伤",
        "right_knuckle_scar": "右手食指关节有小块旧疤",
        "old_burn_patch": "左手背有一小片旧烫伤",
    },
    "dominant_hand": {
        "right": "惯用右手",
        "left": "惯用左手",
        "ambidextrous": "双手使用能力接近",
    },
    "hand_armor": {
        "none": "不佩戴手甲或手套",
        "segmented_iron_gauntlet": "外覆分节铁护手，边缘磨圆且不妨碍握持",
        "leather_bracer_glove": "佩戴熟皮护腕连半掌手套，保留关节活动",
    },
}
_MALE_CHARACTER_DETAIL_CONTRACT = {
    "hands": {
        field: list(choices) for field, choices in _MALE_HAND_PROFILE_OPTIONS.items()
    },
    "free_form_hand_prose_allowed": False,
    "nail_detail_allowed": False,
}

_FEMALE_INVARIANT_FIELDS = ["makeup_identity", "legs", "feet"]
_FEMALE_VARIANT_FIELDS = ["makeup", "manicure", "pedicure", "leg_and_foot_state"]
_FEMALE_SHOTS = [
    "makeup-face-detail",
    "hands-and-manicure-detail",
    "legs-detail",
    "feet-and-pedicure-detail",
]
_FEMALE_DETAIL_FIELDS = {
    "makeup_identity": ["skin_texture", "brow_anchor", "eye_anchor", "lip_anchor"],
    "legs": ["proportion", "musculature", "skin", "marks"],
    "feet": ["shape", "arch", "toes", "skin", "marks"],
}
_FEMALE_VARIANT_DETAIL_FIELDS = {
    "makeup": ["complexion", "brows", "eyes", "cheeks", "lips", "finish"],
    "manicure": [
        "style",
        "length",
        "shape",
        "base_color",
        "accent_colors",
        "finish",
        "design",
        "embellishments",
        "condition",
    ],
    "pedicure": [
        "style",
        "length",
        "shape",
        "base_color",
        "accent_colors",
        "finish",
        "design",
        "embellishments",
        "condition",
    ],
    "leg_and_foot_state": ["legs", "feet", "exposure", "footwear_interaction"],
}
_FEMALE_CHARACTER_DETAIL_CONTRACT = {
    "modern_nail_art_allowed": True,
    "nail_art_vocabulary": {
        "styles": [
            "solid",
            "french",
            "gradient",
            "cat-eye",
            "jelly",
            "chrome",
            "aurora",
            "marble",
        ],
        "lengths": ["short", "medium-short", "medium", "long"],
        "shapes": ["round", "squoval", "oval", "almond", "coffin", "stiletto"],
        "finishes": ["matte", "gloss", "glass", "satin", "magnetic", "mirror"],
    },
}

_SHOT_DIRECTIONS = {
    "face-front-neutral": "正面中性表情脸部特写，85mm 人像透视，均匀柔光，完整显示五官比例",
    "face-three-quarter": "同一人物三分之二侧脸特写，保持眼距、鼻形、下颌与发际线",
    "face-profile": "同一人物严格侧面特写，显示额头、鼻梁、唇线、下颌和耳廓轮廓",
    "facial-features-detail": "同一人物五官校准特写，分别核验眉形、眼形与虹膜、鼻形、唇形、耳廓和标志痕迹",
    "hair-color-style-accessories-detail": "同一人物头发设定组图，稳定核验发色层次、发丝质地、分缝、前后发型结构、发饰材质与固定位置",
    "full-body-front": "全身正面自然站姿，头脚完整，显示真实身高、肩腰腿比例和服装层次",
    "full-body-back": "全身背面自然站姿，头脚完整，显示发型后部、衣物背片和下摆结构",
    "full-body-side": "全身严格侧面站姿，显示胸背厚度、骨盆、腿长和鞋履比例",
    "hands-detail": "双手微距细节，仅保留手型、惯用手、茧、伤痕与关节比例",
    "hands-and-nails-detail": "双手与指甲微距细节，保留手型、惯用手、茧、伤痕和美甲状态",
    "makeup-face-detail": "女性妆面校准特写，分别核验底妆质感、眉妆、眼妆、腮红、唇妆与妆效，不得磨除身份痕迹",
    "hands-and-manicure-detail": "女性双手与手部美甲微距，完整显示甲长、甲型、底色、强调色、质感、图案、饰件及当下磨损",
    "legs-detail": "女性腿部正面、侧面与背面细节组图，稳定核验腿长比例、肌肉结构、肤色、膝部与固定标志",
    "feet-and-pedicure-detail": "女性双足自然承重与非承重微距，稳定核验足型、足弓、脚趾排列、皮肤标志及足部美甲的长度、形状、颜色、图案与饰件",
    "garment-construction-detail": "服饰结构细节组图，展示领口、袖口、腰封、接缝、面料与饰件",
    "state-expression": "指定状态下的半身表情定妆照，身份不变，仅允许状态差异",
    "action-dynamic": "符合人物能力的动态全身姿态，面部和身材比例不得漂移",
    "master-map": "完整俯视总图，边界内全部地貌、水系、城市、道路和比例尺可读",
    "terrain-relief": "同一地理拓扑的地形起伏层，强调高程、山口、河谷与流域关系",
    "route-overlay": "同一底图的交通与势力叠加层，路线和节点不得偏移",
    "regional-detail": "从总图按固定比例放大的区域细图，坐标、方位和地标完全对应",
    "establishing-wide": "广角建立镜头，完整展示地标、地形和空间关系",
    "human-eye-level": "人眼高度主视角，保持建筑尺度、动线和固定地标",
    "spatial-reverse": "同一机位轴线的反向视角，用于验证空间拓扑不漂移",
    "material-detail": "材质与工艺微距细节，颜色、磨损、纹理和尺度忠于锁定卡",
    "weather-state": "同一场景在指定天气状态，建筑、地形和物件位置完全不变",
    "orthographic-front": "正交正视图，无透视夸张，尺寸与标记清晰",
    "orthographic-back": "正交背视图，与正视图尺寸、边缘和结构一一对应",
    "three-quarter": "三分之二立体视图，准确显示厚度、连接结构和表面磨损",
    "mechanism-detail": "机关、扣件或可动结构的分解细节，零件关系可核验",
    "in-hand-scale": "由符合设定的手持握，准确证明道具与人体的尺度关系",
}

_GENERATION_CONTRACT = {
    "role": "ArtifactProducer",
    "profile_key": "artifact_producer",
    "profile_authority": "config/agent_model_profiles.yml",
    "required_worker_capability": "codex_managed_image_generation",
    "managed_tool": "image_gen.imagegen",
    "auto_executable": False,
    "reference_images_required_after_first_accepted_generation": True,
}

_REVIEW_CONTRACT = {
    "observer": {
        "role": "Observer",
        "profile_key": "observer",
    },
    "reviewer": {
        "role": "Reviewer",
        "profile_key": "visual_reviewer",
    },
    "producer_self_check": {
        "role": "ArtifactProducer",
        "profile_key": "artifact_producer",
    },
    "verifier": {
        "role": "Verifier",
        "profile_key": "verifier",
    },
    "profile_authority": "config/agent_model_profiles.yml",
    "independence": {
        "producer_self_check_counts_as_independent_acceptance": False,
        "all_stage_session_ids_must_differ": True,
        "reviewer_verifier_backend_model_pair_must_differ": True,
    },
    "required_dimensions": [
        "identity_consistency",
        "wardrobe_and_state_consistency",
        "spatial_and_scale_consistency",
        "prompt_and_asset_hash_integrity",
    ],
}

_VISUAL_STAGE_PROFILES = {
    "generation": ("ArtifactProducer", "artifact_producer"),
    "producer_self_check": ("ArtifactProducer", "artifact_producer"),
    "observer": ("Observer", "observer"),
    "reviewer": ("Reviewer", "visual_reviewer"),
    "verifier": ("Verifier", "verifier"),
}

_MALE_NAIL_DETAIL_TERMS = (
    "指甲",
    "趾甲",
    "美甲",
    "甲面",
    "甲缘",
    "甲缝",
    "护甲油",
    "甲油",
    "修甲",
    "染甲",
    "manicure",
    "pedicure",
    "nail_",
    "nails",
    "toenail",
    "fingernail",
    "甲床",
    "甲缘",
    "甲面",
    "甲根",
    "甲沟",
    "甲油",
    "甲色",
    "甲型",
    "甲长",
)
_MALE_NAIL_CIRCUMLOCUTION_PATTERNS = (
    re.compile(
        r"(?:十根?指头|十指|手指|脚趾|指头|指尖|趾尖|指端|趾端|手部末端|足部末端)"
        r".{0,40}(?:角质|半透明|硬壳|硬层|硬片|硬质|薄层|覆盖层|甲片)"
        r".{0,40}(?:边缘|表面|剪|修|磨|圆|方|尖|色泽|光泽|颜色|涂层|上色|着色|抛光)"
    ),
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes | str) -> str:
    return hashlib.sha256(
        value.encode("utf-8") if isinstance(value, str) else value
    ).hexdigest()


def _resolve_visual_stage_contracts(agentlab_root: Path) -> dict[str, dict[str, str]]:
    """Resolve visual workers only from the canonical role/tier matrix."""

    profile_path = agentlab_root / "config" / "agent_model_profiles.yml"
    try:
        document = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load visual role authority: {exc}") from exc
    mode_id = str(document.get("default_mode") or "")
    tier_id = str(((document.get("tier_policy") or {}).get("default_tier")) or "")
    tier = (((document.get("modes") or {}).get(mode_id) or {}).get("tiers") or {}).get(
        tier_id
    ) or {}
    resolved: dict[str, dict[str, str]] = {}
    for stage_id, (role, profile_key) in _VISUAL_STAGE_PROFILES.items():
        profile = tier.get(profile_key) or {}
        worker = str(profile.get("cli_agent") or "")
        invocation_contract = str(profile.get("invocation_contract") or "")
        model_key = str(profile.get("default") or "")
        if (
            profile.get("executor_type") != "cli_agent"
            or not worker
            or not invocation_contract
            or not model_key
        ):
            raise ValueError(
                f"visual stage {stage_id} has no complete {mode_id}/{tier_id} profile"
            )
        allowed, reason = check_role_binding(
            agentlab_root,
            worker,
            role,
            invocation_contract,
        )
        if not allowed:
            raise ValueError(
                f"visual stage {stage_id} role binding is invalid: {reason}"
            )
        resolved[stage_id] = {
            "role": role,
            "profile_key": profile_key,
            "mode": mode_id,
            "tier": tier_id,
            "worker": worker,
            "invocation_contract": invocation_contract,
            "model_key": model_key,
        }
    if resolved["generation"]["worker"] != "codex":
        raise ValueError(
            "visual identity generation requires the canonical ArtifactProducer "
            "profile to resolve to Codex"
        )
    return resolved


def resolve_visual_stage_contracts(agentlab_root: Path) -> dict[str, dict[str, str]]:
    """Public read-only resolver for governed visual execution adapters."""

    return _resolve_visual_stage_contracts(agentlab_root)


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value) and all(_nonempty(item) for item in value.values())
    if isinstance(value, list):
        return bool(value) and all(_nonempty(item) for item in value)
    return value is not None


def _render(value: Any) -> str:
    if isinstance(value, Mapping):
        return "；".join(
            f"{key}：{_render(value[key])}" for key in sorted(value, key=str)
        )
    if isinstance(value, list):
        return "、".join(_render(item) for item in value)
    return str(value).strip()


def _require_mapping(value: Any, locator: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{locator} must be a mapping")
    return value


def _require_fields(value: Mapping[str, Any], fields: list[str], locator: str) -> None:
    for field in fields:
        if field not in value or not _nonempty(value[field]):
            raise ValueError(f"{locator}.{field} must be non-empty")


def _reject_male_nail_details(card: Mapping[str, Any], card_id: str) -> None:
    serialized = _render(card).lower()
    present = [term for term in _MALE_NAIL_DETAIL_TERMS if term in serialized]
    if re.search(r"(?<![a-z])nails?(?![a-z])", serialized):
        present.append("nail")
    if any(
        pattern.search(serialized) for pattern in _MALE_NAIL_CIRCUMLOCUTION_PATTERNS
    ):
        present.append("free-form digit material prose")
    if present:
        raise ValueError(
            f"cards.{card_id} male character must not contain nail details: "
            + ", ".join(present)
        )


def _validated_male_hand_profile(value: Any, *, locator: str) -> Mapping[str, str]:
    profile = _require_mapping(value, locator)
    expected_fields = set(_MALE_HAND_PROFILE_OPTIONS)
    _reject_unsupported_fields(
        profile,
        allowed_fields=expected_fields,
        locator=locator,
    )
    _require_fields(profile, sorted(expected_fields), locator)
    normalized: dict[str, str] = {}
    for field, choices in _MALE_HAND_PROFILE_OPTIONS.items():
        selected = str(profile[field] or "")
        if selected not in choices:
            raise ValueError(
                f"{locator}.{field} must use a governed male hand profile value"
            )
        normalized[field] = selected
    return normalized


def _render_male_hand_profile(profile: Mapping[str, Any]) -> str:
    validated = _validated_male_hand_profile(profile, locator="male hands")
    return "；".join(
        _MALE_HAND_PROFILE_OPTIONS[field][validated[field]]
        for field in _MALE_HAND_PROFILE_OPTIONS
    )


def _require_detail_mappings(
    value: Mapping[str, Any],
    contracts: Mapping[str, list[str]],
    locator: str,
) -> None:
    for field, required_fields in contracts.items():
        detail = _require_mapping(value.get(field), f"{locator}.{field}")
        _require_fields(detail, required_fields, f"{locator}.{field}")


def _reject_unsupported_fields(
    value: Mapping[str, Any],
    *,
    allowed_fields: set[str],
    locator: str,
) -> None:
    unsupported = sorted(set(value) - allowed_fields)
    if unsupported:
        raise ValueError(
            f"{locator} contains unsupported fields: {', '.join(unsupported)}"
        )


def _validated_creative_policy(
    value: Any,
    *,
    project: str,
    locator: str,
) -> Mapping[str, Any]:
    creative_policy = _require_mapping(value, locator)
    _require_fields(
        creative_policy,
        ["work_title", "female_modern_nail_art_allowed"],
        locator,
    )
    if not isinstance(creative_policy["female_modern_nail_art_allowed"], bool):
        raise ValueError(f"{locator}.female_modern_nail_art_allowed must be boolean")
    if (
        project == "ShanHeYouJia" or str(creative_policy["work_title"]) == "山河有约"
    ) and creative_policy["female_modern_nail_art_allowed"] is not True:
        raise ValueError("ShanHeYouJia requires modern nail art to remain allowed")
    return creative_policy


def _card_contract(
    *,
    kind: str,
    invariant: Mapping[str, Any],
    card_id: str,
) -> tuple[dict[str, list[str]], str | None]:
    contract = deepcopy(_KIND_CONTRACTS[kind])
    if kind != "character":
        return contract, None
    gender = str(invariant.get("gender") or "").strip().lower()
    if gender not in {"male", "female"}:
        raise ValueError(f"cards.{card_id}.invariant.gender must be male or female")
    if gender == "female":
        contract["required_invariant_fields"].extend(_FEMALE_INVARIANT_FIELDS)
        contract["required_variant_fields"].extend(_FEMALE_VARIANT_FIELDS)
        contract["required_shots"] = [
            shot_id
            for shot_id in contract["required_shots"]
            if shot_id != "hands-detail"
        ]
        contract["required_shots"].extend(_FEMALE_SHOTS)
    return contract, gender


def _identity_lock_prompt(
    card: Mapping[str, Any],
    ordered_fields: list[str],
    *,
    gender: str | None,
    modern_nail_art_allowed: bool,
) -> str:
    invariant = _require_mapping(
        card["invariant"], f"cards.{card['card_id']}.invariant"
    )
    facts = "；".join(
        f"{field}：{_render_male_hand_profile(invariant[field]) if field == 'hands' and gender == 'male' and isinstance(invariant[field], Mapping) else _render(invariant[field])}"
        for field in ordered_fields
    )
    modernization_rule = (
        "除卡片明确记载的女性现代美甲元素外，不得擅自现代化"
        if modern_nail_art_allowed
        else "不得现代化"
    )
    return (
        f"【IDENTITY LOCK {card['card_id']} / {card['display_name']}】{facts}。"
        f"所有图像必须把这些内容视为不可变事实；不得美化替换，{modernization_rule}，"
        "不得左右翻转或随机增删。"
    )


def _compile_legacy_card(card: Mapping[str, Any]) -> dict:
    """Rebuild v1 cards for historical validation; never used for new compilation."""

    _require_fields(
        card, ["card_id", "kind", "display_name", "invariant", "variants"], "card"
    )
    card_id = str(card["card_id"])
    kind = str(card["kind"])
    if kind not in _LEGACY_KIND_CONTRACTS:
        raise ValueError(f"cards.{card_id}.kind unsupported: {kind}")
    contract = _LEGACY_KIND_CONTRACTS[kind]
    invariant = _require_mapping(card["invariant"], f"cards.{card_id}.invariant")
    _require_fields(
        invariant,
        contract["required_invariant_fields"],
        f"cards.{card_id}.invariant",
    )
    variants = card["variants"]
    if not isinstance(variants, list) or not variants:
        raise ValueError(f"cards.{card_id}.variants must be a non-empty list")

    facts = "；".join(
        f"{field}：{_render(invariant[field])}"
        for field in contract["required_invariant_fields"]
    )
    identity_prompt = (
        f"【IDENTITY LOCK {card_id} / {card['display_name']}】{facts}。"
        "所有图像必须把这些内容视为不可变事实；不得美化替换、现代化、左右翻转或随机增删。"
    )
    identity_digest = _sha256(identity_prompt)
    reference_variant = _require_mapping(variants[0], f"cards.{card_id}.variants[0]")
    _require_fields(
        reference_variant,
        ["variant_id", *contract["required_variant_fields"]],
        f"cards.{card_id}.variants[0]",
    )
    reference_variant_text = "；".join(
        f"{key}：{_render(reference_variant[key])}"
        for key in contract["required_variant_fields"]
    )
    reference_views = "；".join(
        f"{shot_id}={_SHOT_DIRECTIONS[shot_id]}"
        for shot_id in contract["required_shots"]
    )
    reference_prompt = (
        f"{identity_prompt}\n"
        f"【REFERENCE VARIANT {reference_variant['variant_id']}】{reference_variant_text}。\n"
        "【IDENTITY REFERENCE SHEET】在一张高分辨率、无文字遮挡的统一定妆设定板中，"
        f"以等比例分格同时呈现：{reference_views}。"
        "所有分格必须是同一身份、同一尺度、同一套锁定服饰与同一材质基准；使用中性背景和"
        "稳定白平衡。此图通过独立验收后才可作为后续组图的图像条件。"
    )
    prompts: list[dict] = []
    seen_variants: set[str] = set()
    for variant_index, raw_variant in enumerate(variants):
        variant = _require_mapping(
            raw_variant, f"cards.{card_id}.variants[{variant_index}]"
        )
        _require_fields(
            variant,
            ["variant_id", *contract["required_variant_fields"]],
            f"cards.{card_id}.variants[{variant_index}]",
        )
        variant_id = str(variant["variant_id"])
        if variant_id in seen_variants:
            raise ValueError(f"cards.{card_id} duplicate variant_id: {variant_id}")
        seen_variants.add(variant_id)
        ordered_variant_fields = [
            *contract["required_variant_fields"],
            *sorted(
                key
                for key in variant
                if key not in {"variant_id", *contract["required_variant_fields"]}
            ),
        ]
        variant_text = "；".join(
            f"{key}：{_render(variant[key])}" for key in ordered_variant_fields
        )
        for shot_id in contract["required_shots"]:
            prompt = (
                f"{identity_prompt}\n"
                f"【VARIANT {variant_id}】{variant_text}。\n"
                f"【SHOT {shot_id}】{_SHOT_DIRECTIONS[shot_id]}。\n"
                "制作高细节、可用于连续叙事的定妆/设定图；保持相同身份、时代工艺、尺度、"
                "色彩基准和材质逻辑。首张获验收后，后续生成必须把已验收身份参考图作为图像条件。"
            )
            prompts.append(
                {
                    "prompt_id": f"{card_id}::{variant_id}::{shot_id}",
                    "variant_id": variant_id,
                    "shot_id": shot_id,
                    "prompt": prompt,
                    "prompt_sha256": _sha256(prompt),
                    "reference_asset_ids": [f"{card_id}::identity-reference"],
                }
            )
    return {
        "card_id": card_id,
        "kind": kind,
        "display_name": str(card["display_name"]),
        "candidate_only": True,
        "invariant": deepcopy(dict(invariant)),
        "variants": deepcopy(variants),
        "required_shot_ids": list(contract["required_shots"]),
        "identity_lock_prompt": identity_prompt,
        "identity_digest": identity_digest,
        "identity_reference_asset_id": f"{card_id}::identity-reference",
        "identity_reference": {
            "asset_id": f"{card_id}::identity-reference",
            "variant_id": str(reference_variant["variant_id"]),
            "prompt": reference_prompt,
            "prompt_sha256": _sha256(reference_prompt),
            "must_be_accepted_before_dependent_generation": True,
        },
        "prompt_set": prompts,
    }


def _compile_card(
    card: Mapping[str, Any],
    *,
    creative_policy: Mapping[str, Any],
    structured_male_hands: bool = True,
) -> dict:
    _require_fields(
        card, ["card_id", "kind", "display_name", "invariant", "variants"], "card"
    )
    card_id = str(card["card_id"])
    kind = str(card["kind"])
    if kind not in _KIND_CONTRACTS:
        raise ValueError(f"cards.{card_id}.kind unsupported: {kind}")
    invariant = _require_mapping(card["invariant"], f"cards.{card_id}.invariant")
    contract, gender = _card_contract(
        kind=kind,
        invariant=invariant,
        card_id=card_id,
    )
    _require_fields(
        invariant,
        contract["required_invariant_fields"],
        f"cards.{card_id}.invariant",
    )
    if kind == "character":
        _require_detail_mappings(
            invariant,
            _CHARACTER_DETAIL_FIELDS,
            f"cards.{card_id}.invariant",
        )
        if gender == "male":
            if structured_male_hands:
                _validated_male_hand_profile(
                    invariant.get("hands"),
                    locator=f"cards.{card_id}.invariant.hands",
                )
            _reject_unsupported_fields(
                invariant,
                allowed_fields=set(contract["required_invariant_fields"]),
                locator=f"cards.{card_id}.invariant",
            )
            _reject_male_nail_details(card, card_id)
        else:
            _require_detail_mappings(
                invariant,
                _FEMALE_DETAIL_FIELDS,
                f"cards.{card_id}.invariant",
            )
    variants = card["variants"]
    if not isinstance(variants, list) or not variants:
        raise ValueError(f"cards.{card_id}.variants must be a non-empty list")

    modern_nail_art_allowed = (
        gender == "female"
        and creative_policy.get("female_modern_nail_art_allowed") is True
    )
    identity_prompt = _identity_lock_prompt(
        card,
        contract["required_invariant_fields"],
        gender=gender,
        modern_nail_art_allowed=modern_nail_art_allowed,
    )
    if gender == "female":
        if modern_nail_art_allowed:
            work_title = str(creative_policy["work_title"])
            identity_prompt += (
                f"现代美甲元素为《{work_title}》的合法视觉设定；可使用法式、渐变、猫眼、"
                "果冻、镜面、极光与玉石晕染等语言，但每个变体的甲长、甲型、底色、"
                "强调色、质感、图案、饰件与磨损必须按卡片精确锁定。"
            )
    identity_digest = _sha256(identity_prompt)
    reference_variant = _require_mapping(variants[0], f"cards.{card_id}.variants[0]")
    _require_fields(
        reference_variant,
        ["variant_id", *contract["required_variant_fields"]],
        f"cards.{card_id}.variants[0]",
    )
    reference_variant_text = "；".join(
        f"{key}：{_render(reference_variant[key])}"
        for key in contract["required_variant_fields"]
    )
    reference_views = "；".join(
        f"{shot_id}={_SHOT_DIRECTIONS[shot_id]}"
        for shot_id in contract["required_shots"]
    )
    reference_prompt = (
        f"{identity_prompt}\n"
        f"【REFERENCE VARIANT {reference_variant['variant_id']}】{reference_variant_text}。\n"
        "【IDENTITY REFERENCE SHEET】在一张高分辨率、无文字遮挡的统一定妆设定板中，"
        f"以等比例分格同时呈现：{reference_views}。"
        "所有分格必须是同一身份、同一尺度、同一套锁定服饰与同一材质基准；使用中性背景和"
        "稳定白平衡。此图通过独立验收后才可作为后续组图的图像条件。"
    )
    prompts: list[dict] = []
    seen_variants: set[str] = set()
    for variant_index, raw_variant in enumerate(variants):
        variant = _require_mapping(
            raw_variant, f"cards.{card_id}.variants[{variant_index}]"
        )
        _require_fields(
            variant,
            ["variant_id", *contract["required_variant_fields"]],
            f"cards.{card_id}.variants[{variant_index}]",
        )
        if kind == "character":
            _require_detail_mappings(
                variant,
                _CHARACTER_VARIANT_HAIR_FIELDS,
                f"cards.{card_id}.variants[{variant_index}]",
            )
            if gender == "female":
                _require_detail_mappings(
                    variant,
                    _FEMALE_VARIANT_DETAIL_FIELDS,
                    f"cards.{card_id}.variants[{variant_index}]",
                )
            else:
                _reject_unsupported_fields(
                    variant,
                    allowed_fields={
                        "variant_id",
                        *contract["required_variant_fields"],
                    },
                    locator=f"cards.{card_id}.variants[{variant_index}]",
                )
        variant_id = str(variant["variant_id"])
        if variant_id in seen_variants:
            raise ValueError(f"cards.{card_id} duplicate variant_id: {variant_id}")
        seen_variants.add(variant_id)
        ordered_variant_fields = [
            *contract["required_variant_fields"],
            *sorted(
                key
                for key in variant
                if key not in {"variant_id", *contract["required_variant_fields"]}
            ),
        ]
        variant_text = "；".join(
            f"{key}：{_render(variant[key])}" for key in ordered_variant_fields
        )
        for shot_id in contract["required_shots"]:
            prompt = (
                f"{identity_prompt}\n"
                f"【VARIANT {variant_id}】{variant_text}。\n"
                f"【SHOT {shot_id}】{_SHOT_DIRECTIONS[shot_id]}。\n"
                "制作高细节、可用于连续叙事的定妆/设定图；保持相同身份、时代工艺、尺度、"
                "色彩基准和材质逻辑。首张获验收后，后续生成必须把已验收身份参考图作为图像条件。"
            )
            prompts.append(
                {
                    "prompt_id": f"{card_id}::{variant_id}::{shot_id}",
                    "variant_id": variant_id,
                    "shot_id": shot_id,
                    "prompt": prompt,
                    "prompt_sha256": _sha256(prompt),
                    "reference_asset_ids": [f"{card_id}::identity-reference"],
                }
            )

    compiled = {
        "card_id": card_id,
        "kind": kind,
        "display_name": str(card["display_name"]),
        "candidate_only": True,
        "invariant": deepcopy(dict(invariant)),
        "variants": deepcopy(variants),
        "required_shot_ids": list(contract["required_shots"]),
        "identity_lock_prompt": identity_prompt,
        "identity_digest": identity_digest,
        "identity_reference_asset_id": f"{card_id}::identity-reference",
        "identity_reference": {
            "asset_id": f"{card_id}::identity-reference",
            "variant_id": str(reference_variant["variant_id"]),
            "prompt": reference_prompt,
            "prompt_sha256": _sha256(reference_prompt),
            "must_be_accepted_before_dependent_generation": True,
        },
        "prompt_set": prompts,
    }
    if gender == "male" and structured_male_hands:
        compiled["character_detail_contract"] = deepcopy(
            _MALE_CHARACTER_DETAIL_CONTRACT
        )
    elif gender == "female":
        character_detail_contract = deepcopy(_FEMALE_CHARACTER_DETAIL_CONTRACT)
        character_detail_contract["modern_nail_art_allowed"] = modern_nail_art_allowed
        compiled["character_detail_contract"] = character_detail_contract
    return compiled


def compile_visual_detail_card_pack(spec: Mapping[str, Any]) -> dict:
    """Compile one structured candidate spec into deterministic prompt cards."""

    document = deepcopy(dict(_require_mapping(spec, "spec")))
    document.setdefault("source_refs", [])
    _reject_unsupported_fields(
        document,
        allowed_fields={
            "schema_version",
            "project",
            "task_id",
            "creative_policy",
            "character_roster",
            "cards",
            "source_refs",
        },
        locator="spec",
    )
    _require_fields(
        document,
        [
            "schema_version",
            "project",
            "task_id",
            "creative_policy",
            "character_roster",
            "cards",
        ],
        "spec",
    )
    if document["schema_version"] != SPEC_SCHEMA:
        raise ValueError(f"unsupported spec schema: {document['schema_version']}")
    cards = document["cards"]
    if not isinstance(cards, list) or not cards:
        raise ValueError("spec.cards must be a non-empty list")
    creative_policy = _validated_creative_policy(
        document["creative_policy"],
        project=str(document["project"]),
        locator="spec.creative_policy",
    )
    character_roster = document["character_roster"]
    if not isinstance(character_roster, list) or not character_roster:
        raise ValueError("spec.character_roster must be non-empty")
    normalized_roster = [str(card_id).strip() for card_id in character_roster]
    if any(not card_id for card_id in normalized_roster):
        raise ValueError("spec.character_roster entries must be non-empty")
    if len(normalized_roster) != len(set(normalized_roster)):
        raise ValueError("spec.character_roster entries must be unique")
    compiled_cards = [
        _compile_card(
            _require_mapping(card, "spec.cards[]"),
            creative_policy=creative_policy,
        )
        for card in cards
    ]
    card_ids = [card["card_id"] for card in compiled_cards]
    if len(card_ids) != len(set(card_ids)):
        raise ValueError("spec.cards card_id values must be unique")
    character_card_ids = [
        card["card_id"] for card in compiled_cards if card["kind"] == "character"
    ]
    if normalized_roster != character_card_ids:
        raise ValueError(
            "spec.character_roster must exactly match character card ids in order"
        )
    source_refs = document.get("source_refs", [])
    if not isinstance(source_refs, list):
        raise ValueError("spec.source_refs must be a list")

    pack = {
        "schema_version": PACK_SCHEMA,
        "project": str(document["project"]),
        "task_id": str(document["task_id"]),
        "candidate_only": True,
        "promotion_state": AWAITING_ACCEPTANCE,
        "source_spec_sha256": _sha256(_canonical_bytes(document)),
        "source_refs": deepcopy(source_refs),
        "creative_policy": deepcopy(dict(creative_policy)),
        "character_roster": normalized_roster,
        "generation_contract": deepcopy(_GENERATION_CONTRACT),
        "review_contract": deepcopy(_REVIEW_CONTRACT),
        "cards": compiled_cards,
    }
    pack["pack_sha256"] = _pack_sha256(pack)
    return pack


def _pack_sha256(pack: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(pack))
    payload.pop("pack_sha256", None)
    return _sha256(_canonical_bytes(payload))


def _source_document_from_pack(
    pack: Mapping[str, Any],
    *,
    spec_schema: str,
) -> dict[str, Any]:
    cards = pack.get("cards")
    if not isinstance(cards, list):
        raise ValueError("pack.cards must be a list")
    return {
        "schema_version": spec_schema,
        "project": pack.get("project"),
        "task_id": pack.get("task_id"),
        "creative_policy": deepcopy(pack.get("creative_policy")),
        "character_roster": deepcopy(pack.get("character_roster")),
        "cards": [
            {
                "card_id": card.get("card_id"),
                "kind": card.get("kind"),
                "display_name": card.get("display_name"),
                "invariant": deepcopy(card.get("invariant")),
                "variants": deepcopy(card.get("variants")),
            }
            for card in cards
            if isinstance(card, Mapping)
        ],
        "source_refs": deepcopy(pack.get("source_refs")),
    }


def require_current_visual_detail_card_pack(
    pack: Mapping[str, Any],
    *,
    operation: str,
) -> None:
    """Keep historical v1 validation strictly outside production execution."""

    if pack.get("schema_version") != PACK_SCHEMA:
        raise ValueError(f"{operation} requires a current {PACK_SCHEMA} pack")
    validation = validate_visual_detail_card_pack(pack)
    if validation["status"] != "pass":
        raise ValueError(f"{operation} requires a valid current visual card pack")


def validate_visual_detail_card_pack(pack: Mapping[str, Any]) -> dict:
    """Validate hashes, ownership, shot coverage, and identity reuse."""

    issues: list[str] = []
    if not isinstance(pack, Mapping):
        return {"status": "blocked", "issues": ["pack must be a mapping"]}
    schema_version = pack.get("schema_version")
    legacy_v1_mode = schema_version == LEGACY_PACK_SCHEMA
    legacy_v2_mode = schema_version == LEGACY_V2_PACK_SCHEMA
    if schema_version not in {PACK_SCHEMA, LEGACY_PACK_SCHEMA, LEGACY_V2_PACK_SCHEMA}:
        issues.append("unsupported pack schema")
    if pack.get("candidate_only") is not True:
        issues.append("pack must remain candidate_only")
    if pack.get("promotion_state") != AWAITING_ACCEPTANCE:
        issues.append(
            "promotion_state must await visual generation and human acceptance"
        )
    if pack.get("generation_contract") != _GENERATION_CONTRACT:
        issues.append("generation_contract must bind image generation to Codex handoff")
    if pack.get("review_contract") != _REVIEW_CONTRACT:
        issues.append("review_contract does not match the Codex/Agy/Hermes boundary")
    creative_policy: Mapping[str, Any] = {}
    if not legacy_v1_mode:
        try:
            creative_policy = _validated_creative_policy(
                pack.get("creative_policy"),
                project=str(pack.get("project") or ""),
                locator="pack.creative_policy",
            )
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(f"creative_policy is invalid: {exc}")
        source_spec_sha256 = pack.get("source_spec_sha256")
        if not isinstance(source_spec_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", source_spec_sha256
        ):
            issues.append("source_spec_sha256 must be lowercase 64-hex")
        source_refs = pack.get("source_refs")
        if not isinstance(source_refs, list):
            issues.append("source_refs must be a list")
        else:
            seen_source_paths: set[str] = set()
            for ref_index, ref in enumerate(source_refs):
                if not isinstance(ref, Mapping):
                    issues.append(f"source_refs[{ref_index}] must be a mapping")
                    continue
                path = str(ref.get("path") or "")
                digest = ref.get("sha256")
                relative = Path(path)
                if (
                    not path
                    or relative.is_absolute()
                    or ".." in relative.parts
                    or path in seen_source_paths
                ):
                    issues.append(f"source_refs[{ref_index}].path is invalid")
                seen_source_paths.add(path)
                if not isinstance(digest, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", digest
                ):
                    issues.append(
                        f"source_refs[{ref_index}].sha256 must be lowercase 64-hex"
                    )
        try:
            reconstructed_source_sha256 = _sha256(
                _canonical_bytes(
                    _source_document_from_pack(
                        pack,
                        spec_schema=(
                            LEGACY_V2_SPEC_SCHEMA if legacy_v2_mode else SPEC_SCHEMA
                        ),
                    )
                )
            )
        except (TypeError, ValueError) as exc:
            issues.append(f"source spec reconstruction failed: {exc}")
        else:
            if reconstructed_source_sha256 != source_spec_sha256:
                issues.append("source_spec_sha256 does not match the compiled source")
    cards = pack.get("cards")
    if not isinstance(cards, list) or not cards:
        issues.append("cards must be a non-empty list")
        cards = []
    character_roster = pack.get("character_roster")
    if legacy_v1_mode:
        character_roster = []
    elif not isinstance(character_roster, list) or not character_roster:
        issues.append("character_roster must be a non-empty list")
        character_roster = []
    seen: set[str] = set()
    for card_index, card in enumerate(cards):
        if not isinstance(card, Mapping):
            issues.append(f"cards[{card_index}] must be a mapping")
            continue
        card_id = str(card.get("card_id") or f"index-{card_index}")
        if card_id in seen:
            issues.append(f"duplicate card_id: {card_id}")
        seen.add(card_id)
        kind = str(card.get("kind") or "")
        contracts = _LEGACY_KIND_CONTRACTS if legacy_v1_mode else _KIND_CONTRACTS
        contract = contracts.get(kind)
        if contract is None:
            issues.append(f"{card_id}: unsupported kind")
            continue
        try:
            source_card = {
                "card_id": card_id,
                "kind": kind,
                "display_name": card.get("display_name"),
                "invariant": card.get("invariant"),
                "variants": card.get("variants"),
            }
            rebuilt = (
                _compile_legacy_card(source_card)
                if legacy_v1_mode
                else _compile_card(
                    source_card,
                    creative_policy=creative_policy,
                    structured_male_hands=not legacy_v2_mode,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(f"{card_id}: cannot rebuild card: {exc}")
            continue
        lock = str(card.get("identity_lock_prompt") or "")
        if lock != rebuilt["identity_lock_prompt"]:
            issues.append(f"{card_id}: identity_lock_prompt does not match invariant")
        if card.get("identity_digest") != _sha256(lock):
            issues.append(f"{card_id}: identity_digest mismatch")
        required_shots = rebuilt["required_shot_ids"]
        if card.get("required_shot_ids") != required_shots:
            issues.append(f"{card_id}: required_shot_ids mismatch")
        if not legacy_v1_mode and card.get("character_detail_contract") != rebuilt.get(
            "character_detail_contract"
        ):
            issues.append(f"{card_id}: character_detail_contract mismatch")
        if card.get("identity_reference") != rebuilt["identity_reference"]:
            issues.append(f"{card_id}: identity_reference mismatch")
        variants = (
            card.get("variants") if isinstance(card.get("variants"), list) else []
        )
        expected = {
            (str(variant.get("variant_id")), shot)
            for variant in variants
            if isinstance(variant, Mapping)
            for shot in required_shots
        }
        observed: set[tuple[str, str]] = set()
        prompts = card.get("prompt_set")
        if not isinstance(prompts, list):
            issues.append(f"{card_id}: prompt_set must be a list")
            continue
        for prompt_index, item in enumerate(prompts):
            if not isinstance(item, Mapping):
                issues.append(f"{card_id}.prompt_set[{prompt_index}] must be a mapping")
                continue
            prompt = str(item.get("prompt") or "")
            if lock not in prompt:
                issues.append(
                    f"{card_id}.prompt_set[{prompt_index}] missing identity lock"
                )
            if item.get("prompt_sha256") != _sha256(prompt):
                issues.append(
                    f"{card_id}.prompt_set[{prompt_index}] prompt_sha256 mismatch"
                )
            if item.get("reference_asset_ids") != [f"{card_id}::identity-reference"]:
                issues.append(
                    f"{card_id}.prompt_set[{prompt_index}] reference asset mismatch"
                )
            observed.add(
                (str(item.get("variant_id") or ""), str(item.get("shot_id") or ""))
            )
        if observed != expected:
            issues.append(f"{card_id}: prompt shot coverage mismatch")
        if prompts != rebuilt["prompt_set"]:
            issues.append(f"{card_id}: prompt_set does not match variants")
    if not legacy_v1_mode:
        observed_character_ids = [
            str(card.get("card_id"))
            for card in cards
            if isinstance(card, Mapping) and card.get("kind") == "character"
        ]
        if character_roster != observed_character_ids:
            issues.append("character_roster does not exactly match character cards")
    if pack.get("pack_sha256") != _pack_sha256(pack):
        issues.append("pack_sha256 mismatch")
    return {
        "schema_version": "narrative-visual-detail-card-validation/v1",
        "status": "pass" if not issues else "blocked",
        "pack_sha256": pack.get("pack_sha256"),
        "card_count": len(cards),
        "prompt_count": sum(
            len(card.get("prompt_set", [])) + 1
            for card in cards
            if isinstance(card, Mapping) and isinstance(card.get("prompt_set"), list)
        ),
        "issues": issues,
    }


def _safe_identifier(value: str, *, label: str) -> str:
    normalized = str(value or "")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", normalized)
        or ".." in normalized
    ):
        raise ValueError(f"{label} is not a safe runtime identifier")
    return normalized


def _pinned_managed_tool_public_key(agentlab_root: Path) -> Path:
    """Load the external public key that attests Codex-managed image results."""

    config_path = agentlab_root / "config" / "local_private_topology.yml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("Codex managed-tool authority is not configured") from exc
    authority = config.get("codex_managed_tool_authority")
    if not isinstance(authority, Mapping):
        raise ValueError("Codex managed-tool authority is not configured")
    public_key = Path(str(authority.get("public_key_path") or ""))
    expected_sha256 = str(authority.get("public_key_sha256") or "")
    if (
        not str(public_key).strip()
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or public_key.is_symlink()
    ):
        raise ValueError("Codex managed-tool authority is invalid")
    public_key = public_key.resolve(strict=True)
    try:
        public_key.relative_to(agentlab_root.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ValueError("Codex managed-tool public key must be outside AgentLab")
    if not public_key.is_file() or _sha256(public_key.read_bytes()) != expected_sha256:
        raise ValueError("Codex managed-tool public key pin mismatch")
    return public_key


def _reject_symlink_ancestry(path: Path, boundary: Path, *, label: str) -> None:
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise ValueError(f"{label} is outside its boundary") from exc
    cursor = boundary
    if cursor.is_symlink():
        raise ValueError(f"{label} boundary must not be a symlink")
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ValueError(f"{label} ancestry must not contain symlinks")


def _bounded_regular_file(path: Path, boundary: Path, *, label: str) -> Path:
    _reject_symlink_ancestry(path, boundary, label=label)
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    try:
        boundary_resolved = boundary.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} boundary does not exist: {boundary}") from exc
    if not resolved.is_relative_to(boundary_resolved):
        raise ValueError(f"{label} must be inside {boundary}")
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    return resolved


def load_visual_detail_spec(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    source_path: Path,
) -> tuple[dict, list[dict[str, str]]]:
    """Read and verify a project-bounded spec and all of its declared sources."""

    root = agentlab_root.resolve(strict=True)
    selected_project = _safe_identifier(project, label="project")
    selected_task = _safe_identifier(task_id, label="task_id")
    projects_root = root / "projects"
    project_path = projects_root / selected_project
    _reject_symlink_ancestry(project_path, root, label="project")
    project_root = project_path.resolve(strict=True)
    if not project_root.is_relative_to(root):
        raise ValueError("project root escapes AgentLab")
    requested_source = source_path if source_path.is_absolute() else root / source_path
    source = _bounded_regular_file(requested_source, project_root, label="source spec")
    try:
        source_bytes = source.read_bytes()
        spec = yaml.safe_load(source_bytes.decode("utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read visual detail spec: {exc}") from exc
    if not isinstance(spec, Mapping):
        raise ValueError("visual detail spec must be a mapping")
    if spec.get("project") != selected_project or spec.get("task_id") != selected_task:
        raise ValueError("visual detail spec project/task identity mismatch")

    verified_refs: list[dict] = []
    sealed_sources = [
        {
            "path": source.relative_to(root).as_posix(),
            "sha256": _sha256(source_bytes),
        }
    ]
    refs = spec.get("source_refs", [])
    if not isinstance(refs, list):
        raise ValueError("source_refs must be a list")
    for index, ref in enumerate(refs):
        ref_map = _require_mapping(ref, f"source_refs[{index}]")
        _require_fields(ref_map, ["path", "sha256"], f"source_refs[{index}]")
        relative = Path(str(ref_map["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"source_refs[{index}].path must be repository-relative")
        resolved_ref = _bounded_regular_file(
            root / relative,
            project_root,
            label=f"source_refs[{index}]",
        )
        ref_bytes = resolved_ref.read_bytes()
        observed = _sha256(ref_bytes)
        if observed != ref_map["sha256"]:
            raise ValueError(f"source_refs[{index}] sha256 mismatch")
        verified_refs.append({"path": relative.as_posix(), "sha256": observed})
        sealed_sources.append(
            {
                "path": resolved_ref.relative_to(root).as_posix(),
                "sha256": observed,
            }
        )

    normalized_spec = deepcopy(dict(spec))
    normalized_spec["source_refs"] = verified_refs
    return normalized_spec, sealed_sources


def visual_reference_task_id(pack: Mapping[str, Any], card_id: str) -> str:
    identity = "|".join(
        (
            str(pack.get("project") or ""),
            str(pack.get("task_id") or ""),
            str(card_id or ""),
        )
    )
    return f"visual-reference-{_sha256(identity)[:32]}"


def _validate_pack_runtime_provenance(
    agentlab_root: Path,
    pack: Mapping[str, Any],
    pack_path: Path,
) -> dict[str, str]:
    """Bind one generation batch to the selected visual Task ArtifactVersion."""

    require_current_visual_detail_card_pack(pack, operation="visual production")
    root = agentlab_root.resolve(strict=True)
    project = _safe_identifier(str(pack.get("project") or ""), label="project")
    task_id = _safe_identifier(str(pack.get("task_id") or ""), label="task_id")
    project_path = root / "projects" / project
    _reject_symlink_ancestry(project_path, root, label="project")
    project_root = project_path.resolve(strict=True)
    requested = pack_path if pack_path.is_absolute() else root / pack_path
    resolved_pack = _bounded_regular_file(
        requested,
        project_root,
        label="visual detail card pack",
    )
    pack_bytes = resolved_pack.read_bytes()
    try:
        observed_pack = yaml.safe_load(pack_bytes.decode("utf-8")) or {}
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(
            "visual detail card pack ArtifactVersion is unreadable"
        ) from exc
    if observed_pack != pack:
        raise ValueError("visual detail card pack mapping does not match its file")
    digest = _sha256(pack_bytes)
    runtime = TaskRuntime(root, project=project)
    try:
        projection = runtime.load_task(task_id)
    except (EntityNotFound, LedgerIntegrityError) as exc:
        raise ValueError("visual detail card Task is unavailable") from exc
    matches = [
        (version_id, artifact)
        for version_id, artifact in projection["artifacts"].items()
        if artifact.get("artifact_id") == "visual_detail_card_pack"
        and artifact.get("disposition", "eligible") == "eligible"
        and artifact.get("sha256") == digest
        and (runtime._task_dir(task_id) / str(artifact.get("path") or "")).resolve(
            strict=True
        )
        == resolved_pack
    ]
    if (
        projection["task"].get("protocol_ref") != "narrative.visual.v1"
        or len(matches) != 1
    ):
        raise ValueError(
            "generation requires one eligible narrative.visual.v1 pack ArtifactVersion"
        )
    version_id, artifact = matches[0]
    gate = projection["protocol_gates"].get("visual_detail_cards_hash_verified")
    if (
        not isinstance(gate, Mapping)
        or gate.get("status") != "pass"
        or version_id not in (gate.get("subject_version_ids") or [])
    ):
        raise ValueError("visual detail card pack has no exact deterministic hash gate")
    facts = projection["task"].get("input_profile") or {}
    raw_source = Path(str(facts.get("source_visual_detail_spec") or ""))
    source_candidates = (
        [raw_source]
        if raw_source.is_absolute()
        else [root / raw_source, project_root / raw_source]
    )
    declared_source = next(
        (candidate for candidate in source_candidates if candidate.exists()),
        None,
    )
    if declared_source is None:
        raise ValueError("visual detail source spec is unavailable")
    try:
        source_spec, sealed_sources = load_visual_detail_spec(
            root,
            project=project,
            task_id=task_id,
            source_path=declared_source,
        )
        expected_pack = compile_visual_detail_card_pack(source_spec)
    except (OSError, ValueError) as exc:
        raise ValueError("visual detail source spec is invalid") from exc
    if (
        not sealed_sources
        or sealed_sources[0].get("sha256")
        != facts.get("source_visual_detail_spec_sha256")
        or expected_pack != pack
    ):
        raise ValueError("visual detail pack does not match its Task source spec")
    blueprint_task_id = str(facts.get("source_blueprint_task_id") or "")
    blueprint_version_id = str(facts.get("source_blueprint_artifact_version_id") or "")
    try:
        blueprint = runtime.load_task(blueprint_task_id)
    except (EntityNotFound, LedgerIntegrityError) as exc:
        raise ValueError("source blueprint Task is unavailable") from exc
    blueprint_artifact = blueprint["artifacts"].get(blueprint_version_id)
    if (
        blueprint["task"].get("protocol_ref") != "narrative.blueprint.v1"
        or not isinstance(blueprint_artifact, Mapping)
        or blueprint_artifact.get("artifact_id") != "story_blueprint"
        or blueprint_artifact.get("disposition", "eligible") != "eligible"
        or blueprint_artifact.get("sha256")
        != facts.get("source_blueprint_artifact_sha256")
    ):
        raise ValueError("source blueprint ArtifactVersion is not current")
    blueprint_path = runtime._task_dir(blueprint_task_id) / str(
        blueprint_artifact.get("path") or ""
    )
    if _sha256(blueprint_path.read_bytes()) != blueprint_artifact.get("sha256"):
        raise ValueError("source blueprint ArtifactVersion hash drifted")
    return {
        "visual_task_id": task_id,
        "visual_pack_version_id": version_id,
        "visual_pack_sha256": str(artifact["sha256"]),
        "visual_hash_gate_evidence_sha256": str(gate.get("evidence_sha256") or ""),
        "source_blueprint_task_id": blueprint_task_id,
        "source_blueprint_artifact_version_id": blueprint_version_id,
        "source_blueprint_artifact_sha256": str(blueprint_artifact["sha256"]),
    }


def validate_visual_pack_runtime_provenance(
    agentlab_root: Path,
    pack: Mapping[str, Any],
    pack_path: Path,
) -> dict[str, str]:
    """Public fail-closed provenance gate for visual execution adapters."""

    return _validate_pack_runtime_provenance(agentlab_root, pack, pack_path)


def validate_managed_imagegen_attestation(
    agentlab_root: Path,
    attestation: Mapping[str, Any],
    *,
    expected_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify one externally signed managed-image result exactly."""

    signed_payload = (
        attestation.get("signed_payload") if isinstance(attestation, Mapping) else None
    )
    if (
        not isinstance(attestation, Mapping)
        or attestation.get("status") != "attested"
        or signed_payload != expected_payload
        or not str(attestation.get("signature_path") or "").strip()
    ):
        raise ValueError("managed imagegen attestation does not match the result")
    authority = _verify_external_signature(
        agentlab_root
        / "projects"
        / _safe_identifier(str(expected_payload.get("project") or ""), label="project"),
        payload=dict(expected_payload),
        signature_path=Path(str(attestation["signature_path"])),
        public_key_path=_pinned_managed_tool_public_key(agentlab_root),
    )
    return {
        "status": "pass",
        "signed_payload": deepcopy(dict(expected_payload)),
        "signature_authority": authority,
    }


def _visual_stage_output_issues(
    output: Any,
    *,
    stage_id: str,
    role: str,
    asset_sha256: str,
) -> list[str]:
    """Validate the semantic pass contract for one independent visual review."""

    if not isinstance(output, Mapping):
        return [f"identity reference {stage_id} review output must be a mapping"]
    issues: list[str] = []
    if output.get("schema_version") != "narrative-visual-stage-review/v1":
        issues.append(f"identity reference {stage_id} review schema is invalid")
    if (
        output.get("stage_id") != stage_id
        or output.get("role") != role
        or output.get("asset_sha256") != asset_sha256
    ):
        issues.append(f"identity reference {stage_id} review subject is mismatched")
    if output.get("status") != "complete" or output.get("verdict") != "pass":
        issues.append(f"identity reference {stage_id} review did not pass")
    if output.get("blocking_issues") != []:
        issues.append(f"identity reference {stage_id} review has blocking issues")
    dimensions = output.get("dimensions")
    required_dimensions = _REVIEW_CONTRACT["required_dimensions"]
    if not isinstance(dimensions, Mapping):
        issues.append(f"identity reference {stage_id} review dimensions are missing")
    else:
        for dimension in required_dimensions:
            finding = dimensions.get(dimension)
            if (
                not isinstance(finding, Mapping)
                or finding.get("status") != "pass"
                or not isinstance(finding.get("evidence"), list)
                or not finding["evidence"]
                or not all(_nonempty(item) for item in finding["evidence"])
            ):
                issues.append(
                    f"identity reference {stage_id} review dimension {dimension} did not pass"
                )
    return issues


def validate_identity_reference_acceptance(
    agentlab_root: Path,
    pack: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict:
    """Verify one accepted identity image before it may condition later shots."""

    issues: list[str] = []
    if pack.get("schema_version") != PACK_SCHEMA:
        issues.append(
            f"identity reference acceptance requires a current {PACK_SCHEMA} pack"
        )
    pack_validation = validate_visual_detail_card_pack(pack)
    if pack_validation["status"] != "pass":
        issues.append("visual detail card pack is invalid")
    if not isinstance(receipt, Mapping):
        return {"status": "blocked", "issues": ["acceptance receipt must be a mapping"]}
    card_id = str(receipt.get("card_id") or "")
    card = next(
        (
            item
            for item in pack.get("cards", [])
            if isinstance(item, Mapping) and item.get("card_id") == card_id
        ),
        None,
    )
    if (
        receipt.get("schema_version")
        != "narrative-visual-identity-reference-acceptance/v1"
    ):
        issues.append("unsupported identity reference acceptance schema")
    if receipt.get("status") != "accepted":
        issues.append("identity reference receipt is not accepted")
    if (
        receipt.get("project") != pack.get("project")
        or receipt.get("task_id") != pack.get("task_id")
        or receipt.get("pack_sha256") != pack.get("pack_sha256")
    ):
        issues.append("identity reference receipt does not bind the exact pack")
    if card is None:
        issues.append("identity reference receipt card is undeclared")

    asset = receipt.get("asset")
    asset_sha256 = ""
    if not isinstance(asset, Mapping) or card is None:
        issues.append("identity reference asset is missing")
    else:
        if asset.get("asset_id") != card.get("identity_reference_asset_id"):
            issues.append("identity reference asset_id mismatch")
        relative = Path(str(asset.get("path") or ""))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            issues.append("identity reference asset path must be repository-relative")
        else:
            try:
                root = agentlab_root.resolve(strict=True)
                project = _safe_identifier(
                    str(pack.get("project") or ""), label="project"
                )
                project_path = root / "projects" / project
                _reject_symlink_ancestry(project_path, root, label="project")
                project_root = project_path.resolve(strict=True)
                asset_path = _bounded_regular_file(
                    root / relative,
                    project_root,
                    label="identity reference asset",
                )
                asset_sha256 = _sha256(asset_path.read_bytes())
                if asset.get("sha256") != asset_sha256:
                    issues.append("identity reference asset sha256 mismatch")
            except (OSError, ValueError) as exc:
                issues.append(f"identity reference asset is unavailable: {exc}")

    runtime_evidence = receipt.get("runtime_evidence")
    runtime_evidence_sha256 = ""
    if not isinstance(runtime_evidence, Mapping):
        issues.append("identity reference Runtime-v2 evidence is missing")
    else:
        runtime_evidence_sha256 = _sha256(_canonical_bytes(runtime_evidence))
        evidence_task_id = str(runtime_evidence.get("task_id") or "")
        version_id = str(runtime_evidence.get("artifact_version_id") or "")
        stages = runtime_evidence.get("stages")
        expected_reference_task_id = visual_reference_task_id(pack, card_id)
        if evidence_task_id != expected_reference_task_id:
            issues.append("identity reference Task is not the canonical card selector")
        try:
            runtime = TaskRuntime(
                agentlab_root,
                project=str(pack.get("project") or ""),
            )
            projection = runtime.load_task(evidence_task_id)
        except (EntityNotFound, LedgerIntegrityError, ValueError):
            projection = None
            issues.append("identity reference Runtime-v2 Task is unavailable")
        artifact = (
            projection["artifacts"].get(version_id)
            if isinstance(projection, Mapping)
            else None
        )
        immutable_asset: Path | None = None
        if (
            not isinstance(artifact, Mapping)
            or artifact.get("artifact_id") != "visual_identity_reference"
            or artifact.get("disposition", "eligible") != "eligible"
            or artifact.get("sha256") != asset_sha256
            or not isinstance(asset, Mapping)
            or not isinstance(projection, Mapping)
            or projection.get("selected_artifact_version") != version_id
        ):
            issues.append("identity reference ArtifactVersion is missing or mismatched")
        else:
            reference_facts = projection["task"].get("input_profile") or {}
            if (
                projection["task"].get("protocol_ref")
                != "narrative.visual.reference.v1"
                or not isinstance(projection["task"].get("compiled_protocol"), Mapping)
                or reference_facts.get("source_visual_task_id") != pack.get("task_id")
                or reference_facts.get("source_visual_pack_sha256")
                != pack.get("pack_sha256")
                or not _nonempty(reference_facts.get("source_visual_pack_version_id"))
                or reference_facts.get("card_id") != card_id
                or reference_facts.get("identity_reference_prompt_sha256")
                != (card.get("identity_reference") or {}).get("prompt_sha256")
            ):
                issues.append(
                    "identity reference Task facts do not bind the exact card"
                )
            try:
                visual_projection = runtime.load_task(str(pack.get("task_id") or ""))
                visual_version_id = str(
                    reference_facts.get("source_visual_pack_version_id") or ""
                )
                visual_artifact = visual_projection["artifacts"].get(visual_version_id)
                visual_pack_path = runtime._task_dir(
                    str(pack.get("task_id") or "")
                ) / str((visual_artifact or {}).get("path") or "")
                visual_pack_bytes = visual_pack_path.read_bytes()
                visual_pack_mapping = (
                    yaml.safe_load(visual_pack_bytes.decode("utf-8")) or {}
                )
                visual_gate = visual_projection["protocol_gates"].get(
                    "visual_detail_cards_hash_verified"
                )
                if (
                    visual_projection["task"].get("protocol_ref")
                    != "narrative.visual.v1"
                    or not isinstance(visual_artifact, Mapping)
                    or visual_artifact.get("artifact_id") != "visual_detail_card_pack"
                    or visual_artifact.get("disposition", "eligible") != "eligible"
                    or visual_artifact.get("sha256") != _sha256(visual_pack_bytes)
                    or visual_pack_mapping != pack
                    or not isinstance(visual_gate, Mapping)
                    or visual_gate.get("status") != "pass"
                    or visual_version_id
                    not in (visual_gate.get("subject_version_ids") or [])
                ):
                    issues.append(
                        "identity reference Task source visual pack is not current"
                    )
            except (
                EntityNotFound,
                LedgerIntegrityError,
                OSError,
                UnicodeError,
                ValueError,
                yaml.YAMLError,
            ):
                issues.append(
                    "identity reference Task source visual pack is unavailable"
                )
            immutable_asset = runtime._task_dir(evidence_task_id) / str(
                artifact.get("path") or ""
            )
            if not immutable_asset.is_file() or immutable_asset.resolve(
                strict=True
            ) != (
                agentlab_root.resolve(strict=True) / str(asset.get("path") or "")
            ).resolve(strict=True):
                issues.append(
                    "identity reference asset is not the Runtime-v2 ArtifactVersion"
                )

        stage_sessions: dict[str, str] = {}
        stage_backends: dict[str, str] = {}
        try:
            expected_stages = _resolve_visual_stage_contracts(agentlab_root)
        except ValueError as exc:
            expected_stages = {}
            issues.append(f"visual role authority is invalid: {exc}")
        if not isinstance(stages, Mapping) or not isinstance(projection, Mapping):
            issues.append("identity reference Runtime-v2 stages are missing")
        else:
            for stage_id, stage_contract in expected_stages.items():
                expected_role = str(stage_contract["role"])
                expected_worker = str(stage_contract["worker"])
                expected_contract = str(stage_contract["invocation_contract"])
                stage = stages.get(stage_id)
                attempt_id = (
                    str(stage.get("attempt_id") or "")
                    if isinstance(stage, Mapping)
                    else ""
                )
                attempt = projection["attempts"].get(attempt_id)
                contract = (
                    attempt.get("execution_contract")
                    if isinstance(attempt, Mapping)
                    else None
                )
                outcome = (
                    attempt.get("outcome") if isinstance(attempt, Mapping) else None
                )
                if (
                    not isinstance(stage, Mapping)
                    or not isinstance(attempt, Mapping)
                    or attempt.get("status") != "succeeded"
                    or attempt.get("worker") != expected_worker
                    or not isinstance(contract, Mapping)
                    or contract.get("role") != expected_role
                    or contract.get("invocation_contract") != expected_contract
                    or not isinstance(outcome, Mapping)
                    or stage.get("attempt_receipt_sha256")
                    != outcome.get("receipt_sha256")
                ):
                    issues.append(f"identity reference {stage_id} Attempt is invalid")
                    continue
                try:
                    runtime.verify_attempt_execution_receipt(
                        evidence_task_id,
                        attempt_id,
                    )
                    attempt_receipt_path = runtime._task_dir(evidence_task_id) / str(
                        outcome.get("receipt_path") or ""
                    )
                    attempt_receipt = (
                        yaml.safe_load(attempt_receipt_path.read_text(encoding="utf-8"))
                        or {}
                    )
                except (
                    OSError,
                    UnicodeError,
                    ValueError,
                    InvalidTransition,
                    LedgerIntegrityError,
                    yaml.YAMLError,
                ):
                    issues.append(f"identity reference {stage_id} receipt is invalid")
                    continue
                if stage_id == "generation":
                    if (
                        not isinstance(artifact, Mapping)
                        or artifact.get("producer_attempt_id") != attempt_id
                    ):
                        issues.append(
                            "identity reference generation Attempt did not produce the artifact"
                        )
                else:
                    expected_source = (
                        {
                            "path": immutable_asset.relative_to(
                                agentlab_root
                            ).as_posix(),
                            "sha256": asset_sha256,
                        }
                        if isinstance(immutable_asset, Path)
                        else None
                    )
                    if expected_source is None or expected_source not in (
                        attempt_receipt.get("sealed_sources") or []
                    ):
                        issues.append(
                            f"identity reference {stage_id} did not seal the exact artifact"
                        )
                    try:
                        output_path = runtime._task_dir(evidence_task_id) / str(
                            attempt_receipt.get("output_path") or ""
                        )
                        output_bytes = output_path.read_bytes()
                        if _sha256(output_bytes) != attempt_receipt.get(
                            "output_sha256"
                        ):
                            raise ValueError("review output hash mismatch")
                        review_output = (
                            yaml.safe_load(output_bytes.decode("utf-8")) or {}
                        )
                    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                        issues.append(
                            f"identity reference {stage_id} review output is invalid"
                        )
                    else:
                        issues.extend(
                            _visual_stage_output_issues(
                                review_output,
                                stage_id=stage_id,
                                role=expected_role,
                                asset_sha256=asset_sha256,
                            )
                        )
                model_execution = attempt_receipt.get("model_execution")
                if not isinstance(model_execution, Mapping):
                    issues.append(
                        f"identity reference {stage_id} model evidence is missing"
                    )
                    continue
                model_path = runtime._task_dir(evidence_task_id) / str(
                    model_execution.get("path") or ""
                )
                try:
                    model_bytes = model_path.read_bytes()
                    model_receipt = yaml.safe_load(model_bytes.decode("utf-8")) or {}
                except (OSError, UnicodeError, yaml.YAMLError):
                    issues.append(
                        f"identity reference {stage_id} model receipt is unavailable"
                    )
                    continue
                if (
                    _sha256(model_bytes) != model_execution.get("sha256")
                    or stage.get("model_receipt_sha256")
                    != model_execution.get("sha256")
                    or model_receipt.get("status") != "pass"
                    or model_receipt.get("worker") != expected_worker
                    or model_receipt.get("role") != expected_role
                    or model_receipt.get("invocation_contract") != expected_contract
                    or (
                        stage_id != "generation"
                        and model_receipt.get("selected_model_key")
                        != stage_contract["model_key"]
                    )
                    or model_receipt.get("provider_model_binding_verified") is not True
                    or model_receipt.get("provider_process_started") is not True
                    or model_receipt.get("fallback_detected") is not False
                ):
                    issues.append(
                        f"identity reference {stage_id} model receipt is invalid"
                    )
                    continue
                if stage_id == "generation" and (
                    model_receipt.get("execution_surface") != "codex_managed_imagegen"
                    or model_receipt.get("managed_tool")
                    != _GENERATION_CONTRACT["managed_tool"]
                    or model_receipt.get("generated_asset_sha256") != asset_sha256
                ):
                    issues.append(
                        "identity reference generation did not bind the Codex imagegen output"
                    )
                    continue
                if stage_id == "generation":
                    attestation = model_receipt.get("managed_tool_attestation")
                    signed_payload = (
                        attestation.get("signed_payload")
                        if isinstance(attestation, Mapping)
                        else None
                    )
                    tool_result_id = (
                        str(signed_payload.get("tool_result_id") or "")
                        if isinstance(signed_payload, Mapping)
                        else ""
                    )
                    expected_attestation_payload = {
                        "schema_version": "narrative-visual-managed-imagegen-attestation-payload/v1",
                        "action": "attest_codex_managed_imagegen_result",
                        "tool": _GENERATION_CONTRACT["managed_tool"],
                        "project": pack.get("project"),
                        "task_id": evidence_task_id,
                        "attempt_id": attempt_id,
                        "artifact_version_id": version_id,
                        "card_id": card_id,
                        "prompt_sha256": (
                            (card.get("identity_reference") or {}).get("prompt_sha256")
                            if card is not None
                            else None
                        ),
                        "asset_sha256": asset_sha256,
                        "session_id": model_receipt.get("session_id"),
                        "selected_provider": model_receipt.get("selected_provider"),
                        "selected_model_id": model_receipt.get("selected_model_id"),
                        "tool_result_id": tool_result_id,
                    }
                    attestation_valid = (
                        isinstance(attestation, Mapping)
                        and attestation.get("status") == "attested"
                        and bool(tool_result_id)
                        and signed_payload == expected_attestation_payload
                        and bool(str(attestation.get("signature_path") or "").strip())
                    )
                    if attestation_valid:
                        try:
                            _verify_external_signature(
                                agentlab_root
                                / "projects"
                                / str(pack.get("project") or ""),
                                payload=expected_attestation_payload,
                                signature_path=Path(str(attestation["signature_path"])),
                                public_key_path=_pinned_managed_tool_public_key(
                                    agentlab_root
                                ),
                            )
                        except (OSError, ValueError):
                            attestation_valid = False
                    if not attestation_valid:
                        issues.append(
                            "identity reference generation lacks a trusted Codex imagegen attestation"
                        )
                        continue
                session_id = str(model_receipt.get("session_id") or "")
                provider_model = "/".join(
                    (
                        str(model_receipt.get("selected_provider") or ""),
                        str(model_receipt.get("selected_model_id") or ""),
                    )
                )
                if not session_id or provider_model in {"/", ""}:
                    issues.append(
                        f"identity reference {stage_id} session/model is missing"
                    )
                    continue
                stage_sessions[stage_id] = session_id
                stage_backends[stage_id] = provider_model
        if len(stage_sessions) != 5 or len(set(stage_sessions.values())) != 5:
            issues.append("independent visual Attempt sessions are not distinct")
        if (
            stage_backends.get("reviewer")
            and stage_backends.get("verifier")
            and stage_backends["reviewer"] == stage_backends["verifier"]
        ):
            issues.append("Reviewer and Verifier backend/model pairs are not distinct")
        gate_subject_digest = _sha256(
            _canonical_bytes({"visual_identity_reference": asset_sha256})
        )
        required_reference_gates = {
            "managed_imagegen_attested": ("generation", "automated"),
            "independent_visual_acceptance": ("verifier", "independent"),
            "human_identity_reference_acceptance": ("verifier", "human"),
        }
        for gate_id, (stage_id, evidence_kind) in required_reference_gates.items():
            gate = projection["protocol_gates"].get(gate_id)
            stage = stages.get(stage_id) if isinstance(stages, Mapping) else None
            if (
                not isinstance(gate, Mapping)
                or gate.get("status") != "pass"
                or gate.get("evidence_kind") != evidence_kind
                or gate.get("attempt_id")
                != (stage.get("attempt_id") if isinstance(stage, Mapping) else None)
                or gate.get("subject_version_ids") != [version_id]
                or gate.get("evidence_sha256") != gate_subject_digest
            ):
                issues.append(
                    f"identity reference protocol gate {gate_id} is missing or stale"
                )
        if any(
            (projection["work_items"].get(stage_id) or {}).get("status") != "accepted"
            for stage_id in expected_stages
        ):
            issues.append("identity reference protocol WorkItems are not accepted")

    if card is not None and receipt.get("identity_reference_prompt_sha256") != (
        card.get("identity_reference") or {}
    ).get("prompt_sha256"):
        issues.append("identity reference prompt hash mismatch")
    human = receipt.get("human_acceptance")
    expected_human_payload = {
        "schema_version": "narrative-visual-human-acceptance-signature-payload/v1",
        "action": "accept_identity_reference",
        "actor_type": "user",
        "actor_id": str((human or {}).get("actor_id") or ""),
        "approved_at": str((human or {}).get("accepted_at") or ""),
        "project": pack.get("project"),
        "task_id": pack.get("task_id"),
        "pack_sha256": pack.get("pack_sha256"),
        "card_id": card_id,
        "asset_sha256": asset_sha256,
        "identity_reference_prompt_sha256": (
            (card.get("identity_reference") or {}).get("prompt_sha256")
            if card is not None
            else None
        ),
        "runtime_evidence_sha256": runtime_evidence_sha256,
    }
    human_valid = isinstance(human, Mapping) and not any(
        (
            human.get("status") != "accepted",
            not expected_human_payload["actor_id"],
            not expected_human_payload["approved_at"],
            human.get("signed_payload") != expected_human_payload,
            not str(human.get("signature_path") or "").strip(),
        )
    )
    if human_valid:
        try:
            root = agentlab_root.resolve(strict=True)
            project_root = root / "projects" / str(pack.get("project") or "")
            _verify_external_signature(
                project_root,
                payload=expected_human_payload,
                signature_path=Path(str(human["signature_path"])),
                public_key_path=_pinned_public_key(project_root),
            )
        except (OSError, ValueError):
            human_valid = False
    if not human_valid:
        issues.append("human acceptance is not exact and hash-bound")

    return {
        "schema_version": "narrative-visual-identity-reference-validation/v1",
        "status": "pass" if not issues else "blocked",
        "pack_sha256": pack.get("pack_sha256"),
        "card_id": card_id,
        "asset_sha256": asset_sha256 or None,
        "acceptance_receipt_sha256": _sha256(_canonical_bytes(receipt)),
        "issues": issues,
    }


def compile_visual_generation_batch(
    pack: Mapping[str, Any],
    *,
    card_id: str,
    agentlab_root: Path,
    pack_path: Path,
    accepted_reference_receipt_paths: list[Path],
) -> dict:
    """Compile reference-first Codex jobs from concrete acceptance receipts."""

    require_current_visual_detail_card_pack(pack, operation="visual generation")
    pack_provenance = _validate_pack_runtime_provenance(
        agentlab_root,
        pack,
        pack_path,
    )
    generation_profile = _resolve_visual_stage_contracts(agentlab_root)["generation"]
    card = next(
        (item for item in pack["cards"] if item.get("card_id") == card_id),
        None,
    )
    if card is None:
        raise ValueError(f"unknown visual card: {card_id}")

    if not accepted_reference_receipt_paths:
        jobs = [
            {
                "job_id": f"{card_id}::identity-reference",
                "prompt_id": f"{card_id}::identity-reference",
                "prompt": card["identity_reference"]["prompt"],
                "prompt_sha256": card["identity_reference"]["prompt_sha256"],
                "input_images": [],
                "generation_contract": deepcopy(_GENERATION_CONTRACT),
                "resolved_generation_profile": deepcopy(generation_profile),
                "required_post_generation_gate": "human_identity_reference_acceptance",
            }
        ]
        phase = "identity_reference_generation"
    else:
        if len(accepted_reference_receipt_paths) != 1:
            raise ValueError(
                "dependent generation requires exactly one current accepted reference"
            )
        references: list[dict] = []
        receipt_refs: list[dict[str, str]] = []
        root = agentlab_root.resolve(strict=True)
        project = _safe_identifier(str(pack.get("project") or ""), label="project")
        project_path = root / "projects" / project
        _reject_symlink_ancestry(project_path, root, label="project")
        project_root = project_path.resolve(strict=True)
        for receipt_path in accepted_reference_receipt_paths:
            requested = (
                receipt_path if receipt_path.is_absolute() else root / receipt_path
            )
            resolved_receipt = _bounded_regular_file(
                requested,
                project_root,
                label="identity reference acceptance receipt",
            )
            try:
                receipt = (
                    yaml.safe_load(resolved_receipt.read_text(encoding="utf-8")) or {}
                )
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                raise ValueError(
                    f"identity reference acceptance receipt is invalid: {exc}"
                ) from exc
            if not isinstance(receipt, Mapping):
                raise ValueError(
                    "identity reference acceptance receipt must be a mapping"
                )
            reference_validation = validate_identity_reference_acceptance(
                agentlab_root,
                pack,
                receipt,
            )
            if reference_validation["status"] != "pass":
                raise ValueError(
                    "identity reference acceptance is invalid: "
                    + ", ".join(reference_validation["issues"])
                )
            if receipt.get("card_id") != card_id:
                raise ValueError(
                    "identity reference acceptance belongs to another card"
                )
            references.append(deepcopy(dict(receipt["asset"])))
            receipt_refs.append(
                {
                    "path": resolved_receipt.relative_to(root).as_posix(),
                    "sha256": _sha256(resolved_receipt.read_bytes()),
                    "content_sha256": reference_validation["acceptance_receipt_sha256"],
                }
            )
        jobs = [
            {
                "job_id": prompt["prompt_id"],
                "prompt_id": prompt["prompt_id"],
                "prompt": prompt["prompt"],
                "prompt_sha256": prompt["prompt_sha256"],
                "input_images": deepcopy(references),
                "reference_acceptance_receipts": deepcopy(receipt_refs),
                "generation_contract": deepcopy(_GENERATION_CONTRACT),
                "resolved_generation_profile": deepcopy(generation_profile),
                "required_post_generation_gate": "independent_visual_acceptance",
            }
            for prompt in card["prompt_set"]
        ]
        phase = "dependent_shot_generation"

    batch = {
        "schema_version": "narrative-visual-generation-batch/v1",
        "project": pack["project"],
        "task_id": pack["task_id"],
        "pack_sha256": pack["pack_sha256"],
        "card_id": card_id,
        "reference_task_id": visual_reference_task_id(pack, card_id),
        "pack_runtime_provenance": pack_provenance,
        "candidate_only": True,
        "promotion_authorized": False,
        "phase": phase,
        "jobs": jobs,
    }
    batch["batch_sha256"] = _sha256(_canonical_bytes(batch))
    return batch
