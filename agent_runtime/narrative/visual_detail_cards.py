"""Deterministic visual continuity cards for longform narrative production.

The module turns human/model-authored structured facts into immutable prompt sets.
It does not generate images and cannot promote a card or an image into project canon.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from agent_runtime.atomic_io import atomic_write_yaml


SPEC_SCHEMA = "narrative-visual-detail-spec/v1"
PACK_SCHEMA = "narrative-visual-detail-card-pack/v1"
RECEIPT_SCHEMA = "narrative-visual-detail-card-receipt/v1"

_KIND_CONTRACTS: dict[str, dict[str, list[str]]] = {
    "character": {
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

_SHOT_DIRECTIONS = {
    "face-front-neutral": "正面中性表情脸部特写，85mm 人像透视，均匀柔光，完整显示五官比例",
    "face-three-quarter": "同一人物三分之二侧脸特写，保持眼距、鼻形、下颌与发际线",
    "face-profile": "同一人物严格侧面特写，显示额头、鼻梁、唇线、下颌和耳廓轮廓",
    "full-body-front": "全身正面自然站姿，头脚完整，显示真实身高、肩腰腿比例和服装层次",
    "full-body-back": "全身背面自然站姿，头脚完整，显示发型后部、衣物背片和下摆结构",
    "full-body-side": "全身严格侧面站姿，显示胸背厚度、骨盆、腿长和鞋履比例",
    "hands-and-nails-detail": "双手与指甲微距细节，保留手型、惯用手、茧、伤痕和美甲状态",
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
    "worker": "codex",
    "backend": "codex_imagegen_handoff",
    "auto_executable": False,
    "reference_images_required_after_first_accepted_generation": True,
}

_REVIEW_CONTRACT = {
    "observer": {"role": "Observer", "worker": "agy"},
    "reviewer": {"role": "Reviewer", "worker": "agy"},
    "verifier": {"role": "Verifier", "worker": "codex"},
    "independence": {
        "producer_must_not_review": True,
        "distinct_session_ids_required": True,
        "distinct_backend_model_pairs_required": True,
    },
    "required_dimensions": [
        "identity_consistency",
        "wardrobe_and_state_consistency",
        "spatial_and_scale_consistency",
        "prompt_and_asset_hash_integrity",
    ],
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


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


def _identity_lock_prompt(card: Mapping[str, Any], ordered_fields: list[str]) -> str:
    invariant = _require_mapping(card["invariant"], f"cards.{card['card_id']}.invariant")
    facts = "；".join(f"{field}：{_render(invariant[field])}" for field in ordered_fields)
    return (
        f"【IDENTITY LOCK {card['card_id']} / {card['display_name']}】{facts}。"
        "所有图像必须把这些内容视为不可变事实；不得美化替换、现代化、左右翻转或随机增删。"
    )


def _compile_card(card: Mapping[str, Any]) -> dict:
    _require_fields(card, ["card_id", "kind", "display_name", "invariant", "variants"], "card")
    card_id = str(card["card_id"])
    kind = str(card["kind"])
    if kind not in _KIND_CONTRACTS:
        raise ValueError(f"cards.{card_id}.kind unsupported: {kind}")
    contract = _KIND_CONTRACTS[kind]
    invariant = _require_mapping(card["invariant"], f"cards.{card_id}.invariant")
    _require_fields(
        invariant,
        contract["required_invariant_fields"],
        f"cards.{card_id}.invariant",
    )
    variants = card["variants"]
    if not isinstance(variants, list) or not variants:
        raise ValueError(f"cards.{card_id}.variants must be a non-empty list")

    identity_prompt = _identity_lock_prompt(card, contract["required_invariant_fields"])
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
        variant = _require_mapping(raw_variant, f"cards.{card_id}.variants[{variant_index}]")
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


def compile_visual_detail_card_pack(spec: Mapping[str, Any]) -> dict:
    """Compile one structured candidate spec into deterministic prompt cards."""

    document = _require_mapping(spec, "spec")
    _require_fields(document, ["schema_version", "project", "task_id", "cards"], "spec")
    if document["schema_version"] != SPEC_SCHEMA:
        raise ValueError(f"unsupported spec schema: {document['schema_version']}")
    cards = document["cards"]
    if not isinstance(cards, list) or not cards:
        raise ValueError("spec.cards must be a non-empty list")
    compiled_cards = [_compile_card(_require_mapping(card, "spec.cards[]")) for card in cards]
    card_ids = [card["card_id"] for card in compiled_cards]
    if len(card_ids) != len(set(card_ids)):
        raise ValueError("spec.cards card_id values must be unique")
    source_refs = document.get("source_refs", [])
    if not isinstance(source_refs, list):
        raise ValueError("spec.source_refs must be a list")

    pack = {
        "schema_version": PACK_SCHEMA,
        "project": str(document["project"]),
        "task_id": str(document["task_id"]),
        "candidate_only": True,
        "promotion_state": "awaiting_visual_generation_and_human_acceptance",
        "source_spec_sha256": _sha256(_canonical_bytes(document)),
        "source_refs": deepcopy(source_refs),
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


def validate_visual_detail_card_pack(pack: Mapping[str, Any]) -> dict:
    """Validate hashes, ownership, shot coverage, and identity reuse."""

    issues: list[str] = []
    if not isinstance(pack, Mapping):
        return {"status": "blocked", "issues": ["pack must be a mapping"]}
    if pack.get("schema_version") != PACK_SCHEMA:
        issues.append("unsupported pack schema")
    if pack.get("candidate_only") is not True:
        issues.append("pack must remain candidate_only")
    if pack.get("generation_contract") != _GENERATION_CONTRACT:
        issues.append("generation_contract must bind image generation to Codex handoff")
    if pack.get("review_contract") != _REVIEW_CONTRACT:
        issues.append("review_contract does not match the independent Agy/Codex boundary")
    cards = pack.get("cards")
    if not isinstance(cards, list) or not cards:
        issues.append("cards must be a non-empty list")
        cards = []
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
        contract = _KIND_CONTRACTS.get(kind)
        if contract is None:
            issues.append(f"{card_id}: unsupported kind")
            continue
        try:
            rebuilt = _compile_card(
                {
                    "card_id": card_id,
                    "kind": kind,
                    "display_name": card.get("display_name"),
                    "invariant": card.get("invariant"),
                    "variants": card.get("variants"),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(f"{card_id}: cannot rebuild card: {exc}")
            continue
        lock = str(card.get("identity_lock_prompt") or "")
        if lock != rebuilt["identity_lock_prompt"]:
            issues.append(f"{card_id}: identity_lock_prompt does not match invariant")
        if card.get("identity_digest") != _sha256(lock):
            issues.append(f"{card_id}: identity_digest mismatch")
        if card.get("required_shot_ids") != contract["required_shots"]:
            issues.append(f"{card_id}: required_shot_ids mismatch")
        if card.get("identity_reference") != rebuilt["identity_reference"]:
            issues.append(f"{card_id}: identity_reference mismatch")
        variants = card.get("variants") if isinstance(card.get("variants"), list) else []
        expected = {
            (str(variant.get("variant_id")), shot)
            for variant in variants
            if isinstance(variant, Mapping)
            for shot in contract["required_shots"]
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
                issues.append(f"{card_id}.prompt_set[{prompt_index}] missing identity lock")
            if item.get("prompt_sha256") != _sha256(prompt):
                issues.append(f"{card_id}.prompt_set[{prompt_index}] prompt_sha256 mismatch")
            if item.get("reference_asset_ids") != [f"{card_id}::identity-reference"]:
                issues.append(f"{card_id}.prompt_set[{prompt_index}] reference asset mismatch")
            observed.add((str(item.get("variant_id") or ""), str(item.get("shot_id") or "")))
        if observed != expected:
            issues.append(f"{card_id}: prompt shot coverage mismatch")
        if prompts != rebuilt["prompt_set"]:
            issues.append(f"{card_id}: prompt_set does not match variants")
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


def _bounded_regular_file(path: Path, boundary: Path, *, label: str) -> Path:
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


def materialize_visual_detail_card_pack(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    source_path: Path,
) -> dict:
    """Hash-seal a task-local spec into an immutable candidate version."""

    root = agentlab_root.resolve(strict=True)
    project_root = root / "projects" / project
    task_root = project_root / "runtime" / "tasks" / task_id
    inputs_root = task_root / "inputs"
    try:
        source = _bounded_regular_file(source_path, inputs_root, label="source spec")
    except ValueError as exc:
        raise ValueError(f"source spec must be inside exact task inputs: {exc}") from exc
    try:
        spec = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read visual detail spec: {exc}") from exc
    if not isinstance(spec, Mapping):
        raise ValueError("visual detail spec must be a mapping")
    if spec.get("project") != project or spec.get("task_id") != task_id:
        raise ValueError("visual detail spec project/task identity mismatch")

    verified_refs: list[dict] = []
    refs = spec.get("source_refs", [])
    if not isinstance(refs, list):
        raise ValueError("source_refs must be a list")
    for index, ref in enumerate(refs):
        ref_map = _require_mapping(ref, f"source_refs[{index}]")
        _require_fields(ref_map, ["path", "sha256"], f"source_refs[{index}]")
        relative = Path(str(ref_map["path"]))
        if relative.is_absolute():
            raise ValueError(f"source_refs[{index}].path must be repository-relative")
        resolved_ref = _bounded_regular_file(
            root / relative,
            project_root,
            label=f"source_refs[{index}]",
        )
        observed = _sha256(resolved_ref.read_bytes())
        if observed != ref_map["sha256"]:
            raise ValueError(f"source_refs[{index}] sha256 mismatch")
        verified_refs.append({"path": relative.as_posix(), "sha256": observed})

    normalized_spec = deepcopy(dict(spec))
    normalized_spec["source_refs"] = verified_refs
    pack = compile_visual_detail_card_pack(normalized_spec)
    validation = validate_visual_detail_card_pack(pack)
    if validation["status"] != "pass":
        raise ValueError("compiled visual detail card pack failed validation")

    version_root = task_root / "artifacts" / "visual_detail_cards" / "versions" / pack["pack_sha256"]
    pack_path = version_root / "visual_detail_card_pack.yml"
    if pack_path.exists():
        existing = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
        if existing != pack:
            raise ValueError("immutable visual detail card version collision")
    else:
        atomic_write_yaml(pack_path, pack)
    pack_file_sha256 = _sha256(pack_path.read_bytes())
    source_file_sha256 = _sha256(source.read_bytes())
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "pass",
        "project": project,
        "task_id": task_id,
        "candidate_only": True,
        "source_path": source.relative_to(root).as_posix(),
        "source_file_sha256": source_file_sha256,
        "source_spec_sha256": pack["source_spec_sha256"],
        "source_refs": verified_refs,
        "pack_path": pack_path.relative_to(root).as_posix(),
        "pack_sha256": pack["pack_sha256"],
        "pack_file_sha256": pack_file_sha256,
        "validation": validation,
        "promotion_authorized": False,
    }
    receipt_path = version_root / "materialization_receipt.yml"
    if receipt_path.exists():
        existing_receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
        if existing_receipt != receipt:
            raise ValueError("immutable visual detail card receipt collision")
    else:
        atomic_write_yaml(receipt_path, receipt)

    index_path = task_root / "artifacts" / "visual_detail_cards" / "candidate_index.yml"
    index = {
        "schema_version": "narrative-visual-detail-card-candidate-index/v1",
        "project": project,
        "task_id": task_id,
        "candidate_only": True,
        "current_candidate": None,
        "card_identity_index": [],
        "versions": [],
    }
    if index_path.exists():
        loaded = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict) or not isinstance(loaded.get("versions"), list):
            raise ValueError("invalid visual detail card candidate index")
        index = loaded
    entry = {
        "pack_sha256": pack["pack_sha256"],
        "pack_path": receipt["pack_path"],
        "receipt_path": receipt_path.relative_to(root).as_posix(),
        "status": "current_candidate",
    }
    matched = False
    for prior in index["versions"]:
        if not isinstance(prior, dict):
            raise ValueError("invalid visual detail card candidate index version")
        if prior.get("pack_sha256") == pack["pack_sha256"]:
            prior.update(entry)
            matched = True
        else:
            prior["status"] = "superseded_candidate"
            prior["superseded_by"] = pack["pack_sha256"]
    if not matched:
        index["versions"].append(entry)
    index["current_candidate"] = entry
    index["card_identity_index"] = [
        {
            "card_id": card["card_id"],
            "kind": card["kind"],
            "display_name": card["display_name"],
            "identity_digest": card["identity_digest"],
            "identity_reference_asset_id": card["identity_reference_asset_id"],
            "identity_reference_prompt_sha256": card["identity_reference"]["prompt_sha256"],
            "prompt_count": len(card["prompt_set"]) + 1,
        }
        for card in pack["cards"]
    ]
    atomic_write_yaml(index_path, index)

    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "pass",
        "project": project,
        "task_id": task_id,
        "candidate_only": True,
        "pack_path": receipt["pack_path"],
        "receipt_path": entry["receipt_path"],
        "candidate_index_path": index_path.relative_to(root).as_posix(),
        "pack_sha256": pack["pack_sha256"],
        "pack_file_sha256": pack_file_sha256,
        "card_count": validation["card_count"],
        "prompt_count": validation["prompt_count"],
        "promotion_authorized": False,
    }
