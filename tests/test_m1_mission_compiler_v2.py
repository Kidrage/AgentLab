"""Tests for M1-2 Mission Compiler v2 — deterministic prompt-to-contract compilation."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest
import yaml

from agent_runtime.brain.mission_contract import build_mission_contract


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


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
        assert "script_approved" in gates or "storyboard_complete" in gates


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
