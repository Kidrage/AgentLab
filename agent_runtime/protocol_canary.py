"""Deterministic recovery canaries for the shared production-protocol kernel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.production_protocols import ProductionProtocolRunner
from agent_runtime.task_runtime_v2 import TaskRuntime


_SHARED_CONFIGS = (
    "production_packs.yml",
    "task_input_tiers.yml",
    "narrative_author_team.yml",
    "agent_registry.yml",
    "agent_model_profiles.yml",
    "production_role_profiles.yml",
)

_CANARIES: tuple[dict[str, Any], ...] = (
    {
        "name": "NovelCanary",
        "protocol_ref": "narrative.chapter.v1",
        "title": "Write one isolated lighthouse-memory chapter",
        "user_goal": "Produce a reviewed chapter candidate without touching an existing story world.",
        "facts": {
            "kind": "prose_build",
            "scope": "single_chapter",
            "target_count": 1,
            "canon_impact": "none",
            "chapter": 1,
            "risk_flags": [],
            "source_story_bible": "examples/novel_canary/story_bible.yml",
        },
    },
    {
        "name": "CodeCanary",
        "protocol_ref": "code.large.v1",
        "title": "Build one isolated fixture patch",
        "user_goal": "Produce an independently validated candidate patch for a fixture repository.",
        "facts": {
            "kind": "code_build",
            "scope": "large",
            "target_count": 6,
            "canon_impact": "none",
            "risk_flags": [],
            "repository": "fixture-repository",
        },
    },
)


def _install_canary_authority(source_root: Path, state_root: Path) -> None:
    config_root = state_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    for name in _SHARED_CONFIGS:
        source = source_root / "config" / name
        if not source.is_file():
            raise FileNotFoundError(f"canary authority is missing: {source}")
        target = config_root / name
        if target.exists() and target.read_bytes() == source.read_bytes():
            continue
        shutil.copy2(source, target)

    authority_root = state_root.parent / (
        ".agentlab-canary-approval-"
        + hashlib.sha256(str(state_root).encode("utf-8")).hexdigest()[:12]
    )
    authority_root.mkdir(parents=True, exist_ok=True)
    private_key = authority_root / "private.pem"
    public_key = authority_root / "public.pem"
    if not private_key.is_file():
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
    if not public_key.is_file():
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
    atomic_write_yaml(
        config_root / "local_private_topology.yml",
        {
            "user_approval_authority": {
                "public_key_path": str(public_key.resolve()),
                "public_key_sha256": hashlib.sha256(
                    public_key.read_bytes()
                ).hexdigest(),
            },
            "protocol_canary_private_key_path": str(private_key.resolve()),
        },
    )


def _sign_canary_approval(
    state_root: Path,
    runtime: TaskRuntime,
    *,
    task_id: str,
    gate_id: str,
    actor: str,
    subjects: dict[str, str],
    evidence_sha256: str,
) -> tuple[Path, Path]:
    config = yaml.safe_load(
        (state_root / "config" / "local_private_topology.yml").read_text(
            encoding="utf-8"
        )
    )
    private_key = Path(config["protocol_canary_private_key_path"])
    document = {
        "schema_version": "protocol-human-approval/v1",
        "task_id": task_id,
        "gate_id": gate_id,
        "actor": actor,
        "decision": "approved",
        "subject_artifacts": subjects,
        "evidence_sha256": evidence_sha256,
    }
    approval_root = runtime._task_dir(task_id) / "approvals"
    approval_root.mkdir(parents=True, exist_ok=True)
    receipt_path = approval_root / f"{gate_id}.yml"
    atomic_write_yaml(receipt_path, document)
    signature_root = private_key.parent / "signatures"
    signature_root.mkdir(parents=True, exist_ok=True)
    signature_path = signature_root / f"{runtime.project}-{task_id}-{gate_id}.sig"
    signed_bytes = (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    subprocess.run(
        [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(signature_path),
        ],
        input=signed_bytes,
        check=True,
        capture_output=True,
    )
    return receipt_path, signature_path


def _prepare_visual_canary_prerequisite(
    state_root: Path,
    *,
    project: str,
    iteration: int,
) -> dict[str, str]:
    """Create a real hash-gated visual ArtifactVersion for the novel canary."""

    runtime = TaskRuntime(state_root, project=project)
    blueprint_task_id = f"task_visual_blueprint_source_{iteration:02d}"
    runtime.create_task(
        task_id=blueprint_task_id,
        title="Canary blueprint source",
        user_goal="Provide one exact story blueprint for visual compilation.",
        protocol_ref="narrative.blueprint.v1",
        input_profile={
            "kind": "blueprint_build",
            "scope": "longform",
            "target_count": 1,
            "canon_impact": "new_project",
            "risk_flags": [],
            "project": project,
            "source_creative_brief": "fixture/creative-brief.yml",
            "source_creative_brief_sha256": "f" * 64,
        },
        idempotency_key=f"create-{blueprint_task_id}",
    )
    runtime.create_work_item(
        blueprint_task_id,
        job_id="job-main",
        work_item_id="blueprint-source",
        kind="production",
        title="Blueprint source",
        idempotency_key=f"work-{blueprint_task_id}",
    )
    runtime.transition_task(
        blueprint_task_id,
        status="ready",
        idempotency_key=f"ready-{blueprint_task_id}",
    )
    runtime.transition_task(
        blueprint_task_id,
        status="running",
        idempotency_key=f"run-{blueprint_task_id}",
    )
    runtime.transition_work_item(
        blueprint_task_id,
        work_item_id="blueprint-source",
        status="running",
        idempotency_key=f"start-{blueprint_task_id}",
    )
    projection = runtime.load_task(blueprint_task_id)
    source_sha256, attempt_id = _execute_canary_attempt(
        state_root,
        runtime,
        projection=projection,
        task_id=blueprint_task_id,
        node_id="blueprint-source",
        binding={
            "node_id": "blueprint-source",
            "role": "Scribe",
            "profile": "state_projector",
            "agent_model_profile": "state_projector",
            "execution_kind": "deterministic_tool",
        },
        canary={
            "name": "VisualBlueprintCanary",
            "protocol_ref": "fixture.visual.blueprint.v1",
        },
        source_paths=[],
    )
    task_root = runtime._task_dir(blueprint_task_id)
    blueprint_staging = task_root / "artifacts" / "staging" / "story-blueprint.yml"
    blueprint_staging.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(
        blueprint_staging,
        {"story_blueprint": "visual canary", "source_output_sha256": source_sha256},
    )
    blueprint_projection = runtime.record_artifact_version(
        blueprint_task_id,
        artifact_id="story_blueprint",
        version_id="story-blueprint-v1",
        attempt_id=attempt_id,
        path=blueprint_staging,
        media_type="application/yaml",
        idempotency_key=f"artifact-{blueprint_task_id}",
    )
    blueprint_artifact = blueprint_projection["artifacts"]["story-blueprint-v1"]

    visual_task_id = f"task_visual_prerequisite_{iteration:02d}"
    spec_path = (
        state_root
        / "projects"
        / project
        / "production"
        / "sources"
        / "visual-detail-spec.yml"
    )
    atomic_write_yaml(
        spec_path,
        {
            "schema_version": "narrative-visual-detail-spec/v3",
            "project": project,
            "task_id": visual_task_id,
            "creative_policy": {
                "work_title": "Protocol Canary",
                "female_modern_nail_art_allowed": False,
            },
            "character_roster": ["character-canary-keeper"],
            "source_refs": [],
            "cards": [
                {
                    "card_id": "character-canary-keeper",
                    "kind": "character",
                    "display_name": "守塔人",
                    "invariant": {
                        "gender": "male",
                        "facial_structure": {
                            "face_shape": "窄长方脸",
                            "forehead": "额头中等",
                            "cheekbones": "颧骨平缓",
                            "jaw": "下颌清楚",
                            "asymmetry": "左颊略高",
                        },
                        "facial_features": {
                            "brows": "平直浓眉",
                            "nose": "鼻梁略弯",
                            "lips": "薄唇",
                            "ears": "耳廓贴近",
                            "distinguishing_marks": "左眉尾浅疤",
                        },
                        "skin": "中性麦色，保留风霜纹理",
                        "eyes": {
                            "shape": "狭长眼",
                            "iris_color": "深褐",
                            "eyelids": "窄内双",
                            "spacing": "一眼宽",
                            "gaze": "平静警觉",
                        },
                        "hair_color": {
                            "base": "墨黑",
                            "undertone": "冷棕",
                            "highlights": "发梢灰褐",
                        },
                        "hairstyle": {
                            "length": "及肩",
                            "texture": "粗直发",
                            "parting": "自然中分",
                            "structure": "低束",
                        },
                        "hair_accessories": {
                            "primary": "旧木簪",
                            "materials": "哑光木",
                            "placement": "低束横穿",
                            "secondary": "隐藏棉绳",
                        },
                        "body": "成年男性，中等身高，清瘦耐劳",
                        "hands": {
                            "proportion": "long_narrow",
                            "joints": "fine_straight",
                            "callus_pattern": "oar_rope",
                            "marks": "none",
                            "dominant_hand": "right",
                            "hand_armor": "none",
                        },
                        "signature_details": "左眉尾浅疤与旧木簪",
                        "negative_constraints": "不得改变脸型、眉疤和身高比例",
                    },
                    "variants": [
                        {
                            "variant_id": "night-watch",
                            "state": "夜间守塔，清醒克制",
                            "wardrobe": "深灰交领衣、旧斗篷与软底靴",
                            "grooming": "面部洁净，鬓角受海风略乱",
                            "hairstyle": {
                                "form": "低束",
                                "front": "自然中分",
                                "back": "发尾及肩",
                                "texture_state": "受潮成束",
                            },
                            "hair_accessories": {
                                "items": "旧木簪与棉绳",
                                "materials": "木与棉",
                                "placement": "低束横穿",
                                "condition": "旧而完整",
                            },
                            "wear_state": "斗篷下摆有盐雾磨痕",
                        }
                    ],
                },
                {
                    "card_id": "prop-canary-lantern",
                    "kind": "prop",
                    "display_name": "守塔灯",
                    "invariant": {
                        "geometry_and_dimensions": "高三十厘米的六角提灯",
                        "materials": "黄铜、玻璃与棉芯",
                        "surface_and_color": "旧金色铜面与透明玻璃",
                        "mechanism": "侧门开启后更换灯芯",
                        "markings": "底座刻一道潮汐纹",
                        "wear_and_damage": "提梁内侧固定磨痕",
                        "handling_scale": "成年人物单手提握",
                        "negative_constraints": "不得改变六角结构、潮汐纹或提梁比例",
                    },
                    "variants": [
                        {
                            "variant_id": "lit",
                            "state": "夜间点亮",
                            "context": "灯塔石阶",
                            "wear_state": "旧而完整",
                        }
                    ],
                },
            ],
        },
    )
    spec_sha256 = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    runtime.create_task(
        task_id=visual_task_id,
        title="Compile visual canary prerequisite",
        user_goal="Prove novel prose cannot bypass visual-card compilation.",
        protocol_ref="narrative.visual.v1",
        input_profile={
            "kind": "visual_detail_build",
            "scope": "longform",
            "target_count": 1,
            "canon_impact": "none",
            "risk_flags": [],
            "project": project,
            "source_blueprint_task_id": blueprint_task_id,
            "source_blueprint_artifact_version_id": "story-blueprint-v1",
            "source_blueprint_artifact_sha256": blueprint_artifact["sha256"],
            "source_visual_detail_spec": spec_path.relative_to(state_root).as_posix(),
            "source_visual_detail_spec_sha256": spec_sha256,
        },
        idempotency_key=f"create-{visual_task_id}",
    )
    result = ProductionProtocolRunner(state_root, project=project).execute_node(
        visual_task_id,
        work_item_id="visual_card_projector",
        messages=[],
        source_paths=[],
        external_context_request={},
        idempotency_key=f"execute-{visual_task_id}",
    )
    visual_versions = [
        (version_id, artifact)
        for version_id, artifact in result["projection"]["artifacts"].items()
        if artifact.get("artifact_id") == "visual_detail_card_pack"
    ]
    if len(visual_versions) != 1:
        raise RuntimeError("visual canary did not produce exactly one card pack")
    version_id, artifact = visual_versions[0]
    artifact_path = runtime._task_dir(visual_task_id) / artifact["path"]
    return {
        "source_visual_task_id": visual_task_id,
        "source_visual_pack_version_id": version_id,
        "source_visual_detail_pack": artifact_path.relative_to(state_root).as_posix(),
        "source_visual_detail_pack_sha256": artifact["sha256"],
    }


def _run_one(
    source_root: Path,
    state_root: Path,
    *,
    canary: dict[str, Any],
    iteration: int,
) -> dict[str, Any]:
    project = f"{canary['name']}{iteration:02d}"
    task_id = f"task_{str(canary['name']).lower()}_{iteration:02d}"
    runtime = TaskRuntime(state_root, project=project)
    production_root = state_root / "projects" / project / "production"
    production_root.mkdir(parents=True, exist_ok=True)
    task_facts = dict(canary["facts"])
    selected_source_paths: list[Path] = []
    resolved_canary = dict(canary)
    if canary["name"] == "NovelCanary":
        story_bible = production_root / "sources" / "story_bible.yml"
        story_bible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            source_root / "examples" / "novel_canary" / "story_bible.yml", story_bible
        )
        task_facts["source_story_bible"] = story_bible.relative_to(
            state_root
        ).as_posix()
        task_facts.update(
            _prepare_visual_canary_prerequisite(
                state_root,
                project=project,
                iteration=iteration,
            )
        )
        resolved_canary["story_bible_path"] = str(story_bible)
    else:
        repository = production_root / "repository"
        repository.mkdir(parents=True, exist_ok=True)
        repository_source = repository / "README.md"
        atomic_write_text(repository_source, "# isolated protocol canary repository\n")
        task_facts["repository"] = repository.relative_to(state_root).as_posix()
        selected_source_paths.append(repository_source)
    resolved_canary["facts"] = task_facts
    runtime.create_task(
        task_id=task_id,
        title=str(canary["title"]),
        user_goal=str(canary["user_goal"]),
        protocol_ref=str(canary["protocol_ref"]),
        input_profile=task_facts,
        idempotency_key=f"create-{task_id}",
    )
    runner = ProductionProtocolRunner(state_root, project=project)
    projection = runner.prepare(task_id)
    runtime.transition_task(task_id, status="ready", idempotency_key=f"ready-{task_id}")
    runtime.transition_task(task_id, status="running", idempotency_key=f"run-{task_id}")

    ordered_nodes = [
        binding["node_id"]
        for binding in projection["task"]["compiled_protocol"]["role_bindings"]
    ]
    recovery_node = ordered_nodes[0]
    runtime.transition_work_item(
        task_id,
        work_item_id=recovery_node,
        status="blocked",
        idempotency_key=f"block-{task_id}-{recovery_node}",
    )

    # Reconstruct from the append-only ledger before resuming the injected failure.
    runtime = TaskRuntime(state_root, project=project)
    runtime.transition_work_item(
        task_id,
        work_item_id=recovery_node,
        status="ready",
        idempotency_key=f"resume-{task_id}-{recovery_node}",
    )
    for node_id in ordered_nodes:
        runtime.transition_work_item(
            task_id,
            work_item_id=node_id,
            status="running",
            idempotency_key=f"start-{task_id}-{node_id}",
        )
        projection = runtime.load_task(task_id)
        binding = next(
            item
            for item in projection["task"]["compiled_protocol"]["role_bindings"]
            if item["node_id"] == node_id
        )
        fact_names = (
            projection["task"]["compiled_protocol"]
            .get("source_fact_bindings", {})
            .get(node_id, [])
        )
        governed_sources = runner._governed_sources(
            task_id,
            projection=projection,
            binding=binding,
            source_paths=(selected_source_paths if fact_names else []),
        )
        output_sha256, attempt_id = _execute_canary_attempt(
            source_root,
            runtime,
            projection=projection,
            task_id=task_id,
            node_id=node_id,
            binding=binding,
            canary=resolved_canary,
            source_paths=governed_sources,
        )
        validation_receipt = (
            runtime._task_dir(task_id)
            / "attempt_logs"
            / attempt_id
            / "artifact_validation_receipt.yml"
        )
        atomic_write_yaml(
            validation_receipt,
            {
                "schema_version": "protocol-artifact-validation/v1",
                "status": "pass",
                "task_id": task_id,
                "attempt_id": attempt_id,
                "output_sha256": output_sha256,
                "issues": [],
            },
        )
        runtime.record_attempt_output_validation(
            task_id,
            attempt_id=attempt_id,
            status="pass",
            validation_receipt_path=validation_receipt,
            issues=[],
            idempotency_key=f"validate-{task_id}-{node_id}",
        )
        contracts = [
            item
            for item in projection["task"]["compiled_protocol"]["artifact_contracts"]
            if item["producer_node"] == node_id
        ]
        for contract in contracts:
            artifact_type = str(contract["artifact_type"])
            source_path = (
                runtime._task_dir(task_id)
                / "artifacts"
                / "staging"
                / f"{node_id}-{artifact_type}.md"
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                source_path,
                _canary_output(source_root, canary=resolved_canary, node_id=node_id),
            )
            runtime.record_artifact_version(
                task_id,
                artifact_id=artifact_type,
                version_id=f"version-{node_id}-{artifact_type}",
                attempt_id=attempt_id,
                path=source_path,
                media_type="text/markdown",
                idempotency_key=f"artifact-{task_id}-{artifact_type}",
            )
        for gate in projection["task"]["compiled_protocol"]["promotion_gate_bindings"]:
            if gate["work_item_id"] != node_id:
                continue
            projection = runtime.load_task(task_id)
            subject_version_ids: list[str] = []
            subjects: dict[str, str] = {}
            for artifact_type in gate["subject_artifact_types"]:
                version_id, artifact = next(
                    (
                        (version_id, artifact)
                        for version_id, artifact in projection["artifacts"].items()
                        if artifact["artifact_id"] == artifact_type
                    ),
                    (None, None),
                )
                if version_id is None or artifact is None:
                    raise RuntimeError(
                        f"canary gate subject artifact is missing: {artifact_type}"
                    )
                subject_version_ids.append(version_id)
                subjects[str(artifact_type)] = str(artifact["sha256"])
            evidence_sha256 = hashlib.sha256(
                json.dumps(
                    subjects,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            actor = f"protocol-canary-{gate['evidence_kind']}-fixture"
            receipt_path: Path | None = None
            signature_path: Path | None = None
            if gate["evidence_kind"] == "human":
                receipt_path, signature_path = _sign_canary_approval(
                    state_root,
                    runtime,
                    task_id=task_id,
                    gate_id=str(gate["gate_id"]),
                    actor=actor,
                    subjects=subjects,
                    evidence_sha256=evidence_sha256,
                )
            runtime.record_protocol_gate(
                task_id,
                gate_id=str(gate["gate_id"]),
                work_item_id=node_id,
                evidence_kind=str(gate["evidence_kind"]),
                evidence_sha256=evidence_sha256,
                attempt_id=attempt_id,
                subject_version_ids=subject_version_ids,
                actor=actor,
                idempotency_key=f"gate-{task_id}-{gate['gate_id']}",
                approval_receipt_path=receipt_path,
                approval_signature_path=signature_path,
            )
        runtime.transition_work_item(
            task_id,
            work_item_id=node_id,
            status="accepted",
            idempotency_key=f"accept-{task_id}-{node_id}",
        )

    projection = runtime.rebuild_task(task_id)
    result_artifact_type = projection["task"]["compiled_protocol"][
        "result_artifact_type"
    ]
    selected_version = next(
        version_id
        for version_id, artifact in projection["artifacts"].items()
        if artifact["artifact_id"] == result_artifact_type
    )
    facts_sha256 = hashlib.sha256(
        json.dumps(
            task_facts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    source_hashes = {"declared-task-facts": facts_sha256}
    if canary["name"] == "NovelCanary":
        story_bible = Path(str(resolved_canary["story_bible_path"]))
        source_hashes["source-story-bible"] = hashlib.sha256(
            story_bible.read_bytes()
        ).hexdigest()
    input_manifest_hash = hashlib.sha256(
        json.dumps(
            source_hashes,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    runtime.bind_evidence(
        task_id,
        binding_id="canary-input-evidence",
        version_id=selected_version,
        input_manifest_hash=input_manifest_hash,
        index_snapshot_id="canary-index",
        source_hashes=source_hashes,
        audit={"status": "pass", "mode": "isolated-fixture"},
        idempotency_key=f"evidence-{task_id}",
    )
    runtime.select_artifact_version(
        task_id,
        version_id=selected_version,
        idempotency_key=f"select-{task_id}",
    )
    runtime.transition_task(
        task_id,
        status="completed",
        idempotency_key=f"complete-{task_id}",
    )
    projection = runtime.rebuild_task(task_id)
    repeated = ProductionProtocolRunner(state_root, project=project).prepare(task_id)
    if repeated != projection:
        raise RuntimeError(
            "canary protocol preparation is not idempotent after recovery"
        )
    doctor = runtime.doctor_project()
    accepted = sum(
        item["status"] == "accepted" for item in projection["work_items"].values()
    )
    return {
        "canary": canary["name"],
        "iteration": iteration,
        "project": project,
        "task_id": task_id,
        "protocol_ref": canary["protocol_ref"],
        "recovery_injected": True,
        "doctor_ok": doctor["ok"],
        "work_item_count": len(projection["work_items"]),
        "accepted_work_items": accepted,
        "task_status": projection["task"]["status"],
        "successful_attempts": sum(
            attempt["status"] == "succeeded"
            for attempt in projection["attempts"].values()
        ),
        "artifact_contracts_satisfied": len(projection["artifacts"])
        == len(projection["task"]["compiled_protocol"]["artifact_contracts"]),
        "promotion_gates_satisfied": set(projection["protocol_gates"])
        == set(projection["task"]["compiled_protocol"]["promotion_gates"]),
        "last_event_sequence": projection["last_event_sequence"],
        "last_event_hash": projection["last_event_hash"],
    }


def _canary_output(
    source_root: Path,
    *,
    canary: dict[str, Any],
    node_id: str,
) -> str:
    if canary["name"] == "NovelCanary" and node_id == "writer":
        story = yaml.safe_load(
            Path(str(canary["story_bible_path"])).read_text(encoding="utf-8")
        )
        chapter = story["chapter_one"]
        return (
            "# 第一章：灯塔记忆\n\n"
            "潮水退去以后，守塔人终于在铜制透镜背面看见了自己的名字。"
            "那不是刻痕，而是一段会随灯束转动的记忆。\n\n"
            f"他必须完成的不可逆改变是：{chapter['irreversible_change']}。\n"
        )
    if canary["name"] == "CodeCanary" and node_id == "implementation":
        return (
            "# Candidate patch\n\n"
            "```diff\n+def stable_fixture() -> str:\n+    return 'stable'\n```\n"
        )
    return (
        f"# {canary['name']} / {node_id}\n\n"
        f"Protocol: {canary['protocol_ref']}\n\n"
        "Deterministic isolated canary stage completed.\n"
    )


def _execute_canary_attempt(
    source_root: Path,
    runtime: TaskRuntime,
    *,
    projection: dict[str, Any],
    task_id: str,
    node_id: str,
    binding: dict[str, Any],
    canary: dict[str, Any],
    source_paths: list[Path],
) -> tuple[str, str]:
    attempt_id = f"attempt-{node_id}"
    worker = f"protocol-canary-{node_id}"
    classification = projection["task"]["input_classification"]
    deterministic = binding.get("execution_kind") == "deterministic_tool"
    deterministic_tool = {
        "tool_id": f"agentlab.protocol.{binding.get('profile') or node_id}",
        "tool_version": "1",
        "protocol_ref": canary["protocol_ref"],
        "node_id": node_id,
    }
    execution_contract: dict[str, Any] = {
        "role": binding["role"],
        "executor_type": "deterministic_tool" if deterministic else "cli_agent",
        "input_tier": classification["tier"],
        "route": classification["route"],
        "agent_model_profile": binding.get("agent_model_profile"),
    }
    provider = "agentlab-deterministic" if deterministic else "protocol-canary-provider"
    if deterministic:
        execution_contract["deterministic_tool"] = deterministic_tool
    else:
        execution_contract.update(
            {
                "invocation_contract": "protocol-canary-fixture",
                "model_key": "fixture",
                "model_id": "protocol-canary-model",
                "runtime_provider": provider,
            }
        )
    runtime.schedule_attempt(
        task_id,
        work_item_id=node_id,
        attempt_id=attempt_id,
        worker=worker,
        provider=provider,
        execution_contract=execution_contract,
        idempotency_key=f"schedule-{task_id}-{node_id}",
    )
    runtime.transition_attempt(
        task_id,
        attempt_id=attempt_id,
        status="running",
        idempotency_key=f"running-{task_id}-{node_id}",
    )
    task_root = runtime._task_dir(task_id)
    attempt_root = task_root / "attempt_logs" / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=True)
    output_path = attempt_root / "output.md"
    atomic_write_text(
        output_path,
        _canary_output(source_root, canary=canary, node_id=node_id),
    )
    output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
    model_execution: dict[str, Any] | None = None
    if not deterministic:
        model_receipt_path = attempt_root / "model_execution_receipt.yml"
        atomic_write_yaml(
            model_receipt_path,
            {
                "status": "pass",
                "worker": worker,
                "invocation_contract": "protocol-canary-fixture",
                "role": binding["role"],
                "selected_provider": provider,
                "selected_model_id": "protocol-canary-model",
                "profile_binding_verified": True,
                "command_binding_verified": True,
                "fallback_detected": False,
                "provider_process_started": True,
                "exit_code": 0,
                "issues": [],
                "provider_model_binding_verified": True,
            },
        )
        model_execution = {
            "path": model_receipt_path.relative_to(task_root).as_posix(),
            "sha256": hashlib.sha256(model_receipt_path.read_bytes()).hexdigest(),
            "cli_agent": worker,
            "model_key": "fixture",
            "model_id": "protocol-canary-model",
            "runtime_provider": provider,
            "executor_provider": "agentlab-cli-executor",
        }
    receipt_path = attempt_root / (
        "deterministic_execution_receipt.yml"
        if deterministic
        else "attempt_receipt.yml"
    )
    receipt = {
        "schema_version": (
            "task-runtime-deterministic-attempt-receipt/v1"
            if deterministic
            else "task-runtime-role-attempt-receipt/v1"
        ),
        "project": runtime.project,
        "task_id": task_id,
        "work_item_id": node_id,
        "attempt_id": attempt_id,
        "role": binding["role"],
        "worker": worker,
        "provider": provider,
        "status": "pass",
        "output_path": output_path.relative_to(task_root).as_posix(),
        "output_sha256": output_sha256,
        "sealed_sources": [
            {
                "path": path.relative_to(runtime.agentlab_root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in source_paths
        ],
        "model_execution": model_execution,
    }
    if deterministic:
        receipt["deterministic_tool"] = deterministic_tool
    atomic_write_yaml(receipt_path, receipt)
    receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    outcome = {
        "execution_origin": (
            "deterministic_tool_executor" if deterministic else "role_attempt_executor"
        ),
        "receipt_path": receipt_path.relative_to(task_root).as_posix(),
        "receipt_sha256": receipt_sha256,
        "output_sha256": output_sha256,
    }
    if deterministic:
        runtime._transition_deterministic_attempt(
            task_id,
            attempt_id=attempt_id,
            idempotency_key=f"succeeded-{task_id}-{node_id}",
            outcome=outcome,
        )
    else:
        runtime._transition_executed_attempt(
            task_id,
            attempt_id=attempt_id,
            status="succeeded",
            idempotency_key=f"succeeded-{task_id}-{node_id}",
            outcome=outcome,
        )
    return output_sha256, attempt_id


def run_protocol_canaries(
    agentlab_root: Path,
    *,
    state_root: Path,
    iterations: int = 10,
) -> dict[str, Any]:
    """Run isolated Novel and Code kernel canaries with restart recovery."""

    if iterations < 1:
        raise ValueError("canary iterations must be positive")
    source_root = Path(agentlab_root).resolve()
    isolated_root = Path(state_root).resolve()
    _install_canary_authority(source_root, isolated_root)
    runs = [
        _run_one(source_root, isolated_root, canary=canary, iteration=iteration)
        for iteration in range(1, iterations + 1)
        for canary in _CANARIES
    ]
    ok = all(
        run["doctor_ok"] and run["accepted_work_items"] == run["work_item_count"]
        for run in runs
    )
    return {
        "schema_version": "protocol-canary-report/v1",
        "ok": ok,
        "iterations": iterations,
        "runs": runs,
    }
