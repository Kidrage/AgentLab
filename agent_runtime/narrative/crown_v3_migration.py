"""Provider-free Crown v3 narrative-state migration helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.narrative.fact_authority import (
    assert_fact_authority_evidence,
    assert_fact_authority_projection,
    load_fact_authority,
    verify_registered_fact_authority,
)


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return value


def _source(path: Path, *, project_root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(project_root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _records_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    raw_records = document.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("canonical document records must be a list")
    for raw in raw_records:
        if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
            raise ValueError("canonical records require a non-empty id")
        record = dict(raw)
        record_id = str(record.pop("id"))
        if record_id in records:
            raise ValueError(f"duplicate canonical record id: {record_id}")
        record.pop("kind", None)
        records[record_id] = record
    return records


def build_crown_bootstrap_manifest(project_root: Path) -> dict[str, Any]:
    """Compile current formal roots into a hash-bound v3 bootstrap manifest."""

    project_root = Path(project_root).resolve(strict=True)
    canonical = project_root / "production" / "canonical"
    paths = {
        "scale": project_root / "production" / "series_scale_decision.yml",
        "fact_authority": project_root / "production" / "fact_authority.yml",
        "part_arcs": canonical / "part_arcs.yml",
        "characters": canonical / "characters.yml",
        "relationships": canonical / "relationships.yml",
        "foreshadowing": canonical / "foreshadowing.yml",
        "worldlines": canonical / "worldlines.yml",
        "fact_distillation": project_root / "project_brain" / "fact_distillation.yml",
    }
    for label, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Crown v3 bootstrap source missing: {label}:{path}")

    scale = _read_yaml(paths["scale"])
    if scale.get("planned_total_chapters") != 1980:
        raise ValueError("Crown v3 bootstrap requires the approved 1980-chapter scale")
    characters = _records_by_id(_read_yaml(paths["characters"]))
    fact_authority, fact_authority_sha256 = load_fact_authority(
        paths["fact_authority"],
        project="Crown_of_Ash",
    )
    verify_registered_fact_authority(
        project_root,
        fact_authority,
        fact_authority_sha256,
    )
    assert_fact_authority_evidence(
        project_root,
        fact_authority,
        source_sha256=fact_authority_sha256,
    )
    assert_fact_authority_projection(
        {"characters": characters},
        fact_authority,
    )
    lia = characters.get("char_lia") or {}
    if lia.get("age") != 18 or lia.get("age_class") != "adult":
        raise ValueError("Crown v3 bootstrap requires Lia's current adult age lock")

    parts = []
    for index, item in enumerate(scale.get("parts") or [], start=1):
        if not isinstance(item, dict):
            continue
        chapter_range = list(item.get("chapter_range") or [])
        if not chapter_range and item.get("chapter_start") is not None:
            chapter_range = [item.get("chapter_start"), item.get("chapter_end")]
        parts.append(
            {
                "part_id": str(
                    item.get("part_id")
                    or item.get("id")
                    or item.get("part")
                    or f"part-{index}"
                ),
                "chapter_range": chapter_range,
                "planned_chapters": item.get("planned_chapters"),
            }
        )
    expected_ranges = [[1, 650], [651, 1310], [1311, 1980]]
    if [part["chapter_range"] for part in parts] != expected_ranges:
        raise ValueError("Crown v3 bootstrap volume ranges do not match 1980 plan")

    return {
        "schema_version": "narrative-bootstrap/v1",
        "project": "Crown_of_Ash",
        "fact_authority": {
            "authority_id": fact_authority["authority_id"],
            "revision": fact_authority["revision"],
            "source_path": paths["fact_authority"].relative_to(project_root).as_posix(),
            "source_sha256": fact_authority_sha256,
        },
        "precedence": [
            "single_active_fact_authority",
            "agentlab_approved_scale_decision",
            "formal_canonical_projection",
            "legacy_material_as_provenance_only",
        ],
        "sources": [
            _source(path, project_root=project_root) for path in paths.values()
        ],
        "base_state": {
            "series": {
                "planned_total_chapters": 1980,
                "parts": parts,
                "macro_arc_count": 45,
                "planning_window_max_chapters": 10,
                "promotion_policy": "single_atomic_after_full_audit_and_user_acceptance",
                "external_model_authorization": "required_before_metadata_compilation",
                "prose_generation_allowed": False,
                "part_arcs_projection": _read_yaml(paths["part_arcs"]),
            },
            "characters": characters,
            "relationships": _records_by_id(_read_yaml(paths["relationships"])),
            "foreshadowing": _records_by_id(_read_yaml(paths["foreshadowing"])),
            "world_axes": _records_by_id(_read_yaml(paths["worldlines"])),
            "fact_authorities": {
                fact_authority["authority_id"]: {
                    "revision": fact_authority["revision"],
                    "source_path": paths["fact_authority"]
                    .relative_to(project_root)
                    .as_posix(),
                    "source_sha256": fact_authority_sha256,
                }
            },
            "chapters": {},
            "style_memory": [],
        },
    }


def crown_feedback_memory_records(
    *, artifact_sha256: str, feedback_sha256: str
) -> list[dict[str, Any]]:
    """Normalize user review into prose-free, traceable editorial memory."""

    source = f"feedback:{feedback_sha256}"
    common = {
        "schema_version": "editorial-memory-event/v1",
        "project": "Crown_of_Ash",
        "source_artifact_sha256": artifact_sha256,
        "source_disposition": "rejected_pre_v3",
    }
    return [
        {
            **common,
            "rule_id": "crown-v3-dialogue-quotes",
            "memory_kind": "mechanical_policy",
            "summary": "明确直接对白使用中文双引号；机械错误只做局部返工，不自动补标点。",
            "source_locator": f"{source}:chinese_dialogue_quotes_missing",
        },
        {
            **common,
            "rule_id": "crown-v3-local-quote-repair-scope",
            "memory_kind": "mechanical_policy",
            "summary": "局部对白修复只允许增删替换引号；去除引号后正文逐字不变，并绑定原报告与修复回执。",
            "source_locator": f"{source}:quote_only_local_repair_boundary",
        },
        {
            **common,
            "rule_id": "crown-v3-protagonist-drive",
            "memory_kind": "anti_pattern",
            "summary": "避免主角只响应外部事件；每章声明自发行动、失败代价和反事实行动。",
            "source_locator": f"{source}:protagonist_active_desire_missing",
        },
        {
            **common,
            "rule_id": "crown-v3-supporting-autonomy",
            "memory_kind": "anti_pattern",
            "summary": "重要配角不能只负责递送信息，必须持有私有目标、计划和幕后行动。",
            "source_locator": f"{source}:supporting_actor_autonomy_missing",
        },
        {
            **common,
            "rule_id": "crown-v3-hook-tiers",
            "memory_kind": "anti_pattern",
            "summary": "系列与卷首结尾必须形成不可回避的压力、个人利害和下一行动。",
            "source_locator": f"{source}:series_open_hook_underpowered",
        },
        {
            **common,
            "rule_id": "crown-v3-rhetorical-fatigue",
            "memory_kind": "anti_pattern",
            "summary": "限制不是而是等对照模板族的局部聚集和千字密度。",
            "source_locator": f"{source}:contrast_template_fatigue",
        },
        {
            **common,
            "rule_id": "crown-v3-strengths-to-preserve",
            "memory_kind": "editorial_guidance",
            "summary": "保留异常对社会生活的实际影响、职业化认知和生存经济约束，不复制拒稿措辞。",
            "source_locator": f"{source}:strengths_to_preserve_as_abstract_guidance",
        },
    ]


__all__ = ["build_crown_bootstrap_manifest", "crown_feedback_memory_records"]
