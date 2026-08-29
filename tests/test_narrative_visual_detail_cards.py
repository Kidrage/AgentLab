from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest
import yaml

from agent_runtime.narrative.visual_detail_cards import (
    compile_visual_detail_card_pack,
    materialize_visual_detail_card_pack,
    validate_visual_detail_card_pack,
)


ROOT = Path(__file__).resolve().parents[1]


def _character_card() -> dict:
    return {
        "card_id": "character-shen-du",
        "kind": "character",
        "display_name": "沈渡",
        "invariant": {
            "facial_structure": "窄长鹅蛋脸，下颌利落，颧骨克制",
            "facial_features": "直鼻薄唇，左眉尾有一道浅断痕",
            "skin": "冷调小麦肤色，真实细微毛孔",
            "eyes": "深褐狭长眼，外眼角微垂，目光安静警觉",
            "hair": "墨黑长发，发际线自然，常以旧乌木簪束半髻",
            "body": "青年男性，一百八十四厘米，宽肩窄腰，长腿，精瘦而非健美块状",
            "hands_and_nails": "修长有剑茧的手，短圆甲，甲面自然无亮油，虎口旧伤",
            "signature_details": "右锁骨下旧箭伤，腰侧青布钱囊",
            "negative_constraints": "不得改变脸型、眼距、断眉、肤色、身高比例与惯用手",
        },
        "variants": [
            {
                "variant_id": "wanderer",
                "state": "初入江湖，克制疲惫，无明显外伤",
                "wardrobe": {
                    "silhouette": "窄袖交领短褐配便于骑行的下裳",
                    "layers": "麻布中衣、靛灰短褐、旧黑斗篷",
                    "materials": "粗麻、旧棉、磨损皮革",
                    "palette": "靛灰、烟黑、少量土褐",
                    "construction": "右衽、暗针补丁、皮绳束袖",
                    "ornament": "无贵重纹章，仅乌木簪",
                    "footwear": "旧牛皮薄底靴，鞋头有泥痕",
                },
                "grooming": "鬓角略乱，下颌有一天青茬",
                "manicure": "短圆自然甲，缝隙有洗不净的淡墨和尘土",
                "wear_state": "斗篷下摆磨毛，左袖两处细补丁",
            },
            {
                "variant_id": "merchant",
                "state": "掌柜身份，沉静自信，无伤",
                "wardrobe": {
                    "silhouette": "修身圆领袍外罩深青半臂",
                    "layers": "白绢中衣、玄青袍、暗纹半臂",
                    "materials": "素绢、细棉、哑光熟皮",
                    "palette": "玄青、月白、暗金",
                    "construction": "密针滚边、隐藏式内袋、窄革带",
                    "ornament": "乌木簪与无字青玉扣",
                    "footwear": "深色软底云头靴",
                },
                "grooming": "发髻整齐，面部干净",
                "manicure": "短圆自然甲，洁净哑光，剑茧仍清楚",
                "wear_state": "衣料平整，仅袖口有轻微使用褶皱",
            },
        ],
    }


def _map_card() -> dict:
    return {
        "card_id": "map-nine-rivers",
        "kind": "map",
        "display_name": "九川总图",
        "invariant": {
            "geography": "西北高原向东南海湾逐级下降，三条主河汇入镜海",
            "scale_and_orientation": "上北下南，九百里横幅尺度，固定比例尺",
            "terrain": "雪岭、黄土台塬、江南丘陵与东南冲积平原层次分明",
            "water_system": "洛水、沧江、白练河的源流、支流和渡口固定",
            "settlements": "上京、临川、雁回关、镜海港位置固定",
            "routes_and_borders": "盐路、茶马道、漕运线与三方政权边界可追踪",
            "labels": "中文小楷地名，主次字号固定，不出现现代行政符号",
            "palette_and_style": "古绢本设色舆图，矿物青绿与赭石，非卫星图",
            "negative_constraints": "不得移动河源、城池、关隘、海岸线或改变方位",
        },
        "variants": [
            {
                "variant_id": "political-year-one",
                "state": "故事元年政区与商路状态",
                "overlays": "政权边界用淡朱，商路用赭金，水运用靛青",
                "wear_state": "新绘制，绢边轻微卷曲",
            }
        ],
    }


def _location_card() -> dict:
    return {
        "card_id": "location-rain-ferry",
        "kind": "location",
        "display_name": "听雨渡",
        "invariant": {
            "architecture": "一座歇山顶木亭、三间低矮客栈与伸入江面的旧栈桥",
            "terrain_and_layout": "北岸砾石滩，客栈在西，渡亭居中，东侧芦苇湾",
            "materials": "湿黑木、青灰瓦、麻绳、卵石与旧铜灯",
            "light_and_atmosphere": "江南长雨，冷灰天光，灯火呈低饱和暖橙",
            "palette": "黛青、湿木黑、芦苇褐、灯火橙",
            "weather_states": "细雨、暴雨后水雾、冬晨薄霜；地标位置不变",
            "signature_details": "亭柱第三根有刀痕，栈桥末端系一只乌篷船",
            "negative_constraints": "不得改变客栈、渡亭、芦苇湾与江流的相对方位",
        },
        "variants": [
            {
                "variant_id": "night-rain",
                "state": "夜雨，渡口停航",
                "lighting": "客栈两盏油灯与远处闪电提供层次",
                "seasonal_detail": "深秋芦花沾雨",
            }
        ],
    }


def _prop_card() -> dict:
    return {
        "card_id": "prop-river-contract",
        "kind": "prop",
        "display_name": "山河契",
        "invariant": {
            "geometry_and_dimensions": "三十二厘米长的窄卷，展开宽十四厘米",
            "materials": "桑皮纸、青麻系绳、氧化铜扣",
            "surface_and_color": "纸色旧黄，边缘深褐，墨色因水渍局部晕开",
            "mechanism": "铜扣旋开后露出夹层，夹层藏半枚朱印",
            "markings": "正面七列行书，右下角残缺山河纹印记",
            "wear_and_damage": "左上角火灼缺口与两道折痕固定",
            "handling_scale": "单手可握，展开时需双手，和成年男性手掌比例固定",
            "negative_constraints": "不得补全残印、改变火灼位置、文字列数或铜扣结构",
        },
        "variants": [
            {
                "variant_id": "sealed",
                "state": "青麻绳封缄，铜扣闭合",
                "context": "放在深色木案上",
                "wear_state": "干燥旧损，无新增血迹",
            }
        ],
    }


def _spec(*cards: dict) -> dict:
    return {
        "schema_version": "narrative-visual-detail-spec/v1",
        "project": "ShanHeYouJia",
        "task_id": "task-shanhe-blueprint-006",
        "cards": list(cards) or [
            _character_card(),
            _map_card(),
            _location_card(),
            _prop_card(),
        ],
        "source_refs": [],
    }


def test_compiles_stable_identity_lock_into_every_character_prompt() -> None:
    pack = compile_visual_detail_card_pack(_spec())

    assert pack["schema_version"] == "narrative-visual-detail-card-pack/v1"
    assert pack["candidate_only"] is True
    assert pack["generation_contract"] == {
        "role": "ArtifactProducer",
        "worker": "codex",
        "backend": "codex_imagegen_handoff",
        "auto_executable": False,
        "reference_images_required_after_first_accepted_generation": True,
    }
    assert pack["review_contract"]["observer"] == {"role": "Observer", "worker": "agy"}
    assert pack["review_contract"]["reviewer"] == {"role": "Reviewer", "worker": "agy"}
    assert pack["review_contract"]["verifier"] == {"role": "Verifier", "worker": "codex"}

    character = next(card for card in pack["cards"] if card["kind"] == "character")
    reference = character["identity_reference"]
    assert reference["asset_id"] == "character-shen-du::identity-reference"
    assert character["identity_lock_prompt"] in reference["prompt"]
    assert reference["prompt_sha256"] == hashlib.sha256(reference["prompt"].encode()).hexdigest()
    assert reference["must_be_accepted_before_dependent_generation"] is True
    prompts = character["prompt_set"]
    assert {item["variant_id"] for item in prompts} == {"wanderer", "merchant"}
    assert {item["shot_id"] for item in prompts} >= {
        "face-front-neutral",
        "face-three-quarter",
        "face-profile",
        "full-body-front",
        "full-body-back",
        "hands-and-nails-detail",
        "garment-construction-detail",
        "state-expression",
    }
    assert all(character["identity_lock_prompt"] in item["prompt"] for item in prompts)
    assert all(item["prompt_sha256"] == hashlib.sha256(item["prompt"].encode()).hexdigest() for item in prompts)
    assert all(item["reference_asset_ids"] == ["character-shen-du::identity-reference"] for item in prompts)
    assert validate_visual_detail_card_pack(pack)["status"] == "pass"


def test_compiles_kind_specific_map_location_and_prop_views() -> None:
    pack = compile_visual_detail_card_pack(_spec())
    cards = {card["kind"]: card for card in pack["cards"]}

    assert {p["shot_id"] for p in cards["map"]["prompt_set"]} >= {
        "master-map",
        "terrain-relief",
        "route-overlay",
        "regional-detail",
    }
    assert {p["shot_id"] for p in cards["location"]["prompt_set"]} >= {
        "establishing-wide",
        "human-eye-level",
        "spatial-reverse",
        "material-detail",
    }
    assert {p["shot_id"] for p in cards["prop"]["prompt_set"]} >= {
        "orthographic-front",
        "orthographic-back",
        "three-quarter",
        "material-detail",
        "in-hand-scale",
    }


def test_rejects_character_without_body_or_hands_and_nails_lock() -> None:
    card = _character_card()
    del card["invariant"]["hands_and_nails"]

    with pytest.raises(ValueError, match="hands_and_nails"):
        compile_visual_detail_card_pack(_spec(card))


def test_validation_detects_prompt_and_pack_hash_tampering() -> None:
    pack = compile_visual_detail_card_pack(_spec())
    pack["cards"][0]["prompt_set"][0]["prompt"] += " changed"

    result = validate_visual_detail_card_pack(pack)

    assert result["status"] == "blocked"
    assert any("prompt_sha256" in issue for issue in result["issues"])
    assert any("pack_sha256" in issue for issue in result["issues"])


def test_materialization_is_task_bounded_hash_sealed_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    task = root / "projects" / "ShanHeYouJia" / "runtime" / "tasks" / "task-shanhe-blueprint-006"
    inputs = task / "inputs"
    inputs.mkdir(parents=True)
    source_fact = task / "artifacts" / "character_bible.md"
    source_fact.parent.mkdir(parents=True)
    source_fact.write_text("沈渡人物圣经", encoding="utf-8")
    spec = _spec()
    spec["source_refs"] = [
        {
            "path": source_fact.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(source_fact.read_bytes()).hexdigest(),
        }
    ]
    spec_path = inputs / "visual-detail-spec.yml"
    spec_path.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")

    first = materialize_visual_detail_card_pack(
        root,
        project="ShanHeYouJia",
        task_id="task-shanhe-blueprint-006",
        source_path=spec_path,
    )
    second = materialize_visual_detail_card_pack(
        root,
        project="ShanHeYouJia",
        task_id="task-shanhe-blueprint-006",
        source_path=spec_path,
    )

    assert first == second
    pack_path = root / first["pack_path"]
    receipt_path = root / first["receipt_path"]
    assert pack_path.is_file() and receipt_path.is_file()
    assert pack_path.parent.name == first["pack_sha256"]
    assert hashlib.sha256(pack_path.read_bytes()).hexdigest() == first["pack_file_sha256"]
    assert yaml.safe_load(pack_path.read_text(encoding="utf-8"))["pack_sha256"] == first["pack_sha256"]
    index = yaml.safe_load((root / first["candidate_index_path"]).read_text(encoding="utf-8"))
    assert index["current_candidate"]["pack_sha256"] == first["pack_sha256"]
    assert {item["card_id"] for item in index["card_identity_index"]} == {
        "character-shen-du",
        "map-nine-rivers",
        "location-rain-ferry",
        "prop-river-contract",
    }


def test_materialization_rejects_source_outside_exact_task_inputs(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    other = root / "visual-detail-spec.yml"
    other.parent.mkdir(parents=True)
    other.write_text(yaml.safe_dump(_spec(), allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="exact task inputs"):
        materialize_visual_detail_card_pack(
            root,
            project="ShanHeYouJia",
            task_id="task-shanhe-blueprint-006",
            source_path=other,
        )


def test_narrative_blueprint_protocol_requires_visual_detail_card_pack() -> None:
    config = yaml.safe_load((ROOT / "config" / "production_packs.yml").read_text(encoding="utf-8"))
    pack = next(item for item in config["packs"] if item["pack_id"] == "narrative_blueprint")

    assert "visual_detail_card_pack.yml" in pack["required_outputs"]
    assert "visual_detail_card_pack" in pack["memory_contract"]
    contract = next(
        item
        for item in pack["protocol"]["artifact_contracts"]
        if item["artifact_type"] == "visual_detail_card_pack"
    )
    assert contract["producer_node"] == "state_projector"
    assert contract["candidate_only"] is True
    assert "pack_sha256" in contract["required_markers"]
    assert "identity_lock_prompt" in contract["required_markers"]
    assert "visual_detail_cards_hash_verified" in pack["quality_gates"]


def test_visual_detail_card_cli_commands_are_registered() -> None:
    for command in ("compile-visual-cards", "validate-visual-cards"):
        result = subprocess.run(
            [str(ROOT / "agentlab.sh"), "narrative", command, "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
