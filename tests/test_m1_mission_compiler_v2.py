"""Tests for M1-2 Mission Compiler v2 — deterministic prompt-to-contract compilation."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent_runtime.brain.mission_contract import build_mission_contract
from agent_runtime.brain.domain_classifier import classify_domain


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def local_hermes_command(command: str) -> str | None:
    return command if command == "hermes" else None


# ── Prompt fixtures ────────────────────────────────────────────────

PROMPT_CODEBASE = (
    "I want to build a local-first task runner CLI app in Python that can manage "
    "long-running projects. It should track project phases, record evidence, and "
    "help with acceptance reviews."
)

PROMPT_LONGFORM = (
    "I want to write a science fiction novel series set in a post-scarcity "
    "interstellar civilization. The series spans three books with interconnected "
    "character arcs. I need worldbuilding, character bibles, chapter outlines, "
    "continuity tracking, and drafting chapters."
)

PROMPT_VIDEO = (
    "I want to create a YouTube video series about the history of computing. "
    "Each episode should be 15-20 minutes, with scripts, storyboards, and visual "
    "asset plans."
)

PROMPT_IMAGE = (
    "Generate image: a cinematic hero image for a new synth plugin, 16:9, "
    "polished and high quality."
)

PROMPT_SIMPLE_IMAGE = "Quick simple generate image of a clean app icon."

PROMPT_BATCH_DRAFT = "Generate 20 draft image variations for concept exploration."

PROMPT_RESEARCH = (
    "I need to conduct a systematic literature review on RAG systems for enterprise "
    "knowledge management. I need to search academic databases, ingest papers, "
    "extract claims and evidence, and produce a comprehensive review report with citations."
)

PROMPT_DOCUMENT = (
    "I have a collection of technical documents and PDF whitepapers about our "
    "product architecture. I want to ingest all these documents, extract text and "
    "metadata, and build a searchable knowledge base index."
)

PROMPT_LOCAL_AUTO = (
    "I want to automate my local file organization workflow: scan my Downloads folder, "
    "classify files by type and date, rename them consistently, and move them to "
    "organized project folders. Run daily as a cron job."
)

PROMPT_EMPTY = ""


def test_ascii_domain_keywords_match_tokens_not_substrings() -> None:
    keywords = {
        "local_ops": {"keywords": ["script"]},
        "document_processing": {"keywords": ["article"]},
    }

    assert classify_domain("Write a product description article", keywords) == "document_processing"
    assert classify_domain("Run this script locally", keywords) == "local_ops"

PROMPT_CROWN_OF_ASH = (
    "Write chapter 7 of Crown of Ash. Keep the protagonist in close third POV, "
    "respect the prior continuity ledger, update character state, track the "
    "silver key item, preserve the foreshadowing about the burned chapel, and "
    "hit 2500 words."
)

PROMPT_CHINESE_CROWN_CHAPTER = (
    "按照《灰烬王冠》重构蓝图及角色圣经，撰写第10章_小规模追击。"
    "具体情节：第一次小规模冲突。教团与教会圣光骑士团在外围发生摩擦，"
    "凯恩在突袭中顺手救下一个虚弱的教团少年。"
)

PROMPT_CHINESE_MEDIA_SERIES = "给Crown_of_Ash做一段连贯视频脚本和海报图册"


# ── Domain classification tests ────────────────────────────────────


class TestDomainClassification:
    def test_coding_domain_detected(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert contract["task_type"] == "coding"

    def test_creative_longform_domain_detected(self):
        contract = build_mission_contract(PROMPT_LONGFORM)
        assert contract["task_type"] == "creative_longform"

    def test_video_generation_domain_detected(self):
        contract = build_mission_contract(PROMPT_VIDEO)
        assert contract["task_type"] == "video_generation"

    def test_image_generation_domain_detected(self):
        contract = build_mission_contract(PROMPT_IMAGE)
        assert contract["task_type"] == "image_generation"

    def test_research_domain_detected(self):
        contract = build_mission_contract(PROMPT_RESEARCH)
        assert contract["task_type"] == "research"

    def test_document_processing_domain_detected(self):
        contract = build_mission_contract(PROMPT_DOCUMENT)
        assert contract["task_type"] == "document_processing"

    def test_local_ops_domain_detected(self):
        contract = build_mission_contract(PROMPT_LOCAL_AUTO)
        assert contract["task_type"] == "local_ops"

    def test_empty_prompt_returns_unknown(self):
        contract = build_mission_contract(PROMPT_EMPTY)
        assert contract["task_type"] == "unknown"


# ── Domain-aware mission route tests ─────────────────────────────────


class TestDomainAwareMissionCompiler:
    def test_creative_writing_normalizes_domain_but_preserves_legacy_task_type(self):
        contract = build_mission_contract(PROMPT_CROWN_OF_ASH)
        assert contract["task_type"] == "creative_longform"
        assert contract["task_domain"] == "creative_writing"
        assert contract["artifact_type"] == "longform_text"

    def test_crown_of_ash_selects_light_chapter_route(self):
        contract = build_mission_contract(PROMPT_CROWN_OF_ASH)
        decision = contract["route_decision"]
        assert decision["action"] == "select_existing_route"
        assert decision["selected_route"] == "narrative_light_chapter"

    def test_chinese_crown_chapter_selects_light_chapter_route(self):
        contract = build_mission_contract(
            PROMPT_CHINESE_CROWN_CHAPTER,
            project_id="Crown_of_Ash",
            task_id="task_crown_rewrite_ch10",
        )
        assert contract["task_type"] == "creative_longform"
        assert contract["task_domain"] == "creative_writing"
        assert contract["project_type"] == "longform_text_project"
        assert contract["route_decision"]["selected_route"] == "narrative_light_chapter"

    def test_crown_chapter_range_selects_batch_route(self):
        contract = build_mission_contract(
            "按照 Crown_of_Ash 长篇规划，生成第1章到第20章候选稿，保持伏笔和时间线一致。",
            project_id="Crown_of_Ash",
            task_id="task_crown_batch_ch01_ch20",
        )
        assert contract["task_domain"] == "creative_writing"
        assert contract["project_type"] == "longform_text_project"
        assert contract["route_decision"]["selected_route"] == "narrative_batch_chapters"

    def test_crown_audit_selects_heavy_audit_route(self):
        contract = build_mission_contract(
            "审计 Crown_of_Ash 前 10 章，检查连续性并给出 promotion 前验收结论。",
            project_id="Crown_of_Ash",
            task_id="task_crown_audit_ch01_ch10",
        )
        assert contract["task_domain"] == "creative_writing"
        assert contract["route_decision"]["selected_route"] == "narrative_heavy_audit"

    def test_blocking_crown_rewrite_selects_narrative_planner_route(self):
        contract = build_mission_contract(
            "根据 heavy audit 的 blocking findings 重写 Crown_of_Ash 第1章到第200章规划。",
            project_id="Crown_of_Ash",
            task_id="task_crown_rewrite_plan_ch001_ch200",
        )
        decision = contract["route_decision"]
        assert decision["selected_route"] == "narrative_rewrite_plan"
        assert "route_proposal" not in decision

    def test_rewrite_question_remains_audit_instead_of_starting_rewrite(self):
        contract = build_mission_contract(
            "检查 Crown_of_Ash 前10章是否需要重写。",
            project_id="Crown_of_Ash",
            task_id="task_crown_check_rewrite_need",
        )
        assert contract["route_decision"]["selected_route"] == "narrative_heavy_audit"

    def test_audit_with_explicit_no_rewrite_boundary_remains_heavy_audit(self):
        contract = build_mission_contract(
            "审计 Crown_of_Ash 第1章到第20章。只审查已有正文；不得重写正文。"
            "发现 blocking issue 时只生成 revision_or_rewrite_proposal.yml。",
            project_id="Crown_of_Ash",
            task_id="task_crown_heavy_audit_no_direct_rewrite",
        )

        assert contract["narrative_job_identity"]["job_kind"] == "narrative_audit"
        assert contract["narrative_job_identity"]["run_mode"] == "audit_only"
        assert contract["route_decision"]["selected_route"] == "narrative_heavy_audit"

    def test_article_about_fiction_market_is_not_longform_chapter(self):
        contract = build_mission_contract(
            "写一篇关于小说市场的分析文章。",
            project_id="Crown_of_Ash",
            task_id="task_article_probe",
        )
        assert contract["route_decision"]["selected_route"] != "narrative_light_chapter"

    def test_chinese_chapter_continuity_check_selects_heavy_audit(self):
        contract = build_mission_contract(
            "检查前10章连续性。",
            project_id="Crown_of_Ash",
            task_id="task_crown_audit_short",
        )
        assert contract["task_domain"] == "creative_writing"
        assert contract["route_decision"]["selected_route"] == "narrative_heavy_audit"

    def test_chinese_media_prompt_with_do_route_to_media_generation(self):
        contract = build_mission_contract(
            PROMPT_CHINESE_MEDIA_SERIES,
            project_id="Crown_of_Ash",
            task_id="task_crown_media_prompt",
        )
        assert contract["task_domain"] == "video_generation"
        assert contract["project_type"] == "video_generation_project"
        assert contract["route_decision"]["selected_route"] == "media_generation_task"

    def test_creative_writing_memory_contract_includes_continuity_ledger(self):
        contract = build_mission_contract(PROMPT_CROWN_OF_ASH)
        assert "continuity_ledger" in contract["memory_contract"]
        assert "character_state" in contract["memory_contract"]
        assert "chapter_state_plan" in contract["memory_contract"]

    def test_creative_writing_route_forbids_generic_fallbacks(self):
        contract = build_mission_contract(PROMPT_CROWN_OF_ASH)
        forbidden = contract["route_decision"]["forbidden_routes"]
        assert "interface_sensitive_task" in forbidden
        assert "large_or_risky_task" in forbidden
        assert "artifact_production_task" in forbidden
        assert "fiction_chapter_pipeline" in forbidden

    def test_creative_writing_missing_route_refuses_and_proposes_pipeline(self):
        import shutil

        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            shutil.copy(repo_root / "config" / "mission_compiler_v2.yml", root / "config" / "mission_compiler_v2.yml")
            shutil.copy(repo_root / "config" / "project_type_classifier.yml", root / "config" / "project_type_classifier.yml")
            shutil.copy(repo_root / "config" / "domain_route_packs.yml", root / "config" / "domain_route_packs.yml")
            (root / "config" / "routing_rules.yml").write_text("version: 2\nroutes: {}\n", encoding="utf-8")
            contract = build_mission_contract(PROMPT_CROWN_OF_ASH, agentlab_root=root)
        decision = contract["route_decision"]
        assert decision["action"] == "refuse_current_route"
        assert decision["route_proposal"]["route_key"] == "narrative_light_chapter"
        assert "agents" not in decision["route_proposal"]

    def test_invalid_llm_assisted_compiler_output_falls_back_to_rules(self):
        def bad_generate(_messages):
            return "{not valid json"

        contract = build_mission_contract(
            PROMPT_CROWN_OF_ASH,
            use_llm_assist=True,
            llm_generate=bad_generate,
        )
        assert contract["compiler_source"] == "rule_based"
        assert contract["task_domain"] == "creative_writing"
        assert contract["route_decision"]["selected_route"] == "narrative_light_chapter"

    def test_llm_assisted_compiler_accepts_new_task_domain_alias(self):
        def good_generate(_messages):
            return '{"task_domain": "creative_writing", "project_type": "longform_text_project", "artifact_type": "longform_text"}'

        contract = build_mission_contract(
            "Draft the next Crown of Ash scene.",
            use_llm_assist=True,
            llm_generate=good_generate,
        )
        assert contract["compiler_source"] == "llm_assisted"
        assert contract["task_type"] == "creative_longform"
        assert contract["task_domain"] == "creative_writing"


# ── Project type classification tests ──────────────────────────────


class TestProjectTypeClassification:
    def test_codebase_build_project_type(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert contract["project_type"] == "codebase_build_project"

    def test_longform_text_project_type(self):
        contract = build_mission_contract(PROMPT_LONGFORM)
        assert contract["project_type"] == "longform_text_project"

    def test_video_generation_project_type(self):
        contract = build_mission_contract(PROMPT_VIDEO)
        assert contract["project_type"] == "video_generation_project"

    def test_image_generation_project_type(self):
        contract = build_mission_contract(PROMPT_IMAGE)
        assert contract["project_type"] == "media_generation_project"

    def test_research_archive_project_type(self):
        contract = build_mission_contract(PROMPT_RESEARCH)
        assert contract["project_type"] == "research_archive_project"

    def test_document_knowledgebase_project_type(self):
        contract = build_mission_contract(PROMPT_DOCUMENT)
        assert contract["project_type"] == "document_knowledgebase_project"

    def test_local_automation_project_type(self):
        contract = build_mission_contract(PROMPT_LOCAL_AUTO)
        assert contract["project_type"] == "local_automation_project"


# ── Long project detection tests ───────────────────────────────────


class TestLongProjectDetection:
    def test_codebase_is_long_project(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert contract["is_long_project"] is True

    def test_longform_is_long_project(self):
        contract = build_mission_contract(PROMPT_LONGFORM)
        assert contract["is_long_project"] is True

    def test_video_is_long_project(self):
        contract = build_mission_contract(PROMPT_VIDEO)
        assert contract["is_long_project"] is True

    def test_research_is_long_project(self):
        contract = build_mission_contract(PROMPT_RESEARCH)
        assert contract["is_long_project"] is True

    def test_document_is_long_project(self):
        contract = build_mission_contract(PROMPT_DOCUMENT)
        assert contract["is_long_project"] is True

    def test_local_automation_is_not_long_project(self):
        contract = build_mission_contract(PROMPT_LOCAL_AUTO)
        assert contract["is_long_project"] is False

    def test_unknown_is_not_long_project(self):
        contract = build_mission_contract(PROMPT_EMPTY)
        assert contract["is_long_project"] is False


# ── Capability requirements tests ──────────────────────────────────


class TestCapabilityRequirements:
    def test_codebase_has_required_capabilities(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        caps = contract["required_capabilities"]
        assert "filesystem_read" in caps
        assert "filesystem_write" in caps
        assert "shell_command" in caps
        assert "git_ops" in caps

    def test_longform_has_minimal_capabilities(self):
        contract = build_mission_contract(PROMPT_LONGFORM)
        caps = contract["required_capabilities"]
        assert "filesystem_read" in caps
        assert "filesystem_write" in caps

    def test_research_includes_web_search(self):
        contract = build_mission_contract(PROMPT_RESEARCH)
        caps = contract["required_capabilities"]
        assert "web_search" in caps
        assert "browser_fetch" in caps

    def test_document_includes_pdf_read(self):
        contract = build_mission_contract(PROMPT_DOCUMENT)
        caps = contract["required_capabilities"]
        assert "pdf_read" in caps

    def test_unknown_has_no_capabilities(self):
        contract = build_mission_contract(PROMPT_EMPTY)
        assert contract["required_capabilities"] == []


# ── Risk flag tests ────────────────────────────────────────────────


class TestRiskFlags:
    def test_codebase_has_risks(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert len(contract["risk_flags"]) >= 1

    def test_codebase_has_regression_risk(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert "code_quality_regression" in contract["risk_flags"]

    def test_unknown_has_clarification_risk(self):
        contract = build_mission_contract(PROMPT_EMPTY)
        assert "needs_clarification" in contract["risk_flags"]

    def test_no_non_goal_hits_for_normal_prompt(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert contract["non_goals"] == []

    def test_safety_ok_for_normal_prompt(self):
        # risk_flags from project type are OK; non_goal_hits would be problematic
        contract = build_mission_contract(PROMPT_LONGFORM)
        # The longform prompt itself doesn't contain non-goal patterns
        assert "spam" not in contract["non_goals"]


# ── Artifact target tests ──────────────────────────────────────────


class TestArtifactTargets:
    def test_codebase_has_artifacts(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        artifacts = contract["required_artifacts"]
        assert len(artifacts) >= 3
        assert "task_packet" in artifacts
        assert "test_results" in artifacts or "delivery_package" in artifacts

    def test_longform_has_artifacts(self):
        contract = build_mission_contract(PROMPT_LONGFORM)
        artifacts = contract["required_artifacts"]
        assert len(artifacts) >= 3

    def test_video_has_artifacts(self):
        contract = build_mission_contract(PROMPT_VIDEO)
        artifacts = contract["required_artifacts"]
        assert len(artifacts) >= 3

    def test_image_generation_has_media_artifacts(self):
        contract = build_mission_contract(PROMPT_IMAGE)
        artifacts = contract["required_artifacts"]
        assert "media_generation_contract.yml" in artifacts
        assert "generation_ledger.yml" in artifacts
        assert "media_qc_report.yml" in artifacts

    def test_unknown_has_minimal_artifacts(self):
        contract = build_mission_contract(PROMPT_EMPTY)
        assert "mission_contract" in contract["required_artifacts"]


# ── Acceptance gate tests ──────────────────────────────────────────


class TestAcceptanceGates:
    def test_global_gates_present(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        gates = contract["acceptance_gates"]
        assert "no_placeholder_artifacts" in gates
        assert "evidence_exists" in gates
        assert "human_approval" in gates
        assert "no_external_execution" in gates

    def test_codebase_has_specific_gates(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        gates = contract["acceptance_gates"]
        assert "tests_pass" in gates
        assert "compileall_passes" in gates

    def test_video_has_specific_gates(self):
        contract = build_mission_contract(PROMPT_VIDEO)
        gates = contract["acceptance_gates"]
        assert "generation_ledger_written" in gates

    def test_image_generation_has_harness_gates(self):
        contract = build_mission_contract(PROMPT_IMAGE)
        gates = contract["quality_gates"]
        assert "capability_auth_quota_preflight" in gates
        assert "qa_or_human_acceptance_before_project_artifact_promotion" in gates


# ── Media generation routing tests ─────────────────────────────────


class TestMediaGenerationRouting:
    @staticmethod
    def _media_config() -> dict:
        repo_root = Path(__file__).resolve().parents[1]
        return yaml.safe_load(
            (repo_root / "config" / "media_generation_backends.yml").read_text(encoding="utf-8")
        )

    def _contract_with_media_config(self, prompt: str, media_config: dict) -> dict:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            for name in [
                "mission_compiler_v2.yml",
                "project_type_classifier.yml",
                "domain_route_packs.yml",
                "routing_rules.yml",
            ]:
                (root / "config" / name).write_text(
                    (repo_root / "config" / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            (root / "config" / "media_generation_backends.yml").write_text(
                yaml.safe_dump(media_config, sort_keys=False),
                encoding="utf-8",
            )
            return build_mission_contract(prompt, agentlab_root=root)

    def test_unknown_capacity_backed_auth_is_pending_without_fallback_preselection(self):
        repo_root = Path(__file__).resolve().parents[1]
        media_config = yaml.safe_load(
            (repo_root / "config" / "media_generation_backends.yml").read_text(encoding="utf-8")
        )
        assert media_config["backends"]["hermes_grok_oauth"]["auth_state"] == "unknown"
        assert media_config["backends"]["hermes_grok_oauth"]["capacity_source"]

        contract = self._contract_with_media_config(PROMPT_SIMPLE_IMAGE, media_config)
        media = contract["media_generation_contract"]

        assert media["selected_backend"] is None
        assert media["executable"] is False
        assert media["routing_status"] == "pending_capacity"
        assert media["execution_blocker"]["status"] == "capacity_pending"
        assert media["execution_blocker"]["backend"] == "hermes_grok_oauth"
        assert media["execution_blocker"]["recommended_action"] == "observe_capacity_then_retry"
        assert media["approval_card"] is None

    def test_generate_image_selects_hermes_grok_when_local_cli_adapter_is_ready(self):
        media_config = self._media_config()
        media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "ready"
        with (
            patch(
                "agent_runtime.brain.media_generation_router.shutil.which",
                side_effect=local_hermes_command,
            ),
            patch.dict(os.environ, {"XAI_API_KEY": ""}, clear=False),
        ):
            contract = self._contract_with_media_config(PROMPT_IMAGE, media_config)
        media = contract["media_generation_contract"]
        assert contract["task_domain"] == "image_generation"
        assert contract["artifact_type"] == "media_generation_contract"
        assert contract["route_decision"]["selected_route"] == "media_generation_task"
        assert media["selected_backend"] == "hermes_grok_oauth"
        assert media["fallback_chain"][:3] == ["hermes_grok_oauth", "grok_direct", "bailian_cli"]
        assert media["executable"] is True
        assert media["execution_blocker"] is None
        assert media["backend_contracts"]["hermes_grok_oauth"]["adapter_kind"] == "local_grok_cli"

    def test_simple_image_selects_local_grok_cli_by_default(self):
        media_config = self._media_config()
        media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "ready"
        with (
            patch(
                "agent_runtime.brain.media_generation_router.shutil.which",
                side_effect=local_hermes_command,
            ),
            patch.dict(os.environ, {"XAI_API_KEY": ""}, clear=False),
        ):
            contract = self._contract_with_media_config(PROMPT_SIMPLE_IMAGE, media_config)
        media = contract["media_generation_contract"]
        assert media["backend_policy"] == "fast_simple"
        assert media["selected_backend"] == "hermes_grok_oauth"
        assert media["fallback_chain"][:3] == ["hermes_grok_oauth", "grok_direct", "bailian_cli"]
        assert media["executable"] is True
        assert media["execution_blocker"] is None

    def test_grok_direct_is_not_auto_selected_when_xai_key_is_present(self):
        repo_root = Path(__file__).resolve().parents[1]
        media_config = yaml.safe_load((repo_root / "config" / "media_generation_backends.yml").read_text(encoding="utf-8"))
        media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "missing_auth"
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "GROK_API_KEY": ""}, clear=False):
            contract = self._contract_with_media_config(PROMPT_SIMPLE_IMAGE, media_config)
        media = contract["media_generation_contract"]
        assert media["selected_backend"] == "bailian_cli"
        assert media["executable"] is False
        assert media["execution_blocker"]["status"] == "approval_required"
        assert media["backend_contracts"]["grok_direct"]["fallback_only"] is True
        assert media["backend_contracts"]["grok_direct"]["approval_required"] is True

    def test_grok_direct_is_not_auto_selected_when_grok_key_alias_is_present(self):
        repo_root = Path(__file__).resolve().parents[1]
        media_config = yaml.safe_load((repo_root / "config" / "media_generation_backends.yml").read_text(encoding="utf-8"))
        media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "missing_auth"
        with patch.dict(os.environ, {"XAI_API_KEY": "", "GROK_API_KEY": "test-key"}, clear=False):
            contract = self._contract_with_media_config(PROMPT_SIMPLE_IMAGE, media_config)
        media = contract["media_generation_contract"]
        assert media["selected_backend"] == "bailian_cli"
        assert media["executable"] is False
        assert media["execution_blocker"]["status"] == "approval_required"
        assert media["backend_contracts"]["grok_direct"]["fallback_only"] is True
        assert media["backend_contracts"]["grok_direct"]["approval_required"] is True

    def test_missing_local_grok_cli_does_not_auto_fall_through_to_direct_api_when_key_is_present(self):
        media_config = self._media_config()
        media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "ready"
        with (
            patch("agent_runtime.brain.media_generation_router.shutil.which", return_value=None),
            patch.dict(os.environ, {"XAI_API_KEY": "test-key", "GROK_API_KEY": ""}, clear=False),
        ):
            contract = self._contract_with_media_config(PROMPT_SIMPLE_IMAGE, media_config)
        media = contract["media_generation_contract"]
        assert media["selected_backend"] == "bailian_cli"
        assert media["executable"] is False
        assert media["execution_blocker"]["status"] == "approval_required"
        assert media["backend_contracts"]["grok_direct"]["fallback_only"] is True

    def test_missing_direct_api_key_falls_through_instead_of_blocking_default_route(self):
        repo_root = Path(__file__).resolve().parents[1]
        media_config = yaml.safe_load((repo_root / "config" / "media_generation_backends.yml").read_text(encoding="utf-8"))
        media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "missing_auth"
        with patch.dict(os.environ, {"XAI_API_KEY": "", "GROK_API_KEY": ""}, clear=False):
            contract = self._contract_with_media_config(PROMPT_SIMPLE_IMAGE, media_config)
        media = contract["media_generation_contract"]
        assert media["selected_backend"] == "bailian_cli"
        assert media["executable"] is False
        assert media["execution_blocker"]["status"] == "approval_required"

    def test_draft_batch_does_not_preselect_an_unobserved_renderer(self):
        contract = build_mission_contract(PROMPT_BATCH_DRAFT)
        media = contract["media_generation_contract"]
        assert media["backend_policy"] == "draft_batch"
        assert media["selected_backend"] is None
        assert media["routing_status"] == "pending_capacity"
        assert media["execution_blocker"]["backend"] == "hermes_grok_oauth"

    def test_ark_pending_is_not_executable_backend(self):
        media_config = self._media_config()
        media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "ready"
        with patch(
            "agent_runtime.brain.media_generation_router.shutil.which",
            side_effect=local_hermes_command,
        ):
            contract = self._contract_with_media_config(
                "Generate a commercial final image for client delivery.", media_config
            )
        media = contract["media_generation_contract"]
        assert media["selected_backend"] == "hermes_grok_oauth"
        assert media["executable"] is True
        assert {"backend": "ark_cli", "auth_state": "pending_activation"} in media["pending_backends"]

    def test_bailian_first_ready_backend_creates_approval_card(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            for name in [
                "mission_compiler_v2.yml",
                "project_type_classifier.yml",
                "domain_route_packs.yml",
                "routing_rules.yml",
            ]:
                (root / "config" / name).write_text(
                    (repo_root / "config" / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            media_config = yaml.safe_load((repo_root / "config" / "media_generation_backends.yml").read_text(encoding="utf-8"))
            media_config["backends"]["hermes_grok_oauth"]["auth_state"] = "missing_auth"
            media_config["backends"]["grok_direct"]["auth_state"] = "missing_auth"
            (root / "config" / "media_generation_backends.yml").write_text(
                yaml.safe_dump(media_config, sort_keys=False),
                encoding="utf-8",
            )

            contract = build_mission_contract(PROMPT_IMAGE, agentlab_root=root)

        media = contract["media_generation_contract"]
        assert media["selected_backend"] == "bailian_cli"
        assert media["approval_required"] is True
        assert media["executable"] is False
        assert media["execution_blocker"]["status"] == "approval_required"
        assert media["approval_card"]["status"] == "approval_required"
        assert media["backend_contracts"]["bailian_cli"]["command_contract"]["image_generation"] == "bl image generate"
        assert "bl text chat" in media["backend_contracts"]["bailian_cli"]["forbidden_command_contracts"]

    def test_no_ready_media_backend_generates_proposal_only(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            for name in [
                "mission_compiler_v2.yml",
                "project_type_classifier.yml",
                "domain_route_packs.yml",
                "routing_rules.yml",
            ]:
                (root / "config" / name).write_text(
                    (repo_root / "config" / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            media_config = yaml.safe_load((repo_root / "config" / "media_generation_backends.yml").read_text(encoding="utf-8"))
            for backend in media_config["backends"].values():
                backend["auth_state"] = "missing_auth"
            (root / "config" / "media_generation_backends.yml").write_text(
                yaml.safe_dump(media_config, sort_keys=False),
                encoding="utf-8",
            )

            contract = build_mission_contract(PROMPT_IMAGE, agentlab_root=root)

        media = contract["media_generation_contract"]
        assert media["selected_backend"] is None
        assert media["executable"] is False
        assert media["no_backend_fallback"]["do_not_fabricate_artifact"] is True


# ── Decision card tests ────────────────────────────────────────────


class TestDecisionCards:
    def test_codebase_has_decision_cards(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert len(contract["decision_cards"]) >= 1

    def test_codebase_has_external_executor_card(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert "dc_external_executor" in contract["decision_cards"]

    def test_unknown_has_project_type_card(self):
        contract = build_mission_contract(PROMPT_EMPTY)
        assert "dc_project_type_unknown" in contract["decision_cards"]

    def test_decision_cards_are_unique(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert len(contract["decision_cards"]) == len(set(contract["decision_cards"]))


# ── Scale estimation tests ─────────────────────────────────────────


class TestScaleEstimation:
    def test_small_prompt_is_small_scale(self):
        contract = build_mission_contract("short prompt")
        assert contract["estimated_scale"] == "small"

    def test_large_prompt_is_not_small(self):
        long_prompt = "zebra " * 500
        contract = build_mission_contract(long_prompt)
        assert contract["estimated_scale"] == "large"


# ── Human approval tests ───────────────────────────────────────────


class TestHumanApproval:
    def test_human_approval_always_required(self):
        for prompt in [PROMPT_CODEBASE, PROMPT_LONGFORM, PROMPT_VIDEO, PROMPT_RESEARCH, PROMPT_EMPTY]:
            contract = build_mission_contract(prompt)
            assert contract["human_approval_required"] is True, f"human_approval missing for prompt starting: {prompt[:30]}"


# ── Schema compliance tests ────────────────────────────────────────


class TestSchemaCompliance:
    REQUIRED_KEYS = [
        "schema_version",
        "task_id",
        "project_id",
        "user_goal",
        "intent_summary",
        "task_type",
        "project_type",
        "is_long_project",
        "estimated_scale",
        "non_goals",
        "hard_constraints",
        "soft_preferences",
        "unknowns",
        "assumptions",
        "required_capabilities",
        "required_artifacts",
        "acceptance_gates",
        "risk_flags",
        "external_executor_needed",
        "asset_registry_recommended",
        "human_approval_required",
        "decision_cards",
    ]

    def test_codebase_contract_has_all_keys(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        for key in self.REQUIRED_KEYS:
            assert key in contract, f"missing key: {key}"

    def test_longform_contract_has_all_keys(self):
        contract = build_mission_contract(PROMPT_LONGFORM)
        for key in self.REQUIRED_KEYS:
            assert key in contract, f"missing key: {key}"

    def test_empty_contract_has_all_keys(self):
        contract = build_mission_contract(PROMPT_EMPTY)
        for key in self.REQUIRED_KEYS:
            assert key in contract, f"missing key: {key}"

    def test_schema_version_is_2(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert contract["schema_version"] == 2


# ── Renderer tests ─────────────────────────────────────────────────


class TestRenderer:
    def test_renders_all_expected_files(self):
        from agent_runtime.brain.renderer import render_mission_contract_outputs

        contract = build_mission_contract(PROMPT_CODEBASE)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            written = render_mission_contract_outputs(contract, out_dir)
            assert (out_dir / "mission_contract.yml").exists()
            assert (out_dir / "intent_summary.md").exists()
            assert (out_dir / "required_capabilities.yml").exists()
            assert (out_dir / "artifact_contracts.yml").exists()
            assert (out_dir / "acceptance_gates.yml").exists()
            assert (out_dir / "risk_flags.yml").exists()
            assert (out_dir / "decision_cards").is_dir()

    def test_mission_contract_yaml_is_valid(self):
        from agent_runtime.brain.renderer import render_mission_contract_outputs

        contract = build_mission_contract(PROMPT_CODEBASE)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            render_mission_contract_outputs(contract, out_dir)
            data = yaml.safe_load((out_dir / "mission_contract.yml").read_text(encoding="utf-8"))
            assert isinstance(data, dict)
            assert data["task_type"] == "coding"

    def test_intent_summary_is_markdown(self):
        from agent_runtime.brain.renderer import render_mission_contract_outputs

        contract = build_mission_contract(PROMPT_CODEBASE)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            render_mission_contract_outputs(contract, out_dir)
            md = (out_dir / "intent_summary.md").read_text(encoding="utf-8")
            assert md.startswith("# Intent Summary")
            assert "coding" in md

    def test_renders_media_generation_contract(self):
        from agent_runtime.brain.renderer import render_mission_contract_outputs

        with patch(
            "agent_runtime.brain.media_generation_router.shutil.which",
            side_effect=local_hermes_command,
        ):
            contract = build_mission_contract(PROMPT_IMAGE)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            written = render_mission_contract_outputs(contract, out_dir)
            assert (out_dir / "media_generation_contract.yml").exists()
            assert "media_generation_contract" in written
            media = yaml.safe_load((out_dir / "media_generation_contract.yml").read_text(encoding="utf-8"))
            assert media["selected_backend"] is None
            assert media["routing_status"] == "pending_capacity"


# ── External executor recommendation tests ─────────────────────────


class TestExternalExecutor:
    def test_codebase_recommends_external_executor(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert contract["external_executor_needed"] is True

    def test_longform_does_not_recommend_external_executor(self):
        contract = build_mission_contract(PROMPT_LONGFORM)
        assert contract["external_executor_needed"] is False

    def test_video_recommends_external_executor(self):
        contract = build_mission_contract(PROMPT_VIDEO)
        assert contract["external_executor_needed"] is True


# ── Asset registry tests ───────────────────────────────────────────


class TestAssetRegistryRecommendation:
    def test_codebase_recommends_asset_registry(self):
        contract = build_mission_contract(PROMPT_CODEBASE)
        assert contract["asset_registry_recommended"] is True

    def test_local_auto_does_not_recommend_asset_registry(self):
        contract = build_mission_contract(PROMPT_LOCAL_AUTO)
        assert contract["asset_registry_recommended"] is False


# ── Prompt fixture file tests ──────────────────────────────────────


class TestPromptFixtures:
    @pytest.mark.parametrize("fixture_name", [
        "codebase_build_project.txt",
        "longform_text_project.txt",
        "video_generation_project.txt",
        "research_archive_project.txt",
        "document_knowledgebase_project.txt",
        "local_automation_project.txt",
    ])
    def test_fixture_exists_and_nonempty(self, fixture_name):
        path = Path(__file__).resolve().parents[1] / "examples" / "prompts" / fixture_name
        assert path.exists(), f"missing fixture: {fixture_name}"
        assert len(path.read_text(encoding="utf-8").strip()) > 20, f"fixture too short: {fixture_name}"

    @pytest.mark.parametrize("fixture_name,expected_domain", [
        ("codebase_build_project.txt", "coding"),
        ("longform_text_project.txt", "creative_longform"),
        ("video_generation_project.txt", "video_generation"),
        ("research_archive_project.txt", "research"),
        ("document_knowledgebase_project.txt", "document_processing"),
        ("local_automation_project.txt", "local_ops"),
    ])
    def test_fixture_classifies_correct_domain(self, fixture_name, expected_domain):
        path = Path(__file__).resolve().parents[1] / "examples" / "prompts" / fixture_name
        prompt = path.read_text(encoding="utf-8").strip()
        contract = build_mission_contract(prompt)
        assert contract["task_type"] == expected_domain, (
            f"{fixture_name}: expected {expected_domain}, got {contract['task_type']}"
        )

    @pytest.mark.parametrize("fixture_name,expected_project_type", [
        ("codebase_build_project.txt", "codebase_build_project"),
        ("longform_text_project.txt", "longform_text_project"),
        ("video_generation_project.txt", "video_generation_project"),
        ("research_archive_project.txt", "research_archive_project"),
        ("document_knowledgebase_project.txt", "document_knowledgebase_project"),
        ("local_automation_project.txt", "local_automation_project"),
    ])
    def test_fixture_classifies_correct_project_type(self, fixture_name, expected_project_type):
        path = Path(__file__).resolve().parents[1] / "examples" / "prompts" / fixture_name
        prompt = path.read_text(encoding="utf-8").strip()
        contract = build_mission_contract(prompt)
        assert contract["project_type"] == expected_project_type, (
            f"{fixture_name}: expected {expected_project_type}, got {contract['project_type']}"
        )


# ── Non-goal detection tests ───────────────────────────────────────


class TestNonGoalDetection:
    def test_spam_prompt_detects_non_goal(self):
        prompt = "I want to spam social media with fake engagement and auto-post to platforms."
        contract = build_mission_contract(prompt)
        # "spam" and "fake engagement" are in non_goal_patterns
        assert len(contract["non_goals"]) >= 1

    def test_pirate_prompt_detects_non_goal(self):
        prompt = "Help me steal content and pirate movies."
        contract = build_mission_contract(prompt)
        assert len(contract["non_goals"]) >= 1

    def test_impersonate_detected(self):
        prompt = "I need to impersonate a celebrity on social media."
        contract = build_mission_contract(prompt)
        assert len(contract["non_goals"]) >= 1

    def test_clean_prompt_has_no_non_goals(self):
        contract = build_mission_contract(PROMPT_RESEARCH)
        assert contract["non_goals"] == []


# ── Determinism tests ──────────────────────────────────────────────


class TestDeterminism:
    def test_same_prompt_same_output(self):
        contract1 = build_mission_contract(PROMPT_CODEBASE)
        contract2 = build_mission_contract(PROMPT_CODEBASE)
        assert contract1 == contract2

    def test_multiple_runs_consistent(self):
        for _ in range(5):
            contract = build_mission_contract(PROMPT_LONGFORM)
            assert contract["task_type"] == "creative_longform"
            assert contract["project_type"] == "longform_text_project"


# ── CLI tests ──────────────────────────────────────────────────────


class TestMissionCompilerCLI:
    def test_compile_command_help(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "agent_runtime/run_task.py", "mission-compiler", "--help"],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0
        assert "compile" in result.stdout

    def test_compile_help(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "agent_runtime/run_task.py", "mission-compiler", "compile", "--help"],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0
        stdout = strip_ansi(result.stdout)
        assert "--prompt-file" in stdout
        assert "--out" in stdout

    def test_compile_writes_to_out_dir(self):
        import subprocess
        import sys

        repo_root = Path(__file__).resolve().parents[1]
        fixture = repo_root / "examples" / "prompts" / "codebase_build_project.txt"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable, "agent_runtime/run_task.py", "mission-compiler", "compile",
                    "--prompt-file", str(fixture), "--out", tmp,
                ],
                capture_output=True, text=True, cwd=repo_root,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            out_dir = Path(tmp)
            assert (out_dir / "mission_contract.yml").exists()
            assert (out_dir / "intent_summary.md").exists()

    def test_compile_missing_prompt_file_errors(self):
        import subprocess
        import sys

        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable, "agent_runtime/run_task.py", "mission-compiler", "compile",
                    "--prompt-file", "/nonexistent/prompt.txt", "--out", tmp,
                ],
                capture_output=True, text=True, cwd=repo_root,
            )
            assert result.returncode != 0
