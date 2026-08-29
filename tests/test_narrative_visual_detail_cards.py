from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading

import pytest
from PIL import Image
import yaml

import agent_runtime.narrative.visual_detail_cards as visual_detail_cards
import agent_runtime.narrative.visual_reference_runtime as visual_reference_runtime
from agent_runtime.narrative.visual_detail_cards import (
    compile_visual_generation_batch,
    compile_visual_detail_card_pack,
    load_visual_detail_spec,
    validate_identity_reference_acceptance,
    validate_visual_detail_card_pack,
    visual_reference_task_id,
)
from agent_runtime.narrative.visual_reference_runtime import (
    ingest_managed_visual_identity_reference,
)
from agent_runtime.production_protocols import ProductionProtocolRunner
from agent_runtime.task_runtime_v2 import InvalidTransition, TaskRuntime


ROOT = Path(__file__).resolve().parents[1]


def _character_card() -> dict:
    return {
        "card_id": "character-shen-du",
        "kind": "character",
        "display_name": "沈渡",
        "invariant": {
            "gender": "male",
            "facial_structure": {
                "face_shape": "窄长鹅蛋脸",
                "forehead": "额头中等偏高，额角平顺",
                "cheekbones": "颧骨克制，不外扩",
                "jaw": "下颌利落，颏部略窄",
                "asymmetry": "右侧咬肌略强，笑时右嘴角先抬",
            },
            "facial_features": {
                "brows": "平直浓眉，左眉尾有一道浅断痕",
                "nose": "鼻梁直，鼻尖收束，鼻翼窄",
                "lips": "薄唇，唇峰浅，下唇中央略厚",
                "ears": "耳廓贴近头部，耳垂薄",
                "distinguishing_marks": "左眉尾四毫米断痕",
            },
            "skin": "冷调小麦肤色，真实细微毛孔",
            "eyes": {
                "shape": "狭长眼，外眼角微垂",
                "iris_color": "深褐色，虹膜外圈更深",
                "eyelids": "窄内双，上眼睑薄",
                "spacing": "眼距约一只眼宽",
                "gaze": "安静警觉，注视时不夸张眯眼",
            },
            "hair_color": {
                "base": "墨黑",
                "undertone": "冷棕",
                "highlights": "日光下发梢呈极淡深栗色",
            },
            "hairstyle": {
                "length": "过肩至肩胛下缘",
                "texture": "直发，发丝中等粗，受潮后微弯",
                "parting": "自然中分略偏左，发际线不过度整齐",
                "structure": "上半束半髻，下半自然垂落",
            },
            "hair_accessories": {
                "primary": "旧乌木簪",
                "materials": "哑光乌木，无金属镶嵌",
                "placement": "从半髻左下向右上穿入",
                "secondary": "黑色棉绳隐藏束发，无外露珠饰",
            },
            "body": "青年男性，一百八十四厘米，宽肩窄腰，长腿，精瘦而非健美块状",
            "hands": {
                "proportion": "long_narrow",
                "joints": "fine_straight",
                "callus_pattern": "sword_grip",
                "marks": "right_thenar_scar",
                "dominant_hand": "right",
                "hand_armor": "none",
            },
            "signature_details": "右锁骨下旧箭伤，腰侧青布钱囊",
            "negative_constraints": "不得改变脸型、眼距、断眉、肤色、身高比例与主侧使用习惯",
        },
        "variants": [
            {
                "variant_id": "wanderer",
                "state": "初入江湖，克制疲惫，无明显外伤",
                "hand_pose": "sword_grip",
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
                "hairstyle": {
                    "form": "松束半髻",
                    "front": "偏左中分，鬓角受潮散落",
                    "back": "发尾自然落至肩胛",
                    "texture_state": "带江雾湿气，发丝成小束但不油腻",
                },
                "hair_accessories": {
                    "items": "旧乌木簪与隐藏黑棉绳",
                    "materials": "磨损乌木与棉线",
                    "placement": "木簪保持左下向右上",
                    "condition": "簪尾有旧磕痕，不新增装饰",
                },
                "wear_state": "斗篷下摆磨毛，左袖两处细补丁",
            },
            {
                "variant_id": "merchant",
                "state": "商号主事身份，沉静自信，无伤",
                "hand_pose": "ledger_writing",
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
                "hairstyle": {
                    "form": "紧实半髻",
                    "front": "偏左中分，鬓发收整但保留发际碎发",
                    "back": "下半发梳顺并收至背后",
                    "texture_state": "洁净哑光，可见独立发丝",
                },
                "hair_accessories": {
                    "items": "修复后的原乌木簪与黑棉绳",
                    "materials": "乌木与棉线，不加玉石金属",
                    "placement": "木簪方向与早期完全一致",
                    "condition": "裂纹修补可见，表面不抛高光",
                },
                "wear_state": "衣料平整，仅袖口有轻微使用褶皱",
            },
        ],
    }


def _female_character_card() -> dict:
    return {
        "card_id": "character-su-wantang",
        "kind": "character",
        "display_name": "苏晚棠",
        "invariant": {
            "gender": "female",
            "facial_structure": {
                "face_shape": "端正偏方的鹅蛋脸",
                "forehead": "额头饱满，发际线圆润",
                "cheekbones": "颧骨略高但转折柔和",
                "jaw": "下颌圆中带直线，颏部不尖",
                "asymmetry": "左颊略丰满，微笑时右嘴角先动",
            },
            "facial_features": {
                "brows": "自然平直眉，眉头疏、眉尾清楚",
                "nose": "鼻梁柔和，鼻尖圆润，鼻翼窄",
                "lips": "唇形清楚偏丰，唇峰圆钝",
                "ears": "耳廓小而贴，左耳垂有单枚耳洞",
                "distinguishing_marks": "右嘴角下极淡小痣",
            },
            "skin": "暖调象牙肤色，鼻翼有细雀斑，保留自然纹理",
            "eyes": {
                "shape": "杏眼，眼尾平，内眼角圆钝",
                "iris_color": "琥珀深褐，虹膜内圈有暖金细纹",
                "eyelids": "自然外双，褶线窄而稳定",
                "spacing": "眼距略小于一只眼宽",
                "gaze": "注视账目时上眼睑略压低，精确克制",
            },
            "hair_color": {
                "base": "深黑褐",
                "undertone": "暖栗棕",
                "highlights": "日光下仅发梢出现低饱和茶棕",
            },
            "hairstyle": {
                "length": "及腰",
                "texture": "粗韧直发，发尾轻微自然弯",
                "parting": "左侧三七分，无空气刘海",
                "structure": "低髻为身份锚点，后脑轮廓饱满但不夸张",
            },
            "hair_accessories": {
                "primary": "银质算盘珠簪",
                "materials": "旧银、黑漆木珠",
                "placement": "从低髻右下向左上斜穿固定",
                "secondary": "两枚极细旧银U形固定簪，不外露",
            },
            "makeup_identity": {
                "skin_texture": "雀斑与毛孔不得被底妆抹除",
                "brow_anchor": "平直眉形与自然眉峰固定",
                "eye_anchor": "不扩大眼裂，不粘夸张浓睫",
                "lip_anchor": "保留清楚偏丰的原生唇形",
            },
            "body": "二十二岁，一百七十厘米，肩背挺直，腰胯为真实成年女性曲线",
            "hands": "手掌略宽、指节灵活，右手中指有执笔薄茧",
            "legs": {
                "proportion": "大腿与小腿比例接近一比一点一，小腿线条偏长",
                "musculature": "常年登船形成紧实小腿与稳定膝部",
                "skin": "暖象牙肤色，膝盖与胫骨略有日晒色差",
                "marks": "右膝外侧一厘米旧擦伤，不得左右翻转",
            },
            "feet": {
                "shape": "脚型修长但前掌略宽，后跟窄",
                "arch": "中等足弓，承重时弧度自然下降",
                "toes": "脚趾长度由大趾向外递减，排列自然不挤压",
                "skin": "足背肤色与腿部一致，后跟有轻微真实干纹",
                "marks": "左脚踝内侧一颗浅褐小痣",
            },
            "signature_details": "右嘴角小痣、算盘珠簪、左脚踝小痣、黑漆算盘",
            "negative_constraints": "不得幼态化、瓷白磨皮、改变雀斑、腿长比例、足型和标志位置",
        },
        "variants": [
            {
                "variant_id": "river-merchant",
                "state": "初掌船队，理性戒备，江风中保持稳重",
                "wardrobe": {
                    "silhouette": "湖蓝窄袖对襟衫配深灰长裙和短半臂",
                    "layers": "素棉中衣、湖蓝衫、深灰裙、烟青防水披帛",
                    "materials": "细棉、葛布、哑光丝边、涂蜡帆布",
                    "palette": "湖蓝、深灰、银白、少量朱砂红",
                    "construction": "对襟盘扣、腋下活动片、裙侧暗袋",
                    "ornament": "算盘珠簪、小银环、黑漆算盘",
                    "footwear": "深灰软底船履，防滑麻底，可脱下核验足部锚点",
                },
                "grooming": "江风吹出两缕碎发，皮肤保持自然光泽",
                "makeup": {
                    "complexion": "轻薄暖调底妆，仅均匀局部泛红",
                    "brows": "原生平直眉，眉尾用灰棕补齐",
                    "eyes": "暖褐内眼线与极淡杏色眼影",
                    "cheeks": "低饱和杏桃色，面积克制",
                    "lips": "半哑光茶杏色润唇",
                    "finish": "低光泽耐风妆，不遮雀斑与毛孔",
                },
                "hairstyle": {
                    "form": "低髻，发尾全部收束",
                    "front": "左侧三七分，两缕受风碎发",
                    "back": "髻心顺时针盘绕，轮廓贴近后脑",
                    "texture_state": "江风下略蓬松，不油亮",
                },
                "hair_accessories": {
                    "items": "银算盘珠簪与两枚隐藏U簪",
                    "materials": "氧化旧银与黑漆木珠",
                    "placement": "主簪右下向左上斜穿",
                    "condition": "银面有细划痕，木珠无缺失",
                },
                "manicure": {
                    "style": "现代微法式与透明果冻甲结合",
                    "length": "中短，前缘超出指尖三毫米",
                    "shape": "方圆形",
                    "base_color": "半透明奶茶米色",
                    "accent_colors": "极细朱砂红法式边",
                    "finish": "玻璃感亮面",
                    "design": "无名指算盘珠几何细线",
                    "embellishments": "零立体钻饰，使用极薄金属箔点",
                    "condition": "完整新做，右中指执笔茧仍可见",
                },
                "pedicure": {
                    "style": "现代猫眼渐变足部美甲",
                    "length": "短，前缘不超过趾端一毫米",
                    "shape": "大趾方圆，其余自然圆形",
                    "base_color": "深湖蓝半透明底",
                    "accent_colors": "银灰磁光与一线朱砂红",
                    "finish": "高亮猫眼光带",
                    "design": "双足大趾纵向窄猫眼，其余纯色",
                    "embellishments": "大趾根部单枚微型银箔，不使用厚重贴钻",
                    "condition": "边缘完整，足部皮肤纹理真实",
                },
                "leg_and_foot_state": {
                    "legs": "小腿有登船后的轻微肌肉张力，无伤",
                    "feet": "足背干净，后跟保留轻微干纹",
                    "exposure": "细节照脱鞋赤足，其余镜头按服饰穿船履",
                    "footwear_interaction": "鞋头宽度匹配前掌，不挤压趾形",
                },
                "wear_state": "袖口有墨点，裙摆有轻微水痕",
            },
            {
                "variant_id": "alliance-chair",
                "state": "合伙议会主持者，沉着威严",
                "wardrobe": {
                    "silhouette": "深青立领长衫外叠宽肩织金半臂",
                    "layers": "米白绢衣、深青长衫、乌蓝半臂",
                    "materials": "素绢、云纹提花、乌木扣、氧化银",
                    "palette": "深青、乌蓝、旧银、暗朱",
                    "construction": "肩线清晰、裙褶稳定、无拖尾",
                    "ornament": "旧银算盘珠簪与合伙印戒",
                    "footwear": "黑蓝软皮履，低跟，可脱下核验足部锚点",
                },
                "grooming": "低髻光洁但保留发丝纹理，雀斑不遮",
                "makeup": {
                    "complexion": "半哑光轻薄底妆，保留鼻翼雀斑",
                    "brows": "灰黑平直眉，边界柔和",
                    "eyes": "深茶眼线与旧金细闪内眼角",
                    "cheeks": "冷豆沙色沿颧骨轻扫",
                    "lips": "半哑光深豆沙唇",
                    "finish": "正式耐久妆，皮肤不过度磨平",
                },
                "hairstyle": {
                    "form": "结构更紧密的低髻",
                    "front": "左侧三七分，额前无碎发",
                    "back": "双股扭绕后收成扁圆髻",
                    "texture_state": "顺滑但可见独立发丝",
                },
                "hair_accessories": {
                    "items": "同形旧银算盘珠簪与暗朱丝线",
                    "materials": "旧银、黑漆木、蚕丝",
                    "placement": "主簪保持固定方向，丝线沿髻根一圈",
                    "condition": "氧化层均匀，无新增珠翠",
                },
                "manicure": {
                    "style": "现代镜面铬粉框边甲",
                    "length": "中等，前缘超出指尖五毫米",
                    "shape": "短杏仁形",
                    "base_color": "半透明冷豆沙",
                    "accent_colors": "旧银镜面细框与暗朱点色",
                    "finish": "局部镜面、主体缎面",
                    "design": "食指印戒位留白，无名指细框",
                    "embellishments": "无厚重水钻，单枚极薄银箔",
                    "condition": "边缘整齐，右中指执笔茧保留",
                },
                "pedicure": {
                    "style": "现代玉石晕染与极细金线",
                    "length": "短齐趾端",
                    "shape": "大趾方圆，其余柔和圆形",
                    "base_color": "半透明墨青玉色",
                    "accent_colors": "乌蓝晕染、旧金极细线",
                    "finish": "温润玉石亮面",
                    "design": "大趾不对称山河纹晕染，其余单色",
                    "embellishments": "平面金箔线，无立体饰物",
                    "condition": "完整正式，左右设计互为对应而非复制",
                },
                "leg_and_foot_state": {
                    "legs": "站立议事后小腿肌肉轻微绷紧",
                    "feet": "足背肤色一致，左脚踝小痣清楚",
                    "exposure": "细节照脱鞋赤足，其余镜头穿软皮履",
                    "footwear_interaction": "低跟保持自然足弓与步态",
                },
                "wear_state": "正式但有使用折痕，账册带边缘轻磨",
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
    selected_cards = list(cards) or [
        _character_card(),
        _map_card(),
        _location_card(),
        _prop_card(),
    ]
    return {
        "schema_version": "narrative-visual-detail-spec/v3",
        "project": "ShanHeYouJia",
        "task_id": "task-shanhe-blueprint-006",
        "creative_policy": {
            "work_title": "山河有约",
            "female_modern_nail_art_allowed": True,
        },
        "character_roster": [
            card["card_id"] for card in selected_cards if card["kind"] == "character"
        ],
        "cards": selected_cards,
        "source_refs": [],
    }


def test_compiles_stable_identity_lock_into_every_character_prompt() -> None:
    pack = compile_visual_detail_card_pack(_spec())

    assert pack["schema_version"] == "narrative-visual-detail-card-pack/v3"
    assert pack["candidate_only"] is True
    assert pack["generation_contract"] == {
        "role": "ArtifactProducer",
        "profile_key": "artifact_producer",
        "profile_authority": "config/agent_model_profiles.yml",
        "required_worker_capability": "codex_managed_image_generation",
        "managed_tool": "image_gen.imagegen",
        "auto_executable": False,
        "reference_images_required_after_first_accepted_generation": True,
    }
    assert pack["review_contract"]["observer"] == {
        "role": "Observer",
        "profile_key": "observer",
    }
    assert pack["review_contract"]["reviewer"] == {
        "role": "Reviewer",
        "profile_key": "visual_reviewer",
    }
    assert pack["review_contract"]["producer_self_check"] == {
        "role": "ArtifactProducer",
        "profile_key": "artifact_producer",
    }
    assert pack["review_contract"]["verifier"] == {
        "role": "Verifier",
        "profile_key": "verifier",
    }

    character = next(card for card in pack["cards"] if card["kind"] == "character")
    reference = character["identity_reference"]
    assert reference["asset_id"] == "character-shen-du::identity-reference"
    assert character["identity_lock_prompt"] in reference["prompt"]
    assert (
        reference["prompt_sha256"]
        == hashlib.sha256(reference["prompt"].encode()).hexdigest()
    )
    assert reference["must_be_accepted_before_dependent_generation"] is True
    prompts = character["prompt_set"]
    assert {item["variant_id"] for item in prompts} == {"wanderer", "merchant"}
    assert {item["shot_id"] for item in prompts} >= {
        "face-front-neutral",
        "face-three-quarter",
        "face-profile",
        "facial-features-detail",
        "hair-color-style-accessories-detail",
        "full-body-front",
        "full-body-back",
        "hands-detail",
        "garment-construction-detail",
        "state-expression",
    }
    assert all(character["identity_lock_prompt"] in item["prompt"] for item in prompts)
    assert all(
        detail in reference["prompt"]
        for detail in (
            "face_shape",
            "brows",
            "nose",
            "lips",
            "ears",
            "iris_color",
            "hair_color",
            "hairstyle",
            "hair_accessories",
        )
    )
    assert all(
        forbidden not in item["prompt"].lower()
        for item in prompts
        for forbidden in ("指甲", "趾甲", "美甲", "manicure", "pedicure", "nail")
    )
    assert all(
        item["prompt_sha256"] == hashlib.sha256(item["prompt"].encode()).hexdigest()
        for item in prompts
    )
    assert all(
        item["reference_asset_ids"] == ["character-shen-du::identity-reference"]
        for item in prompts
    )
    assert validate_visual_detail_card_pack(pack)["status"] == "pass"


def test_compiles_female_beauty_hair_leg_foot_and_modern_nail_art_details() -> None:
    pack = compile_visual_detail_card_pack(_spec(_female_character_card()))
    character = pack["cards"][0]

    assert character["character_detail_contract"]["modern_nail_art_allowed"] is True
    assert character["character_detail_contract"]["nail_art_vocabulary"] == {
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
    }
    required_shots = set(character["required_shot_ids"])
    assert {
        "makeup-face-detail",
        "hair-color-style-accessories-detail",
        "hands-and-manicure-detail",
        "legs-detail",
        "feet-and-pedicure-detail",
    } <= required_shots
    prompt = character["identity_reference"]["prompt"]
    assert "现代美甲元素为《山河有约》的合法视觉设定" in prompt
    assert all(
        detail in prompt
        for detail in (
            "hair_color",
            "hairstyle",
            "hair_accessories",
            "makeup_identity",
            "legs",
            "feet",
            "manicure",
            "pedicure",
            "base_color",
            "accent_colors",
            "embellishments",
        )
    )
    assert (
        len(
            {
                json.dumps(v["manicure"], ensure_ascii=False, sort_keys=True)
                for v in character["variants"]
            }
        )
        == 2
    )
    assert (
        len(
            {
                json.dumps(v["pedicure"], ensure_ascii=False, sort_keys=True)
                for v in character["variants"]
            }
        )
        == 2
    )
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


def _test_signing_key(authority: Path, name: str) -> tuple[Path, Path]:
    private_key = authority / f"{name}-private.pem"
    public_key = authority / f"{name}-public.pem"
    subprocess.run(
        [
            "/usr/bin/openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(private_key),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "/usr/bin/openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    return private_key, public_key


def _sign_test_payload(private_key: Path, signature: Path, payload: dict) -> None:
    subprocess.run(
        [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(signature),
        ],
        input=(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8"),
        check=True,
        capture_output=True,
    )


def _accepted_reference_receipt(
    root: Path,
    pack: dict,
    *,
    include_generation_surface: bool = True,
    rejected_review_stage: str | None = None,
    invalidate_tool_attestation: bool = False,
    omit_human_protocol_gate: bool = False,
) -> dict:
    _copy_protocol_config(root)
    authority = root.parent / "visual-approval-authority"
    authority.mkdir(parents=True, exist_ok=True)
    human_private_key, human_public_key = _test_signing_key(authority, "human")
    tool_private_key, tool_public_key = _test_signing_key(authority, "imagegen")
    config = root / "config" / "local_private_topology.yml"
    config.write_text(
        yaml.safe_dump(
            {
                "user_approval_authority": {
                    "public_key_path": str(human_public_key),
                    "public_key_sha256": hashlib.sha256(
                        human_public_key.read_bytes()
                    ).hexdigest(),
                },
                "codex_managed_tool_authority": {
                    "public_key_path": str(tool_public_key),
                    "public_key_sha256": hashlib.sha256(
                        tool_public_key.read_bytes()
                    ).hexdigest(),
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    card = next(
        item for item in pack["cards"] if item["card_id"] == "character-shen-du"
    )
    task_id = visual_reference_task_id(pack, "character-shen-du")
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    visual_projection = runtime.load_task(pack["task_id"])
    visual_versions = [
        (version_id, artifact)
        for version_id, artifact in visual_projection["artifacts"].items()
        if artifact["artifact_id"] == "visual_detail_card_pack"
        and artifact.get("disposition", "eligible") == "eligible"
    ]
    assert len(visual_versions) == 1
    visual_version_id, _visual_artifact = visual_versions[0]
    runtime.create_task(
        task_id=task_id,
        title="Generate and review one identity reference",
        user_goal="Bind one identity image to independent review evidence.",
        protocol_ref="narrative.visual.reference.v1",
        input_profile={
            "kind": "visual_identity_reference_build",
            "scope": "single_asset",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
            "project": "ShanHeYouJia",
            "source_visual_task_id": pack["task_id"],
            "source_visual_pack_version_id": visual_version_id,
            "source_visual_pack_sha256": pack["pack_sha256"],
            "card_id": "character-shen-du",
            "identity_reference_prompt_sha256": card["identity_reference"][
                "prompt_sha256"
            ],
        },
        idempotency_key="create-reference-task",
    )
    projection = ProductionProtocolRunner(
        root,
        project="ShanHeYouJia",
    ).prepare(task_id)
    runtime.transition_task(task_id, status="ready", idempotency_key="reference-ready")
    runtime.transition_task(
        task_id, status="running", idempotency_key="reference-running"
    )

    stage_config = {
        "generation": (
            "ArtifactProducer",
            "codex",
            "openai",
            "gpt-image-2",
            "codex",
            "fixture-generation",
        ),
        "producer_self_check": (
            "ArtifactProducer",
            "codex",
            "openai",
            "gpt-5.6-sol",
            "codex",
            "codex_gpt_5_6_sol_medium_cli_oauth",
        ),
        "observer": (
            "Observer",
            "agy",
            "google",
            "gemini-3.6-flash-high",
            "agy_observer",
            "gemini_3_6_flash_high_agy_oauth",
        ),
        "reviewer": (
            "Reviewer",
            "agy",
            "google",
            "gemini-3.6-flash-high",
            "agy_visual_reviewer",
            "gemini_3_6_flash_high_agy_oauth",
        ),
        "verifier": (
            "Verifier",
            "hermes",
            "deepseek",
            "deepseek-v4-flash",
            "hermes_deepseek",
            "deepseek_v4_flash_hermes_private",
        ),
    }
    stage_evidence: dict[str, dict[str, str]] = {}
    immutable_asset: Path | None = None
    asset_sha256 = ""
    for stage_id, (
        role,
        worker,
        provider,
        model_id,
        invocation_contract,
        model_key,
    ) in stage_config.items():
        runtime.transition_work_item(
            task_id,
            work_item_id=stage_id,
            status="running",
            idempotency_key=f"start-{stage_id}",
        )
        attempt_id = f"attempt-{stage_id}-001"
        runtime.schedule_attempt(
            task_id,
            work_item_id=stage_id,
            attempt_id=attempt_id,
            worker=worker,
            provider=provider,
            execution_contract={
                "role": role,
                "executor_type": "cli_agent",
                "invocation_contract": invocation_contract,
                "model_key": model_key,
                "model_id": model_id,
                "runtime_provider": provider,
                "agent_model_profile": projection["work_items"][stage_id][
                    "agent_model_profile"
                ],
                "input_tier": projection["task"]["input_classification"]["tier"],
                "route": projection["task"]["input_classification"]["route"],
            },
            idempotency_key=f"schedule-{stage_id}",
        )
        runtime.transition_attempt(
            task_id,
            attempt_id=attempt_id,
            status="running",
            idempotency_key=f"run-{stage_id}",
        )
        task_root = runtime._task_dir(task_id)
        attempt_root = task_root / "attempt_logs" / attempt_id
        attempt_root.mkdir(parents=True)
        generated_asset: Path | None = None
        generated_asset_sha256 = ""
        if stage_id == "generation":
            generated_asset = (
                task_root / "artifacts" / "staging" / "shen-du-reference.png"
            )
            generated_asset.parent.mkdir(parents=True)
            generated_asset.write_bytes(b"fixture-image")
            generated_asset_sha256 = hashlib.sha256(
                generated_asset.read_bytes()
            ).hexdigest()
        output = attempt_root / "output.md"
        if stage_id == "generation":
            output.write_text("generation: complete\n", encoding="utf-8")
        else:
            rejected = stage_id == rejected_review_stage
            output.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": "narrative-visual-stage-review/v1",
                        "stage_id": stage_id,
                        "role": role,
                        "asset_sha256": asset_sha256,
                        "status": "complete",
                        "verdict": "reject" if rejected else "pass",
                        "blocking_issues": (
                            ["identity consistency failed"] if rejected else []
                        ),
                        "dimensions": {
                            dimension: {
                                "status": (
                                    "fail"
                                    if rejected and dimension == "identity_consistency"
                                    else "pass"
                                ),
                                "evidence": [f"{stage_id}:{dimension}:checked"],
                            }
                            for dimension in (
                                "identity_consistency",
                                "wardrobe_and_state_consistency",
                                "spatial_and_scale_consistency",
                                "prompt_and_asset_hash_integrity",
                            )
                        },
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
        managed_tool_attestation: dict = {}
        if stage_id == "generation" and include_generation_surface:
            attestation_payload = {
                "schema_version": "narrative-visual-managed-imagegen-attestation-payload/v1",
                "action": "attest_codex_managed_imagegen_result",
                "tool": "image_gen.imagegen",
                "project": "ShanHeYouJia",
                "task_id": task_id,
                "attempt_id": attempt_id,
                "artifact_version_id": "shen-du-reference-v1",
                "card_id": "character-shen-du",
                "prompt_sha256": card["identity_reference"]["prompt_sha256"],
                "asset_sha256": generated_asset_sha256,
                "session_id": "codex-generation-session",
                "selected_provider": provider,
                "selected_model_id": model_id,
                "tool_result_id": "fixture-imagegen-result-001",
            }
            tool_signature = authority / "shen-du-imagegen.sig"
            _sign_test_payload(tool_private_key, tool_signature, attestation_payload)
            if invalidate_tool_attestation:
                invalid_signature = bytearray(tool_signature.read_bytes())
                invalid_signature[0] ^= 1
                tool_signature.write_bytes(invalid_signature)
            managed_tool_attestation = {
                "status": "attested",
                "signed_payload": attestation_payload,
                "signature_path": str(tool_signature),
            }
        model_receipt = attempt_root / "model_execution_receipt.yml"
        model_receipt.write_text(
            yaml.safe_dump(
                {
                    "status": "pass",
                    "role": role,
                    "worker": worker,
                    "invocation_contract": invocation_contract,
                    "selected_provider": provider,
                    "selected_model_key": model_key,
                    "selected_model_id": model_id,
                    "session_id": f"{worker}-{stage_id}-session",
                    "profile_binding_verified": True,
                    "command_binding_verified": True,
                    "provider_model_binding_verified": True,
                    "provider_process_started": True,
                    "fallback_detected": False,
                    "exit_code": 0,
                    "issues": [],
                    **(
                        {
                            "execution_surface": "codex_managed_imagegen",
                            "managed_tool": "image_gen.imagegen",
                            "generated_asset_sha256": generated_asset_sha256,
                            "managed_tool_attestation": managed_tool_attestation,
                        }
                        if stage_id == "generation" and include_generation_surface
                        else {}
                    ),
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        model_sha256 = hashlib.sha256(model_receipt.read_bytes()).hexdigest()
        receipt_path = attempt_root / "attempt_receipt.yml"
        receipt_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "task-runtime-role-attempt-receipt/v1",
                    "project": "ShanHeYouJia",
                    "task_id": task_id,
                    "work_item_id": stage_id,
                    "attempt_id": attempt_id,
                    "role": role,
                    "worker": worker,
                    "provider": provider,
                    "status": "pass",
                    "output_path": output.relative_to(task_root).as_posix(),
                    "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "sealed_sources": (
                        [
                            {
                                "path": immutable_asset.relative_to(root).as_posix(),
                                "sha256": asset_sha256,
                            }
                        ]
                        if immutable_asset is not None
                        else []
                    ),
                    "model_execution": {
                        "path": model_receipt.relative_to(task_root).as_posix(),
                        "sha256": model_sha256,
                        "cli_agent": worker,
                        "model_key": model_key,
                        "model_id": model_id,
                        "runtime_provider": provider,
                        "executor_provider": "agentlab-cli-executor",
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        runtime._transition_executed_attempt(
            task_id,
            attempt_id=attempt_id,
            status="succeeded",
            outcome={
                "execution_origin": "role_attempt_executor",
                "receipt_path": receipt_path.relative_to(task_root).as_posix(),
                "receipt_sha256": receipt_sha256,
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            },
            idempotency_key=f"succeed-{stage_id}",
        )
        validation_receipt = attempt_root / "artifact_validation.yml"
        validation_receipt.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "protocol-artifact-validation/v1",
                    "status": "pass",
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "issues": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        runtime.record_attempt_output_validation(
            task_id,
            attempt_id=attempt_id,
            status="pass",
            validation_receipt_path=validation_receipt,
            issues=[],
            idempotency_key=f"validate-{stage_id}-output",
        )
        if stage_id == "generation":
            assert generated_asset is not None
            projection = runtime.record_artifact_version(
                task_id,
                artifact_id="visual_identity_reference",
                version_id="shen-du-reference-v1",
                attempt_id=attempt_id,
                path=generated_asset,
                media_type="image/png",
                idempotency_key="record-shen-du-reference",
            )
            artifact = projection["artifacts"]["shen-du-reference-v1"]
            immutable_asset = task_root / artifact["path"]
            asset_sha256 = artifact["sha256"]
            subject_digest = hashlib.sha256(
                json.dumps(
                    {"visual_identity_reference": asset_sha256},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            runtime.record_protocol_gate(
                task_id,
                gate_id="managed_imagegen_attested",
                work_item_id="generation",
                evidence_kind="automated",
                evidence_sha256=subject_digest,
                attempt_id=attempt_id,
                subject_version_ids=["shen-du-reference-v1"],
                actor="agentlab-managed-imagegen-attestation-validator",
                idempotency_key="record-managed-imagegen-gate",
            )
        stage_evidence[stage_id] = {
            "attempt_id": attempt_id,
            "attempt_receipt_sha256": receipt_sha256,
            "model_receipt_sha256": model_sha256,
        }
        if stage_id != "verifier":
            runtime.transition_work_item(
                task_id,
                work_item_id=stage_id,
                status="accepted",
                idempotency_key=f"accept-{stage_id}",
            )
    assert immutable_asset is not None
    runtime_evidence = {
        "schema_version": "narrative-visual-runtime-evidence/v1",
        "task_id": task_id,
        "artifact_version_id": "shen-du-reference-v1",
        "stages": stage_evidence,
    }
    runtime_evidence_sha256 = hashlib.sha256(
        json.dumps(
            runtime_evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    runtime.bind_evidence(
        task_id,
        binding_id="identity-reference-review-evidence",
        version_id="shen-du-reference-v1",
        input_manifest_hash=runtime_evidence_sha256,
        index_snapshot_id="identity-reference-review-snapshot",
        source_hashes={
            "runtime-evidence": runtime_evidence_sha256,
            "identity-asset": asset_sha256,
        },
        audit={"status": "all_stages_passed"},
        idempotency_key="bind-identity-reference-evidence",
    )
    runtime.select_artifact_version(
        task_id,
        version_id="shen-du-reference-v1",
        idempotency_key="select-current-identity-reference",
    )
    human_payload = {
        "schema_version": "narrative-visual-human-acceptance-signature-payload/v1",
        "action": "accept_identity_reference",
        "actor_type": "user",
        "actor_id": "local-user",
        "approved_at": "2026-08-29T02:00:00Z",
        "project": "ShanHeYouJia",
        "task_id": pack["task_id"],
        "pack_sha256": pack["pack_sha256"],
        "card_id": "character-shen-du",
        "asset_sha256": asset_sha256,
        "identity_reference_prompt_sha256": card["identity_reference"]["prompt_sha256"],
        "runtime_evidence_sha256": runtime_evidence_sha256,
    }
    signature = authority / "shen-du.sig"
    _sign_test_payload(human_private_key, signature, human_payload)
    subject_digest = hashlib.sha256(
        json.dumps(
            {"visual_identity_reference": asset_sha256},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    runtime.record_protocol_gate(
        task_id,
        gate_id="independent_visual_acceptance",
        work_item_id="verifier",
        evidence_kind="independent",
        evidence_sha256=subject_digest,
        attempt_id="attempt-verifier-001",
        subject_version_ids=["shen-du-reference-v1"],
        actor="agentlab-visual-verifier",
        idempotency_key="record-independent-visual-gate",
    )
    approvals = runtime._task_dir(task_id) / "approvals"
    approvals.mkdir(parents=True, exist_ok=True)
    protocol_approval = approvals / "human-identity-reference-approval.yml"
    protocol_approval_document = {
        "schema_version": "protocol-human-approval/v1",
        "task_id": task_id,
        "gate_id": "human_identity_reference_acceptance",
        "actor": "local-user",
        "decision": "approved",
        "evidence_sha256": subject_digest,
        "subject_artifacts": {"visual_identity_reference": asset_sha256},
    }
    protocol_approval.write_text(
        yaml.safe_dump(protocol_approval_document, sort_keys=False),
        encoding="utf-8",
    )
    protocol_signature = authority / "shen-du-protocol-approval.sig"
    _sign_test_payload(
        human_private_key,
        protocol_signature,
        protocol_approval_document,
    )
    if not omit_human_protocol_gate:
        runtime.record_protocol_gate(
            task_id,
            gate_id="human_identity_reference_acceptance",
            work_item_id="verifier",
            evidence_kind="human",
            evidence_sha256=subject_digest,
            attempt_id="attempt-verifier-001",
            subject_version_ids=["shen-du-reference-v1"],
            actor="local-user",
            approval_receipt_path=protocol_approval,
            approval_signature_path=protocol_signature,
            idempotency_key="record-human-identity-reference-gate",
        )
        runtime.transition_work_item(
            task_id,
            work_item_id="verifier",
            status="accepted",
            idempotency_key="accept-verifier",
        )
    return {
        "schema_version": "narrative-visual-identity-reference-acceptance/v1",
        "status": "accepted",
        "project": "ShanHeYouJia",
        "task_id": pack["task_id"],
        "pack_sha256": pack["pack_sha256"],
        "card_id": "character-shen-du",
        "identity_reference_prompt_sha256": card["identity_reference"]["prompt_sha256"],
        "asset": {
            "asset_id": "character-shen-du::identity-reference",
            "path": immutable_asset.relative_to(root).as_posix(),
            "sha256": asset_sha256,
        },
        "runtime_evidence": runtime_evidence,
        "human_acceptance": {
            "status": "accepted",
            "actor_id": "local-user",
            "accepted_at": "2026-08-29T02:00:00Z",
            "signed_payload": human_payload,
            "signature_path": str(signature),
        },
    }


def test_generation_batch_requires_hash_bound_accepted_identity_reference(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, pack_path = _materialize_visual_pack(root)

    first = compile_visual_generation_batch(
        pack,
        card_id="character-shen-du",
        agentlab_root=root,
        pack_path=pack_path,
        accepted_reference_receipt_paths=[],
    )
    assert first["phase"] == "identity_reference_generation"
    assert len(first["jobs"]) == 1
    assert first["jobs"][0]["input_images"] == []
    assert (
        first["jobs"][0]["required_post_generation_gate"]
        == "human_identity_reference_acceptance"
    )
    assert first["jobs"][0]["resolved_generation_profile"] == {
        "role": "ArtifactProducer",
        "profile_key": "artifact_producer",
        "mode": "full_cli",
        "tier": "alter",
        "worker": "codex",
        "invocation_contract": "codex",
        "model_key": "codex_gpt_5_6_sol_medium_cli_oauth",
    }

    receipt = _accepted_reference_receipt(root, pack)
    assert (
        validate_identity_reference_acceptance(root, pack, receipt)["status"] == "pass"
    )
    receipt_path = (
        root
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "visual_assets"
        / "shen-du-reference-acceptance.yml"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    dependent = compile_visual_generation_batch(
        pack,
        card_id="character-shen-du",
        agentlab_root=root,
        pack_path=pack_path,
        accepted_reference_receipt_paths=[receipt_path],
    )
    assert dependent["phase"] == "dependent_shot_generation"
    assert dependent["jobs"]
    assert all(
        job["input_images"][0]["sha256"] == receipt["asset"]["sha256"]
        for job in dependent["jobs"]
    )
    assert all(
        job["reference_acceptance_receipts"]
        == [
            {
                "path": receipt_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "content_sha256": validate_identity_reference_acceptance(
                    root,
                    pack,
                    receipt,
                )["acceptance_receipt_sha256"],
            }
        ]
        for job in dependent["jobs"]
    )


def test_generation_batch_rejects_offline_self_hashed_pack(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    pack = compile_visual_detail_card_pack(_spec())
    pack_path = project_root / "offline-pack.yml"
    pack_path.write_text(
        yaml.safe_dump(pack, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="visual detail card Task is unavailable"):
        compile_visual_generation_batch(
            pack,
            card_id="character-shen-du",
            agentlab_root=root,
            pack_path=pack_path,
            accepted_reference_receipt_paths=[],
        )


def test_reference_acceptance_rejects_missing_human_gate(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(root, pack)
    receipt["human_acceptance"]["status"] = "pending"

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert "human acceptance is not exact and hash-bound" in result["issues"]


def test_reference_acceptance_requires_formal_runtime_human_gate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(
        root,
        pack,
        omit_human_protocol_gate=True,
    )

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert (
        "identity reference protocol gate human_identity_reference_acceptance "
        "is missing or stale"
    ) in result["issues"]
    assert "identity reference protocol WorkItems are not accepted" in result["issues"]


def test_reference_acceptance_rejects_runtime_model_receipt_tampering(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(root, pack)
    task_id = receipt["runtime_evidence"]["task_id"]
    attempt_id = receipt["runtime_evidence"]["stages"]["generation"]["attempt_id"]
    model_receipt = (
        root
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / task_id
        / "attempt_logs"
        / attempt_id
        / "model_execution_receipt.yml"
    )
    tampered = yaml.safe_load(model_receipt.read_text(encoding="utf-8"))
    tampered["selected_model_id"] = "fabricated-model"
    model_receipt.write_text(yaml.safe_dump(tampered), encoding="utf-8")

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert any("generation receipt" in issue for issue in result["issues"])


def test_reference_acceptance_requires_codex_managed_imagegen_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(
        root,
        pack,
        include_generation_surface=False,
    )

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert (
        "identity reference generation did not bind the Codex imagegen output"
        in result["issues"]
    )


def test_reference_acceptance_rejects_untrusted_imagegen_attestation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(
        root,
        pack,
        invalidate_tool_attestation=True,
    )

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert (
        "identity reference generation lacks a trusted Codex imagegen attestation"
        in result["issues"]
    )


def test_reference_acceptance_rejects_semantically_failed_review(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(
        root,
        pack,
        rejected_review_stage="reviewer",
    )

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert "identity reference reviewer review did not pass" in result["issues"]
    assert "identity reference reviewer review has blocking issues" in result["issues"]


def test_reference_acceptance_rejects_superseded_identity_artifact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(root, pack)
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    runtime.change_artifact_disposition(
        receipt["runtime_evidence"]["task_id"],
        version_id=receipt["runtime_evidence"]["artifact_version_id"],
        disposition="superseded",
        reason_code="new_identity_reference",
        feedback_digest="a" * 64,
        idempotency_key="supersede-identity-reference",
    )

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert (
        "identity reference ArtifactVersion is missing or mismatched"
        in result["issues"]
    )


def test_reference_acceptance_requires_the_task_selected_current_version(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(root, pack)
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    task_id = receipt["runtime_evidence"]["task_id"]
    attempt_id = receipt["runtime_evidence"]["stages"]["generation"]["attempt_id"]
    old_asset = root / receipt["asset"]["path"]
    replacement_staging = (
        runtime._task_dir(task_id)
        / "artifacts"
        / "staging"
        / "shen-du-reference-v2.png"
    )
    replacement_staging.parent.mkdir(parents=True, exist_ok=True)
    replacement_staging.write_bytes(old_asset.read_bytes())
    projection = runtime.record_artifact_version(
        task_id,
        artifact_id="visual_identity_reference",
        version_id="shen-du-reference-v2",
        attempt_id=attempt_id,
        path=replacement_staging,
        media_type="image/png",
        idempotency_key="record-replacement-reference",
    )
    replacement = projection["artifacts"]["shen-du-reference-v2"]
    runtime.bind_evidence(
        task_id,
        binding_id="replacement-reference-evidence",
        version_id="shen-du-reference-v2",
        input_manifest_hash="c" * 64,
        index_snapshot_id="replacement-reference-snapshot",
        source_hashes={"replacement-asset": replacement["sha256"]},
        idempotency_key="bind-replacement-reference",
    )
    runtime.select_artifact_version(
        task_id,
        version_id="shen-du-reference-v2",
        idempotency_key="select-replacement-reference",
    )

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert (
        "identity reference ArtifactVersion is missing or mismatched"
        in result["issues"]
    )


def test_reference_acceptance_rejects_retired_execution_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    pack, _pack_path = _materialize_visual_pack(root)
    receipt = _accepted_reference_receipt(root, pack)
    contracts_path = root / "config" / "worker_invocation_contracts.yml"
    contracts = yaml.safe_load(contracts_path.read_text(encoding="utf-8"))
    contracts["contracts"]["codex"]["selectable"] = False
    contracts_path.write_text(
        yaml.safe_dump(contracts, sort_keys=False),
        encoding="utf-8",
    )

    result = validate_identity_reference_acceptance(root, pack, receipt)

    assert result["status"] == "blocked"
    assert any(
        "visual role authority is invalid" in issue for issue in result["issues"]
    )


def test_dependent_batch_rejects_multiple_current_references(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    pack, pack_path = _materialize_visual_pack(
        root,
        task_id="task-shanhe-visual-multiple-reference",
    )

    with pytest.raises(ValueError, match="exactly one current accepted reference"):
        compile_visual_generation_batch(
            pack,
            card_id="character-shen-du",
            agentlab_root=root,
            pack_path=pack_path,
            accepted_reference_receipt_paths=[Path("one.yml"), Path("two.yml")],
        )


@pytest.mark.parametrize("unsafe", ["../escape", "../../escape", "safe..escape"])
@pytest.mark.parametrize("field", ["project", "task_id"])
def test_visual_spec_loader_rejects_identifier_traversal(
    tmp_path: Path,
    unsafe: str,
    field: str,
) -> None:
    root = tmp_path / "AgentLab"
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "visual.yml"
    source.write_text(yaml.safe_dump(_spec(), allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="safe runtime identifier"):
        load_visual_detail_spec(
            root,
            project=unsafe if field == "project" else "ShanHeYouJia",
            task_id=unsafe if field == "task_id" else "task-shanhe-blueprint-006",
            source_path=source,
        )


def test_visual_spec_loader_rejects_symlinked_project_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    projects = root / "projects"
    projects.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "visual.yml"
    source.write_text(yaml.safe_dump(_spec(), allow_unicode=True), encoding="utf-8")
    (projects / "ShanHeYouJia").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinks"):
        load_visual_detail_spec(
            root,
            project="ShanHeYouJia",
            task_id="task-shanhe-blueprint-006",
            source_path=source,
        )


def test_rejects_character_without_body_or_hands_lock() -> None:
    card = _character_card()
    del card["invariant"]["hands"]

    with pytest.raises(ValueError, match="hands"):
        compile_visual_detail_card_pack(_spec(card))


def test_rejects_all_male_nail_detail_fields_and_text() -> None:
    card = _character_card()
    card["variants"][0]["manicure"] = "短圆自然甲"

    with pytest.raises(
        ValueError,
        match="male hand profile|male character must not contain nail details",
    ):
        compile_visual_detail_card_pack(_spec(card))


def test_rejects_male_uncontracted_fields_that_can_smuggle_nail_detail() -> None:
    card = _character_card()
    card["variants"][0]["digit_grooming"] = "uncontracted detail"

    with pytest.raises(ValueError, match="unsupported fields"):
        compile_visual_detail_card_pack(_spec(card))


def test_rejects_singular_english_nail_detail_in_allowed_male_field() -> None:
    card = _character_card()
    card["invariant"]["signature_details"] = "left brow scar and one broken nail"

    with pytest.raises(
        ValueError,
        match="must be a mapping|male character must not contain nail details",
    ):
        compile_visual_detail_card_pack(_spec(card))


@pytest.mark.parametrize(
    ("field", "detail"),
    [
        ("hands", "十枚指端角质硬片均修短磨平，边缘洁净；掌心有茧"),
        ("hands", "手指修长，甲床宽阔且修剪整齐"),
        ("hands", "十根指尖的半透明硬层都剪短磨圆，表面泛着健康光泽；掌心有剑茧"),
        ("hands", "十指末端甲片均修短磨平，掌心有剑茧"),
        ("signature_details", "left brow scar and broken_nail"),
    ],
)
def test_rejects_male_nail_detail_circumlocutions_in_allowed_fields(
    field: str,
    detail: str,
) -> None:
    card = _character_card()
    card["invariant"][field] = detail

    with pytest.raises(
        ValueError,
        match="must be a mapping|male character must not contain nail details",
    ):
        compile_visual_detail_card_pack(_spec(card))


def test_male_armor_terms_remain_allowed() -> None:
    card = _character_card()
    card["invariant"]["signature_details"] = "左眉断疤，肩后旧铁甲片磨痕"
    card["invariant"]["hands"]["hand_armor"] = "segmented_iron_gauntlet"
    card["variants"][0]["wardrobe"]["layers"] += "、旧皮甲"
    card["variants"][0]["state"] = "雨夜站在船首甲板，警觉而疲惫"

    pack = compile_visual_detail_card_pack(_spec(card))

    assert validate_visual_detail_card_pack(pack)["status"] == "pass"
    assert "外覆分节铁护手" in pack["cards"][0]["identity_lock_prompt"]


@pytest.mark.parametrize(
    "detail",
    [
        "十根指头末梢的硬壳都剪短磨圆，色泽健康；掌心有剑茧",
        "十指末端甲片均修短磨平，掌心有剑茧",
        "手指外覆铁甲片，边缘磨圆以免妨碍握剑；掌心有剑茧",
    ],
)
def test_male_hands_reject_free_prose_in_favor_of_governed_profiles(
    detail: str,
) -> None:
    card = _character_card()
    card["invariant"]["hands"] = detail

    with pytest.raises(ValueError, match="must be a mapping"):
        compile_visual_detail_card_pack(_spec(card))


@pytest.mark.parametrize("field", ["signature_details", "variant_state"])
def test_male_card_rejects_cross_field_nail_circumlocution(field: str) -> None:
    card = _character_card()
    detail = "十根指头末梢的硬壳都剪短磨圆，色泽健康"
    if field == "variant_state":
        card["variants"][0]["state"] = f"{detail}，精神警觉"
    else:
        card["invariant"][field] = f"右锁骨旧伤；{detail}"

    with pytest.raises(
        ValueError, match="male character must not contain nail details"
    ):
        compile_visual_detail_card_pack(_spec(card))


@pytest.mark.parametrize(
    "detail",
    [
        "双手各指末梢的透明角层均已削齐，泛着温润色泽",
        "双手末梢的十枚透明角层均削齐，呈健康光泽",
    ],
)
def test_male_card_rejects_hand_facts_outside_structured_profile(
    detail: str,
) -> None:
    card = _character_card()
    card["invariant"]["signature_details"] = f"右锁骨旧伤；{detail}"

    with pytest.raises(
        ValueError, match="male character must not contain nail details"
    ):
        compile_visual_detail_card_pack(_spec(card))


def test_male_action_uses_governed_hand_pose_instead_of_free_prose() -> None:
    card = _character_card()
    card["variants"][0]["state"] = "登高远望，神色警觉"
    card["variants"][0]["hand_pose"] = "pointing_distant"

    pack = compile_visual_detail_card_pack(_spec(card))

    assert "抬起右臂指向远方" in pack["cards"][0]["prompt_set"][0]["prompt"]

    card["variants"][0]["state"] = "抬手指向远山，神色警觉"
    assert (
        validate_visual_detail_card_pack(compile_visual_detail_card_pack(_spec(card)))[
            "status"
        ]
        == "pass"
    )


@pytest.mark.parametrize(
    "state",
    [
        "双拳紧握，准备迎敌",
        "右拳抵住心口郑重起誓",
        "握剑遥望来敌",
    ],
)
def test_male_free_action_must_match_governed_hand_pose(state: str) -> None:
    card = _character_card()
    card["variants"][0]["state"] = state
    card["variants"][0]["hand_pose"] = "ledger_writing"

    with pytest.raises(ValueError, match="conflicts with governed hand_pose"):
        compile_visual_detail_card_pack(_spec(card))


def test_male_martial_merchant_and_political_terms_are_not_nail_details() -> None:
    card = _character_card()
    card["variants"][0]["state"] = (
        "新任少林掌门，初遇江湖高手与强劲对手，负责指挥船队，沉静警觉"
    )
    card["variants"][1]["state"] = "掌柜身份，处事有铁腕风格，核对商路指标，沉静自信"

    pack = compile_visual_detail_card_pack(_spec(card))

    assert validate_visual_detail_card_pack(pack)["status"] == "pass"


def test_rejects_novel_visual_pack_without_exact_character_roster() -> None:
    spec = _spec(_map_card(), _location_card(), _prop_card())

    with pytest.raises(ValueError, match="character_roster must be non-empty"):
        compile_visual_detail_card_pack(spec)


def test_shanhe_modern_nail_art_policy_cannot_be_disabled() -> None:
    spec = _spec(_female_character_card())
    spec["creative_policy"]["female_modern_nail_art_allowed"] = False

    with pytest.raises(ValueError, match="ShanHeYouJia requires modern nail art"):
        compile_visual_detail_card_pack(spec)


def test_v2_pack_validation_rejects_missing_creative_policy_after_rehash() -> None:
    pack = compile_visual_detail_card_pack(_spec())
    pack["creative_policy"] = {}
    pack["pack_sha256"] = visual_detail_cards._pack_sha256(pack)

    result = validate_visual_detail_card_pack(pack)

    assert result["status"] == "blocked"
    assert any("creative_policy" in issue for issue in result["issues"])


@pytest.mark.parametrize("missing_field", ["source_spec_sha256", "source_refs"])
def test_v2_pack_validation_rejects_missing_source_evidence_after_rehash(
    missing_field: str,
) -> None:
    pack = compile_visual_detail_card_pack(_spec())
    del pack[missing_field]
    pack["pack_sha256"] = visual_detail_cards._pack_sha256(pack)

    result = validate_visual_detail_card_pack(pack)

    assert result["status"] == "blocked"
    assert any(missing_field in issue for issue in result["issues"])


def test_v2_pack_validation_rejects_rewritten_source_evidence() -> None:
    pack = compile_visual_detail_card_pack(_spec())
    pack["source_refs"] = [
        {"path": "projects/ShanHeYouJia/fabricated.yml", "sha256": "0" * 64}
    ]
    pack["pack_sha256"] = visual_detail_cards._pack_sha256(pack)

    result = validate_visual_detail_card_pack(pack)

    assert result["status"] == "blocked"
    assert "source_spec_sha256 does not match the compiled source" in result["issues"]


def test_v1_pack_remains_read_only_validatable_for_task_recovery() -> None:
    current = compile_visual_detail_card_pack(_spec())
    legacy_card = visual_detail_cards._compile_legacy_card(_prop_card())
    pack = {
        "schema_version": "narrative-visual-detail-card-pack/v1",
        "project": "HistoricalProject",
        "task_id": "task-historical-visual",
        "candidate_only": True,
        "promotion_state": "awaiting_visual_generation_and_human_acceptance",
        "source_spec_sha256": "historical-source-sha",
        "source_refs": [],
        "generation_contract": current["generation_contract"],
        "review_contract": current["review_contract"],
        "cards": [legacy_card],
    }
    pack["pack_sha256"] = visual_detail_cards._pack_sha256(pack)

    assert validate_visual_detail_card_pack(pack)["status"] == "pass"

    with pytest.raises(ValueError, match="requires a current"):
        compile_visual_generation_batch(
            pack,
            card_id="prop-qinglong-seal",
            agentlab_root=Path("/unneeded-for-v1-rejection"),
            pack_path=Path("historical-pack.yml"),
            accepted_reference_receipt_paths=[],
        )

    acceptance = validate_identity_reference_acceptance(Path("."), pack, {})
    assert acceptance["status"] == "blocked"
    assert any(
        "current narrative-visual-detail-card-pack/v3" in issue
        for issue in acceptance["issues"]
    )


def test_v2_string_hands_pack_remains_read_only_validatable() -> None:
    card = _character_card()
    card["invariant"]["hands"] = "十根指头末梢外覆铁质硬壳甲片，边缘磨圆以免碍剑"
    for variant in card["variants"]:
        variant.pop("hand_pose")
    source = _spec(card)
    source["schema_version"] = "narrative-visual-detail-spec/v2"
    compiled_card = visual_detail_cards._compile_card(
        card,
        creative_policy=source["creative_policy"],
        structured_male_hands=False,
    )
    current = compile_visual_detail_card_pack(_spec())
    pack = {
        "schema_version": "narrative-visual-detail-card-pack/v2",
        "project": source["project"],
        "task_id": source["task_id"],
        "candidate_only": True,
        "promotion_state": "awaiting_visual_generation_and_human_acceptance",
        "source_spec_sha256": visual_detail_cards._sha256(
            visual_detail_cards._canonical_bytes(source)
        ),
        "source_refs": [],
        "creative_policy": source["creative_policy"],
        "character_roster": source["character_roster"],
        "generation_contract": current["generation_contract"],
        "review_contract": current["review_contract"],
        "cards": [compiled_card],
    }
    pack["pack_sha256"] = visual_detail_cards._pack_sha256(pack)

    assert validate_visual_detail_card_pack(pack)["status"] == "pass"
    with pytest.raises(ValueError, match="requires a current"):
        compile_visual_generation_batch(
            pack,
            card_id="character-shen-du",
            agentlab_root=Path("/unneeded-for-v2-rejection"),
            pack_path=Path("historical-v2-pack.yml"),
            accepted_reference_receipt_paths=[],
        )


def test_rejects_female_character_without_leg_and_foot_identity_locks() -> None:
    card = _female_character_card()
    del card["invariant"]["feet"]

    with pytest.raises(ValueError, match=r"invariant\.feet"):
        compile_visual_detail_card_pack(_spec(card))


def test_rejects_female_nail_art_without_shape_length_color_and_finish() -> None:
    card = _female_character_card()
    del card["variants"][0]["pedicure"]["length"]

    with pytest.raises(ValueError, match=r"pedicure\.length"):
        compile_visual_detail_card_pack(_spec(card))


def test_validation_detects_prompt_and_pack_hash_tampering() -> None:
    pack = compile_visual_detail_card_pack(_spec())
    pack["cards"][0]["prompt_set"][0]["prompt"] += " changed"

    result = validate_visual_detail_card_pack(pack)

    assert result["status"] == "blocked"
    assert any("prompt_sha256" in issue for issue in result["issues"])
    assert any("pack_sha256" in issue for issue in result["issues"])


def test_validation_rejects_rehashed_canon_promotion_state() -> None:
    pack = compile_visual_detail_card_pack(_spec())
    pack["promotion_state"] = "canon"
    payload = dict(pack)
    payload.pop("pack_sha256")
    pack["pack_sha256"] = hashlib.sha256(
        __import__("json")
        .dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        .encode("utf-8")
    ).hexdigest()

    result = validate_visual_detail_card_pack(pack)

    assert result["status"] == "blocked"
    assert (
        "promotion_state must await visual generation and human acceptance"
        in result["issues"]
    )


def _copy_protocol_config(root: Path) -> None:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
        "agent_role_bindings.yml",
        "worker_invocation_contracts.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)


def test_anchored_visual_runtime_shares_the_standard_ledger_lock(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agentlab"
    task_root = root / "projects" / "ShanHeYouJia" / "runtime" / "tasks" / "task-lock"
    task_root.mkdir(parents=True)
    descriptor = visual_reference_runtime._open_task_subdirectory(
        root,
        task_root,
        (),
    )
    anchored = visual_reference_runtime._AnchoredTaskRuntime(
        root,
        project="ShanHeYouJia",
        task_id="task-lock",
        task_descriptor=descriptor,
        expected_task_root=task_root,
    )
    ordinary = TaskRuntime(root, project="ShanHeYouJia")
    anchored_entered = threading.Event()
    release_anchored = threading.Event()
    ordinary_entered = threading.Event()

    def hold_anchored_lock() -> None:
        with anchored._ledger_lock("task-lock"):
            anchored_entered.set()
            assert release_anchored.wait(timeout=5)

    def enter_ordinary_lock() -> None:
        with ordinary._ledger_lock("task-lock"):
            ordinary_entered.set()

    holder = threading.Thread(target=hold_anchored_lock)
    contender = threading.Thread(target=enter_ordinary_lock)
    holder.start()
    assert anchored_entered.wait(timeout=5)
    contender.start()
    assert not ordinary_entered.wait(timeout=0.1)
    release_anchored.set()
    holder.join(timeout=5)
    contender.join(timeout=5)
    assert ordinary_entered.is_set()
    anchored.close()


def _record_blueprint_artifact(
    root: Path,
    *,
    protocol_ref: str | None = "narrative.blueprint.v1",
) -> tuple[str, str]:
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    task_id = "task-shanhe-blueprint-006"
    runtime.create_task(
        task_id=task_id,
        title="Fixture blueprint",
        user_goal="Provide one exact blueprint ArtifactVersion.",
        protocol_ref=protocol_ref,
        input_profile=(
            {
                "kind": "blueprint_build",
                "scope": "longform",
                "target_count": 1,
                "canon_impact": "new_project",
                "risk_flags": [],
                "project": "ShanHeYouJia",
                "source_creative_brief": "fixture/creative-brief.yml",
                "source_creative_brief_sha256": "f" * 64,
            }
            if protocol_ref
            else None
        ),
        **({} if protocol_ref else {"legacy_source": {"kind": "test_fixture"}}),
        idempotency_key="create-blueprint-fixture",
    )
    runtime.create_work_item(
        task_id,
        job_id="job-main",
        work_item_id="blueprint",
        kind="production",
        title="Blueprint",
        idempotency_key="create-blueprint-work",
    )
    runtime.transition_task(task_id, status="ready", idempotency_key="blueprint-ready")
    runtime.transition_task(
        task_id, status="running", idempotency_key="blueprint-running"
    )
    runtime.transition_work_item(
        task_id,
        work_item_id="blueprint",
        status="running",
        idempotency_key="blueprint-work-running",
    )
    attempt_id = "attempt-blueprint-001"
    tool = {"tool_id": "fixture.blueprint", "tool_version": "1"}
    runtime.schedule_attempt(
        task_id,
        work_item_id="blueprint",
        attempt_id=attempt_id,
        worker="fixture-blueprint",
        provider="agentlab-deterministic",
        execution_contract={
            "role": "Writer",
            "executor_type": "deterministic_tool",
            "deterministic_tool": tool,
            **(
                {
                    "input_tier": runtime.load_task(task_id)["task"][
                        "input_classification"
                    ]["tier"],
                    "route": runtime.load_task(task_id)["task"]["input_classification"][
                        "route"
                    ],
                }
                if protocol_ref
                else {}
            ),
        },
        idempotency_key="schedule-blueprint",
    )
    runtime.transition_attempt(
        task_id,
        attempt_id=attempt_id,
        status="running",
        idempotency_key="run-blueprint",
    )
    task_root = runtime._task_dir(task_id)
    attempt_root = task_root / "attempt_logs" / attempt_id
    attempt_root.mkdir(parents=True)
    output = attempt_root / "output.md"
    output.write_text("story_blueprint: fixture\n", encoding="utf-8")
    receipt = attempt_root / "deterministic_execution_receipt.yml"
    receipt.write_text(
        yaml.safe_dump(
            {
                "schema_version": "task-runtime-deterministic-attempt-receipt/v1",
                "project": "ShanHeYouJia",
                "task_id": task_id,
                "work_item_id": "blueprint",
                "attempt_id": attempt_id,
                "role": "Writer",
                "worker": "fixture-blueprint",
                "provider": "agentlab-deterministic",
                "status": "pass",
                "output_path": output.relative_to(task_root).as_posix(),
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "sealed_sources": [],
                "deterministic_tool": tool,
                "model_execution": None,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    runtime._transition_deterministic_attempt(
        task_id,
        attempt_id=attempt_id,
        outcome={
            "execution_origin": "deterministic_tool_executor",
            "receipt_path": receipt.relative_to(task_root).as_posix(),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        },
        idempotency_key="succeed-blueprint",
    )
    staging = task_root / "artifacts" / "staging" / "story-blueprint.yml"
    staging.parent.mkdir(parents=True)
    staging.write_text("story_blueprint: fixture\n", encoding="utf-8")
    projection = runtime.record_artifact_version(
        task_id,
        artifact_id="story_blueprint",
        version_id="story-blueprint-v1",
        attempt_id=attempt_id,
        path=staging,
        media_type="application/yaml",
        idempotency_key="record-blueprint-version",
    )
    artifact = projection["artifacts"]["story-blueprint-v1"]
    return "story-blueprint-v1", artifact["sha256"]


def _create_visual_runtime_task(
    root: Path,
    *,
    task_id: str,
    source: Path,
    blueprint_version_id: str,
    blueprint_sha256: str,
) -> TaskRuntime:
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    runtime.create_task(
        task_id=task_id,
        title="Compile ShanHe visual continuity cards",
        user_goal="Create candidate-only visual continuity prompts before prose.",
        protocol_ref="narrative.visual.v1",
        input_profile={
            "kind": "visual_detail_build",
            "scope": "longform",
            "target_count": 4,
            "canon_impact": "none",
            "risk_flags": [],
            "project": "ShanHeYouJia",
            "source_blueprint_task_id": "task-shanhe-blueprint-006",
            "source_blueprint_artifact_version_id": blueprint_version_id,
            "source_blueprint_artifact_sha256": blueprint_sha256,
            "source_visual_detail_spec": source.relative_to(root).as_posix(),
            "source_visual_detail_spec_sha256": hashlib.sha256(
                source.read_bytes()
            ).hexdigest(),
        },
        idempotency_key=f"create-{task_id}",
    )
    return runtime


def _materialize_visual_pack(
    root: Path,
    *,
    task_id: str = "task-shanhe-visual-batch",
) -> tuple[dict, Path]:
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True, exist_ok=True)
    source = project_root / "runtime" / f"{task_id}-spec.yml"
    source.parent.mkdir(parents=True, exist_ok=True)
    spec = _spec()
    spec["task_id"] = task_id
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    runtime = _create_visual_runtime_task(
        root,
        task_id=task_id,
        source=source,
        blueprint_version_id=blueprint_version_id,
        blueprint_sha256=blueprint_sha256,
    )
    result = ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
        task_id,
        work_item_id="visual_card_projector",
        messages=[],
        source_paths=[],
        external_context_request={},
        idempotency_key=f"materialize-{task_id}",
    )
    version = next(
        artifact
        for artifact in result["projection"]["artifacts"].values()
        if artifact["artifact_id"] == "visual_detail_card_pack"
    )
    pack_path = runtime._task_dir(task_id) / version["path"]
    return yaml.safe_load(pack_path.read_text(encoding="utf-8")), pack_path


def test_public_managed_imagegen_ingest_records_real_image_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "AgentLab"
    pack, pack_path = _materialize_visual_pack(
        root,
        task_id="task-shanhe-visual-public-ingest",
    )
    authority = tmp_path / "managed-imagegen-authority"
    authority.mkdir()
    private_key, public_key = _test_signing_key(authority, "imagegen")
    (root / "config" / "local_private_topology.yml").write_text(
        yaml.safe_dump(
            {
                "codex_managed_tool_authority": {
                    "public_key_path": str(public_key),
                    "public_key_sha256": hashlib.sha256(
                        public_key.read_bytes()
                    ).hexdigest(),
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    image = tmp_path / "shen-du.png"
    Image.new("RGB", (8, 8), color=(47, 63, 79)).save(image, format="PNG")
    card = next(
        item for item in pack["cards"] if item["card_id"] == "character-shen-du"
    )
    task_id = visual_reference_task_id(pack, "character-shen-du")
    payload = {
        "schema_version": "narrative-visual-managed-imagegen-attestation-payload/v1",
        "action": "attest_codex_managed_imagegen_result",
        "tool": "image_gen.imagegen",
        "project": "ShanHeYouJia",
        "task_id": task_id,
        "attempt_id": "attempt-generation-001",
        "artifact_version_id": "shen-du-reference-v1",
        "card_id": "character-shen-du",
        "prompt_sha256": card["identity_reference"]["prompt_sha256"],
        "asset_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "session_id": "codex-managed-imagegen-session-001",
        "selected_provider": "openai",
        "selected_model_id": "gpt-image-2",
        "tool_result_id": "managed-imagegen-result-001",
    }
    signature = authority / "imagegen-result.sig"
    _sign_test_payload(private_key, signature, payload)
    attestation = tmp_path / "imagegen-attestation.yml"
    attestation.write_text(
        yaml.safe_dump(
            {
                "status": "attested",
                "signed_payload": payload,
                "signature_path": str(signature),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    invalid_signature = bytearray(signature.read_bytes())
    invalid_signature[0] ^= 1
    signature.write_bytes(invalid_signature)
    with pytest.raises(ValueError, match="signature verification failed"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    assert not (
        root
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / task_id
        / "events.jsonl"
    ).exists()
    _sign_test_payload(private_key, signature, payload)

    fake_image = tmp_path / "fake-prefix.png"
    fake_image.write_bytes(b"\x89PNG\r\n\x1a\nnot-an-image")
    with pytest.raises(ValueError, match="not a decodable image"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=fake_image,
            attestation_path=attestation,
        )
    assert not (
        root
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / task_id
        / "events.jsonl"
    ).exists()

    profiles_path = root / "config" / "agent_model_profiles.yml"
    profiles_text = profiles_path.read_text(encoding="utf-8")
    profiles = yaml.safe_load(profiles_text)
    default_mode = profiles["default_mode"]
    default_tier = profiles["tier_policy"]["default_tier"]
    profiles["modes"][default_mode]["tiers"][default_tier]["artifact_producer"][
        "invocation_contract"
    ] = ""
    profiles_path.write_text(
        yaml.safe_dump(profiles, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no complete"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    assert not (
        root
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / task_id
        / "events.jsonl"
    ).exists()
    profiles_path.write_text(profiles_text, encoding="utf-8")

    reference_task_root = (
        root / "projects" / "ShanHeYouJia" / "runtime" / "tasks" / task_id
    )
    escaped_task = tmp_path / "escaped-reference-task"
    escaped_task.mkdir()
    reference_task_root.parent.mkdir(parents=True, exist_ok=True)
    reference_task_root.symlink_to(escaped_task, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestry contains a symlink"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    assert list(escaped_task.iterdir()) == []
    reference_task_root.unlink()

    real_open_task_subdirectory = visual_reference_runtime._open_task_subdirectory
    parked_task = tmp_path / "parked-reference-task"

    def swap_after_open(agentlab_root: Path, task_root: Path, parts: tuple[str, ...]):
        descriptor = real_open_task_subdirectory(agentlab_root, task_root, parts)
        if not parts and not parked_task.exists():
            task_root.rename(parked_task)
            task_root.symlink_to(escaped_task, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(
        visual_reference_runtime,
        "_open_task_subdirectory",
        swap_after_open,
    )
    with pytest.raises(InvalidTransition, match="Task inode moved or was replaced"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    assert list(escaped_task.iterdir()) == []
    reference_task_root.unlink()
    parked_task.rename(reference_task_root)
    monkeypatch.setattr(
        visual_reference_runtime,
        "_open_task_subdirectory",
        real_open_task_subdirectory,
    )

    runtime_root = reference_task_root.parent.parent
    parked_runtime = tmp_path / "parked-runtime-ancestor"
    escaped_runtime = tmp_path / "escaped-runtime-ancestor"
    escaped_runtime.mkdir()

    def swap_runtime_ancestor_after_open(
        agentlab_root: Path,
        task_root: Path,
        parts: tuple[str, ...],
    ):
        descriptor = real_open_task_subdirectory(agentlab_root, task_root, parts)
        if not parts and not parked_runtime.exists():
            runtime_root.rename(parked_runtime)
            runtime_root.symlink_to(escaped_runtime, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(
        visual_reference_runtime,
        "_open_task_subdirectory",
        swap_runtime_ancestor_after_open,
    )
    with pytest.raises(InvalidTransition, match="Task inode moved or was replaced"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    assert list(escaped_runtime.iterdir()) == []
    runtime_root.unlink()
    parked_runtime.rename(runtime_root)
    monkeypatch.setattr(
        visual_reference_runtime,
        "_open_task_subdirectory",
        real_open_task_subdirectory,
    )

    escaped_after_check = tmp_path / "escaped-after-task-check"
    escaped_after_check.mkdir()
    parked_after_check = tmp_path / "parked-after-task-check"
    real_append_ledger_line = (
        visual_reference_runtime._AnchoredTaskRuntime._append_ledger_line
    )
    swapped_after_check = False

    def swap_immediately_before_ledger_open(runtime, task_id, line):
        nonlocal swapped_after_check
        if not swapped_after_check:
            swapped_after_check = True
            reference_task_root.rename(parked_after_check)
            reference_task_root.symlink_to(
                escaped_after_check,
                target_is_directory=True,
            )
        return real_append_ledger_line(runtime, task_id, line)

    monkeypatch.setattr(
        visual_reference_runtime._AnchoredTaskRuntime,
        "_append_ledger_line",
        swap_immediately_before_ledger_open,
    )
    with pytest.raises(InvalidTransition, match="Task inode moved or was replaced"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    assert list(escaped_after_check.iterdir()) == []
    assert list(parked_after_check.iterdir()) == []
    reference_task_root.unlink()
    parked_after_check.rename(reference_task_root)
    monkeypatch.setattr(
        visual_reference_runtime._AnchoredTaskRuntime,
        "_append_ledger_line",
        real_append_ledger_line,
    )

    escaped_artifacts = tmp_path / "escaped-reference-artifacts"
    escaped_artifacts.mkdir()
    reference_task_root.mkdir(parents=True, exist_ok=True)
    (reference_task_root / "artifacts").symlink_to(
        escaped_artifacts,
        target_is_directory=True,
    )
    with pytest.raises(ValueError, match="ancestry contains a symlink"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    assert list(escaped_artifacts.iterdir()) == []
    (reference_task_root / "artifacts").unlink()

    real_record_protocol_gate = TaskRuntime.record_protocol_gate

    def interrupt_after_artifact(runtime: TaskRuntime, *args, **kwargs):
        if kwargs.get("gate_id") == "managed_imagegen_attested":
            raise RuntimeError("injected interruption after ArtifactVersion")
        return real_record_protocol_gate(runtime, *args, **kwargs)

    monkeypatch.setattr(TaskRuntime, "record_protocol_gate", interrupt_after_artifact)
    with pytest.raises(RuntimeError, match="injected interruption"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )
    interrupted = TaskRuntime(root, project="ShanHeYouJia").load_task(task_id)
    assert "shen-du-reference-v1" in interrupted["artifacts"]
    assert "managed_imagegen_attested" not in interrupted["protocol_gates"]
    assert interrupted["work_items"]["generation"]["status"] != "accepted"
    monkeypatch.setattr(TaskRuntime, "record_protocol_gate", real_record_protocol_gate)

    result = ingest_managed_visual_identity_reference(
        root,
        pack=pack,
        pack_path=pack_path,
        card_id="character-shen-du",
        image_path=image,
        attestation_path=attestation,
    )

    assert result["status"] == "ingested"
    assert result["artifact"]["artifact_id"] == "visual_identity_reference"
    assert result["artifact"]["media_type"] == "image/png"
    assert result["artifact"]["sha256"] == payload["asset_sha256"]
    assert result["managed_imagegen_gate"]["status"] == "pass"
    assert result["projection"]["work_items"]["generation"]["status"] == "accepted"
    assert (
        result["projection"]["attempts"]["attempt-generation-001"]["outcome"][
            "execution_origin"
        ]
        == "role_attempt_executor"
    )
    repeated = ingest_managed_visual_identity_reference(
        root,
        pack=pack,
        pack_path=pack_path,
        card_id="character-shen-du",
        image_path=image,
        attestation_path=attestation,
    )
    assert repeated["status"] == "already_ingested"
    with pytest.raises(
        InvalidTransition,
        match="governed managed-imagegen ingest adapter",
    ):
        ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
            task_id,
            work_item_id="generation",
            messages=[],
            source_paths=[],
            external_context_request={},
            idempotency_key="reject-text-generation-path",
        )
    immutable_image = (
        root
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / task_id
        / result["artifact"]["path"]
    )
    immutable_image.write_bytes(b"tampered-image")
    with pytest.raises(InvalidTransition, match="ArtifactVersion drifted"):
        ingest_managed_visual_identity_reference(
            root,
            pack=pack,
            pack_path=pack_path,
            card_id="character-shen-du",
            image_path=image,
            attestation_path=attestation,
        )


def test_visual_card_protocol_runs_as_real_deterministic_attempt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "visual-detail-spec.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-001"
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    runtime.create_task(
        task_id="task-shanhe-visual-001",
        title="Compile ShanHe visual continuity cards",
        user_goal="Create candidate-only visual continuity prompts before prose.",
        protocol_ref="narrative.visual.v1",
        input_profile={
            "kind": "visual_detail_build",
            "scope": "longform",
            "target_count": 4,
            "canon_impact": "none",
            "risk_flags": [],
            "project": "ShanHeYouJia",
            "source_blueprint_task_id": "task-shanhe-blueprint-006",
            "source_blueprint_artifact_version_id": blueprint_version_id,
            "source_blueprint_artifact_sha256": blueprint_sha256,
            "source_visual_detail_spec": source.relative_to(root).as_posix(),
            "source_visual_detail_spec_sha256": digest,
        },
        idempotency_key="create-visual-task",
    )

    result = ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
        "task-shanhe-visual-001",
        work_item_id="visual_card_projector",
        messages=[],
        source_paths=[],
        external_context_request={},
        idempotency_key="execute-visual-projector",
    )

    assert result["status"] == "waiting_review"
    projection = result["projection"]
    attempt = projection["attempts"]["attempt-visual_card_projector-001"]
    assert attempt["status"] == "succeeded"
    assert attempt["output_validation"]["status"] == "pass"
    version = next(
        item
        for item in projection["artifacts"].values()
        if item["artifact_id"] == "visual_detail_card_pack"
    )
    output_pack = yaml.safe_load(
        (
            root
            / "projects"
            / "ShanHeYouJia"
            / "runtime"
            / "tasks"
            / "task-shanhe-visual-001"
            / version["path"]
        ).read_text(encoding="utf-8")
    )
    assert validate_visual_detail_card_pack(output_pack)["status"] == "pass"
    receipt = yaml.safe_load(
        (
            root
            / "projects"
            / "ShanHeYouJia"
            / "runtime"
            / "tasks"
            / "task-shanhe-visual-001"
            / "attempt_logs"
            / "attempt-visual_card_projector-001"
            / "deterministic_execution_receipt.yml"
        ).read_text(encoding="utf-8")
    )
    assert receipt["declared_sources"][0] == {
        "path": source.relative_to(root).as_posix(),
        "sha256": digest,
    }
    assert receipt["declared_sources"][1]["sha256"] == blueprint_sha256
    assert [item["sha256"] for item in receipt["sealed_sources"]] == [
        digest,
        blueprint_sha256,
    ]
    assert "visual_detail_cards_hash_verified" in projection["protocol_gates"]


def test_prose_prerequisite_rejects_superseded_visual_pack(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "visual-detail-spec.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-prose-gate"
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    runtime = _create_visual_runtime_task(
        root,
        task_id="task-shanhe-visual-prose-gate",
        source=source,
        blueprint_version_id=blueprint_version_id,
        blueprint_sha256=blueprint_sha256,
    )
    runner = ProductionProtocolRunner(root, project="ShanHeYouJia")
    result = runner.execute_node(
        "task-shanhe-visual-prose-gate",
        work_item_id="visual_card_projector",
        messages=[],
        source_paths=[],
        external_context_request={},
        idempotency_key="compile-prose-gate-visual-pack",
    )
    version_id, artifact = next(
        (version_id, artifact)
        for version_id, artifact in result["projection"]["artifacts"].items()
        if artifact["artifact_id"] == "visual_detail_card_pack"
    )
    artifact_path = (
        runtime._task_dir("task-shanhe-visual-prose-gate") / artifact["path"]
    )
    facts = {
        "source_visual_task_id": "task-shanhe-visual-prose-gate",
        "source_visual_pack_version_id": version_id,
        "source_visual_detail_pack": artifact_path.relative_to(root).as_posix(),
        "source_visual_detail_pack_sha256": artifact["sha256"],
    }
    runner._validate_visual_prose_prerequisite(facts)
    original_source = source.read_bytes()
    source.write_text("schema_version: drifted\n", encoding="utf-8")
    with pytest.raises(InvalidTransition, match="provenance is invalid"):
        runner._validate_visual_prose_prerequisite(facts)
    source.write_bytes(original_source)
    runtime.change_artifact_disposition(
        "task-shanhe-visual-prose-gate",
        version_id=version_id,
        disposition="rejected_pre_v3",
        reason_code="visual_pack_rejected",
        feedback_digest="b" * 64,
        idempotency_key="reject-visual-pack",
    )

    with pytest.raises(InvalidTransition, match="exact hash-verified visual"):
        runner._validate_visual_prose_prerequisite(facts)


def test_visual_card_protocol_rejects_source_changed_after_task_creation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "visual-detail-spec.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-002"
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    runtime.create_task(
        task_id="task-shanhe-visual-002",
        title="Compile ShanHe visual continuity cards",
        user_goal="Reject drift after source sealing.",
        protocol_ref="narrative.visual.v1",
        input_profile={
            "kind": "visual_detail_build",
            "scope": "longform",
            "target_count": 4,
            "canon_impact": "none",
            "risk_flags": [],
            "project": "ShanHeYouJia",
            "source_blueprint_task_id": "task-shanhe-blueprint-006",
            "source_blueprint_artifact_version_id": blueprint_version_id,
            "source_blueprint_artifact_sha256": blueprint_sha256,
            "source_visual_detail_spec": source.relative_to(root).as_posix(),
            "source_visual_detail_spec_sha256": digest,
        },
        idempotency_key="create-visual-task-drift",
    )
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8"
    )

    with pytest.raises(InvalidTransition, match="source fact hash mismatch"):
        ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
            "task-shanhe-visual-002",
            work_item_id="visual_card_projector",
            messages=[],
            source_paths=[],
            external_context_request={},
            idempotency_key="execute-visual-projector-drift",
        )


def test_visual_protocol_rejects_direct_runtime_symlink_source(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    real_source = project_root / "runtime" / "real-visual.yml"
    real_source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-003"
    real_source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    symlink_source = project_root / "runtime" / "linked-visual.yml"
    symlink_source.symlink_to(real_source)
    digest = hashlib.sha256(real_source.read_bytes()).hexdigest()
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    runtime.create_task(
        task_id="task-shanhe-visual-003",
        title="Reject symlinked source",
        user_goal="Reject Runtime API symlink bypass.",
        protocol_ref="narrative.visual.v1",
        input_profile={
            "kind": "visual_detail_build",
            "scope": "longform",
            "target_count": 4,
            "canon_impact": "none",
            "risk_flags": [],
            "project": "ShanHeYouJia",
            "source_blueprint_task_id": "task-shanhe-blueprint-006",
            "source_blueprint_artifact_version_id": blueprint_version_id,
            "source_blueprint_artifact_sha256": blueprint_sha256,
            "source_visual_detail_spec": symlink_source.relative_to(root).as_posix(),
            "source_visual_detail_spec_sha256": digest,
        },
        idempotency_key="create-visual-symlink",
    )

    with pytest.raises(InvalidTransition, match="source fact is unavailable"):
        ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
            "task-shanhe-visual-003",
            work_item_id="visual_card_projector",
            messages=[],
            source_paths=[],
            external_context_request={},
            idempotency_key="execute-visual-symlink",
        )
    projection = runtime.load_task("task-shanhe-visual-003")
    assert projection["attempts"] == {}
    assert projection["task"]["status"] == "created"


def test_visual_protocol_rejects_missing_blueprint_artifact_before_attempt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "visual-without-blueprint.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-005"
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    runtime = _create_visual_runtime_task(
        root,
        task_id="task-shanhe-visual-005",
        source=source,
        blueprint_version_id="missing-blueprint-v1",
        blueprint_sha256="b" * 64,
    )

    with pytest.raises(InvalidTransition, match="source blueprint Task is unavailable"):
        ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
            "task-shanhe-visual-005",
            work_item_id="visual_card_projector",
            messages=[],
            source_paths=[],
            external_context_request={},
            idempotency_key="execute-missing-blueprint",
        )
    assert runtime.load_task("task-shanhe-visual-005")["attempts"] == {}


def test_visual_preflight_snapshot_closes_post_validation_source_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "visual-snapshot.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-006"
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    declared_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    _create_visual_runtime_task(
        root,
        task_id="task-shanhe-visual-006",
        source=source,
        blueprint_version_id=blueprint_version_id,
        blueprint_sha256=blueprint_sha256,
    )
    runner = ProductionProtocolRunner(root, project="ShanHeYouJia")
    original_preflight = runner._deterministic_preflight

    def preflight_then_swap(*args, **kwargs):
        result = original_preflight(*args, **kwargs)
        source.write_text(
            source.read_text(encoding="utf-8") + "\n# swapped\n", encoding="utf-8"
        )
        return result

    monkeypatch.setattr(runner, "_deterministic_preflight", preflight_then_swap)
    result = runner.execute_node(
        "task-shanhe-visual-006",
        work_item_id="visual_card_projector",
        messages=[],
        source_paths=[],
        external_context_request={},
        idempotency_key="execute-snapshot-swap",
    )

    assert result["status"] == "waiting_review"
    receipt = yaml.safe_load(
        (
            runner.runtime._task_dir("task-shanhe-visual-006")
            / "attempt_logs"
            / result["attempt_id"]
            / "deterministic_execution_receipt.yml"
        ).read_text(encoding="utf-8")
    )
    assert receipt["declared_sources"][0]["sha256"] == declared_sha256
    snapshot = root / receipt["sealed_sources"][0]["path"]
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == declared_sha256
    assert hashlib.sha256(source.read_bytes()).hexdigest() != declared_sha256


def test_visual_preflight_rejects_symlinked_snapshot_directory_before_attempt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "visual-detail-spec.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-snapshot-link"
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    runtime = _create_visual_runtime_task(
        root,
        task_id="task-shanhe-visual-snapshot-link",
        source=source,
        blueprint_version_id=blueprint_version_id,
        blueprint_sha256=blueprint_sha256,
    )
    task_root = runtime._task_dir("task-shanhe-visual-snapshot-link")
    inputs = task_root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    escaped = project_root / "runtime" / "escaped-snapshots"
    escaped.mkdir()
    (inputs / "snapshots").symlink_to(escaped, target_is_directory=True)

    with pytest.raises(InvalidTransition, match="snapshot path contains a symlink"):
        ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
            "task-shanhe-visual-snapshot-link",
            work_item_id="visual_card_projector",
            messages=[],
            source_paths=[],
            external_context_request={},
            idempotency_key="reject-snapshot-link",
        )

    projection = runtime.load_task("task-shanhe-visual-snapshot-link")
    assert projection["task"]["status"] == "created"
    assert projection["attempts"] == {}
    assert list(escaped.iterdir()) == []


def test_visual_protocol_rejects_non_blueprint_source_task(
    tmp_path: Path,
) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "visual-detail-spec.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-legacy-source"
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(
        root,
        protocol_ref=None,
    )
    runtime = _create_visual_runtime_task(
        root,
        task_id="task-shanhe-visual-legacy-source",
        source=source,
        blueprint_version_id=blueprint_version_id,
        blueprint_sha256=blueprint_sha256,
    )

    with pytest.raises(
        InvalidTransition,
        match="source blueprint ArtifactVersion does not match",
    ):
        ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
            "task-shanhe-visual-legacy-source",
            work_item_id="visual_card_projector",
            messages=[],
            source_paths=[],
            external_context_request={},
            idempotency_key="reject-legacy-blueprint-source",
        )

    projection = runtime.load_task("task-shanhe-visual-legacy-source")
    assert projection["task"]["status"] == "created"
    assert projection["attempts"] == {}


def test_invalid_visual_spec_never_starts_an_attempt(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    _copy_protocol_config(root)
    project_root = root / "projects" / "ShanHeYouJia"
    project_root.mkdir(parents=True)
    source = project_root / "runtime" / "invalid-visual.yml"
    source.parent.mkdir(parents=True)
    spec = _spec()
    spec["task_id"] = "task-shanhe-visual-004"
    spec["cards"] = []
    source.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    blueprint_version_id, blueprint_sha256 = _record_blueprint_artifact(root)
    runtime = TaskRuntime(root, project="ShanHeYouJia")
    runtime.create_task(
        task_id="task-shanhe-visual-004",
        title="Reject invalid visual spec",
        user_goal="Do not start an Attempt for invalid deterministic input.",
        protocol_ref="narrative.visual.v1",
        input_profile={
            "kind": "visual_detail_build",
            "scope": "longform",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
            "project": "ShanHeYouJia",
            "source_blueprint_task_id": "task-shanhe-blueprint-006",
            "source_blueprint_artifact_version_id": blueprint_version_id,
            "source_blueprint_artifact_sha256": blueprint_sha256,
            "source_visual_detail_spec": source.relative_to(root).as_posix(),
            "source_visual_detail_spec_sha256": digest,
        },
        idempotency_key="create-invalid-visual",
    )

    with pytest.raises(InvalidTransition, match="visual detail spec is invalid"):
        ProductionProtocolRunner(root, project="ShanHeYouJia").execute_node(
            "task-shanhe-visual-004",
            work_item_id="visual_card_projector",
            messages=[],
            source_paths=[],
            external_context_request={},
            idempotency_key="execute-invalid-visual",
        )
    projection = runtime.load_task("task-shanhe-visual-004")
    assert projection["attempts"] == {}
    assert projection["task"]["status"] == "created"


def test_narrative_blueprint_protocol_requires_visual_detail_card_pack() -> None:
    config = yaml.safe_load(
        (ROOT / "config" / "production_packs.yml").read_text(encoding="utf-8")
    )
    blueprint = next(
        item for item in config["packs"] if item["pack_id"] == "narrative_blueprint"
    )
    assert "visual_detail_card_pack.yml" not in blueprint["required_outputs"]
    pack = next(
        item
        for item in config["packs"]
        if item["pack_id"] == "narrative_visual_development"
    )
    assert pack["protocol"]["ref"] == "narrative.visual.v1"
    assert "visual_detail_card_pack.yml" in pack["required_outputs"]
    assert "visual_detail_card_pack" in pack["memory_contract"]
    contract = next(
        item
        for item in pack["protocol"]["artifact_contracts"]
        if item["artifact_type"] == "visual_detail_card_pack"
    )
    assert contract["producer_node"] == "visual_card_projector"
    assert contract["candidate_only"] is True
    assert "pack_sha256" in contract["required_markers"]
    assert "identity_lock_prompt" in contract["required_markers"]
    assert "visual_detail_cards_hash_verified" in pack["quality_gates"]
    chapter = next(
        item for item in config["packs"] if item["pack_id"] == "narrative_longform"
    )
    assert {
        "source_visual_task_id",
        "source_visual_pack_version_id",
        "source_visual_detail_pack",
        "source_visual_detail_pack_sha256",
    }.issubset(chapter["protocol"]["required_facts"])
    routing = yaml.safe_load(
        (ROOT / "config" / "routing_rules.yml").read_text(encoding="utf-8")
    )
    assert "narrative_visual_development" in routing["routes"]


def test_visual_detail_card_cli_commands_are_registered() -> None:
    for command in (
        "compile-visual-cards",
        "validate-visual-cards",
        "compile-visual-generation-batch",
    ):
        result = subprocess.run(
            [str(ROOT / "agentlab.sh"), "narrative", command, "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
