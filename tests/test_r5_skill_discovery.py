"""R5: Skill Discovery v1 — Comprehensive Tests.

Tests cover:
- Discovery produces deterministic candidates from fixture files.
- Candidates are disabled by default.
- Candidates require human review.
- External-derived candidates do not copy source code.
- Candidate evidence includes path, hash, and source category.
- Duplicate candidates are deduplicated.
- Missing optional sources do not crash.
- Candidate writer round-trip (write + load).
- Policy loading and validation.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skills.discovery import (  # noqa: E402
    _deduplicate_candidates,
    _make_candidate_id,
    _scan_acceptance_reports,
    _scan_docs,
    _scan_recovery_feedback,
    _scan_scripts,
    discover_candidates,
)
from skills.discovery_policy import (  # noqa: E402
    load_discovery_policy,
    validate_candidate,
)
from skills.candidate_writer import (  # noqa: E402
    load_candidates,
    merge_candidates,
    write_candidates,
)
from local_search.document import content_hash_of  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project tree with fixture files for all scanners."""

    # ── scripts/ ──────────────────────────────────────────────────────
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    # Qualifying script: docstring + >100 lines.
    qualifying = scripts_dir / "deploy_check.py"
    lines = ['"""Deployment pre-flight check utility."""', ""]
    lines.append("import os")
    lines.append("")
    # Pad to >100 lines.
    for i in range(105):
        lines.append(f"# comment line {i}")
    qualifying.write_text("\n".join(lines), encoding="utf-8")

    # Non-qualifying script: no docstring.
    no_doc = scripts_dir / "quick_fix.py"
    no_doc_lines = ["import sys", ""]
    for i in range(110):
        no_doc_lines.append(f"# line {i}")
    no_doc.write_text("\n".join(no_doc_lines), encoding="utf-8")

    # Short script: has docstring but <100 lines.
    short = scripts_dir / "hello.py"
    short.write_text('"""Hello world."""\nprint("hi")\n', encoding="utf-8")

    # ── acceptance_runs/ ──────────────────────────────────────────────
    acc_dir = tmp_path / "acceptance_runs"

    # Two runs with the same report file names.
    run_a = acc_dir / "run_a"
    run_a.mkdir(parents=True)
    (run_a / "acceptance_report.md").write_text("# Acceptance A\n- passed\n", encoding="utf-8")
    (run_a / "acceptance_summary.json").write_text('{"status": "pass"}', encoding="utf-8")

    run_b = acc_dir / "run_b"
    run_b.mkdir(parents=True)
    (run_b / "acceptance_report.md").write_text("# Acceptance B\n- passed\n", encoding="utf-8")
    (run_b / "acceptance_summary.json").write_text('{"status": "pass"}', encoding="utf-8")

    # ── projects/*/runs/*/recovery/ ───────────────────────────────────
    for task_id in ("task_001", "task_002", "task_003"):
        rec_dir = tmp_path / "projects" / "Demo" / "runs" / task_id / "recovery"
        rec_dir.mkdir(parents=True)
        feedback = {
            "task_id": task_id,
            "verdict": "passed",
            "failure_categories": ["timeout_error", "network_failure"],
        }
        (rec_dir / "closure_quality_feedback.json").write_text(
            json.dumps(feedback), encoding="utf-8"
        )

    # ── docs/ ─────────────────────────────────────────────────────────
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    # Qualifying doc: 6 checklist items.
    checklist_doc = docs_dir / "deployment_checklist.md"
    checklist_lines = [
        "# Deployment Checklist",
        "",
        "## Pre-deploy",
        "- [ ] Run tests",
        "- [ ] Check migrations",
        "- [ ] Verify env vars",
        "",
        "## Deploy",
        "- [ ] Deploy to staging",
        "- [x] Smoke tests",
        "- [ ] Deploy to production",
    ]
    checklist_doc.write_text("\n".join(checklist_lines), encoding="utf-8")

    # Non-qualifying doc: no checklist items.
    plain_doc = docs_dir / "overview.md"
    plain_doc.write_text("# Overview\n\nThis is a plain doc.\n", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def empty_root(tmp_path: Path) -> Path:
    """Create a project root with no fixture files at all."""
    return tmp_path


# ── Deterministic Candidate Production ───────────────────────────────────────


class TestDiscoverCandidates:
    """Discovery produces deterministic candidates from fixture files."""

    def test_discover_returns_list(self, project_root: Path) -> None:
        candidates = discover_candidates(project_root)
        assert isinstance(candidates, list)
        assert len(candidates) > 0

    def test_discover_is_deterministic(self, project_root: Path) -> None:
        first = discover_candidates(project_root)
        second = discover_candidates(project_root)
        assert len(first) == len(second)
        for a, b in zip(first, second):
            assert a["candidate_id"] == b["candidate_id"]
            assert a["title"] == b["title"]

    def test_scripts_scanner_finds_qualifying_script(self, project_root: Path) -> None:
        found = _scan_scripts(project_root)
        assert len(found) == 1
        assert "deploy_check" in found[0]["title"].lower() or "deploy" in found[0]["title"].lower()

    def test_scripts_scanner_skips_no_docstring(self, project_root: Path) -> None:
        found = _scan_scripts(project_root)
        titles = [c["title"] for c in found]
        assert not any("quick_fix" in t.lower() for t in titles)

    def test_scripts_scanner_skips_short_scripts(self, project_root: Path) -> None:
        found = _scan_scripts(project_root)
        titles = [c["title"] for c in found]
        assert not any("hello" in t.lower() for t in titles)

    def test_acceptance_scanner_finds_repeated_patterns(self, project_root: Path) -> None:
        found = _scan_acceptance_reports(project_root)
        assert len(found) == 1

    def test_recovery_scanner_finds_repeated_categories(self, project_root: Path) -> None:
        found = _scan_recovery_feedback(project_root)
        assert len(found) == 1
        caps = found[0]["proposed_capabilities"]
        # timeout_error appears in 3 tasks.
        assert any("timeout_error" in c for c in caps)

    def test_docs_scanner_finds_checklist(self, project_root: Path) -> None:
        found = _scan_docs(project_root)
        assert len(found) == 1
        assert "deployment" in found[0]["title"].lower() or "checklist" in found[0]["title"].lower()

    def test_docs_scanner_skips_plain_doc(self, project_root: Path) -> None:
        found = _scan_docs(project_root)
        titles = [c["title"] for c in found]
        assert not any("overview" in t.lower() for t in titles)


# ── Disabled By Default ──────────────────────────────────────────────────────


class TestCandidatesDisabledByDefault:
    """All candidates are disabled by default."""

    def test_all_candidates_disabled(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert c["enabled"] is False, f"{c['candidate_id']} should be disabled"

    def test_lifecycle_status_is_candidate(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert c["lifecycle_status"] == "candidate"


# ── Human Review Required ────────────────────────────────────────────────────


class TestCandidatesRequireHumanReview:
    """All candidates require human review."""

    def test_requires_human_review(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert c["promotion"]["requires_human_review"] is True

    def test_requires_tests(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert c["promotion"]["requires_tests"] is True

    def test_requires_metadata_completion(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert c["promotion"]["requires_metadata_completion"] is True

    def test_risk_requires_approval(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert c["risk"]["requires_approval"] is True


# ── No Source Code Copying ───────────────────────────────────────────────────


class TestNoSourceCodeCopying:
    """External-derived candidates do not copy source code."""

    def test_evidence_has_hash_not_content(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            for ev in c["source_evidence"]:
                assert "content_hash" in ev
                assert "text" not in ev
                assert "source_code" not in ev
                assert "content" not in ev

    def test_candidate_has_no_embedded_source(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert "source_code" not in c
            assert "embedded_source" not in c


# ── Evidence Includes Path / Hash / Source Category ──────────────────────────


class TestCandidateEvidence:
    """Candidate evidence includes path, hash, and source category."""

    def test_evidence_has_required_keys(self, project_root: Path) -> None:
        for c in discover_candidates(project_root):
            assert len(c["source_evidence"]) > 0
            for ev in c["source_evidence"]:
                assert "path" in ev, f"evidence missing path in {c['candidate_id']}"
                assert "source_category" in ev, f"evidence missing source_category"
                assert "content_hash" in ev, f"evidence missing content_hash"

    def test_evidence_hash_matches_content_hash_of(self, project_root: Path) -> None:
        """Verify that the hash in evidence matches content_hash_of on the file."""
        scripts_found = _scan_scripts(project_root)
        for c in scripts_found:
            for ev in c["source_evidence"]:
                file_path = project_root / ev["path"]
                if file_path.is_file():
                    text = file_path.read_text(encoding="utf-8")
                    assert ev["content_hash"] == content_hash_of(text)

    def test_evidence_source_category_is_valid(self, project_root: Path) -> None:
        valid_categories = {
            "repo_files", "docs", "config", "skills", "tests", "scripts",
            "acceptance_runs", "task_runs", "recovery_history",
            "closure_feedback", "external_inventory", "project_brain",
            "web_snapshots",
        }
        for c in discover_candidates(project_root):
            for ev in c["source_evidence"]:
                assert ev["source_category"] in valid_categories, (
                    f"Invalid source_category '{ev['source_category']}'"
                )


# ── Deduplication ────────────────────────────────────────────────────────────


class TestDeduplication:
    """Duplicate candidates are deduplicated."""

    def test_deduplicate_removes_same_id(self) -> None:
        a = {
            "candidate_id": "dup-test",
            "title": "Dup Test",
            "source_evidence": [{"path": "a.py", "source_category": "scripts", "content_hash": "h1"}],
            "proposed_capabilities": [],
            "suitable_task_types": [],
            "proposed_inputs": [],
            "proposed_outputs": [],
            "risk": {"level": "low", "reasons": [], "requires_approval": True},
            "license": {"source": "x", "review_required": False},
            "lifecycle_status": "candidate",
            "enabled": False,
            "promotion": {"requires_human_review": True, "requires_tests": True, "requires_metadata_completion": True},
        }
        b = dict(a)
        b["source_evidence"] = [{"path": "b.py", "source_category": "scripts", "content_hash": "h2"}]
        result = _deduplicate_candidates([a, b])
        assert len(result) == 1
        assert result[0]["candidate_id"] == "dup-test"
        # Evidence should be merged.
        paths = {ev["path"] for ev in result[0]["source_evidence"]}
        assert "a.py" in paths
        assert "b.py" in paths

    def test_deduplicate_keeps_distinct_ids(self) -> None:
        a = {"candidate_id": "alpha", "title": "Alpha", "source_evidence": [],
             "proposed_capabilities": [], "suitable_task_types": [],
             "proposed_inputs": [], "proposed_outputs": [],
             "risk": {"level": "low", "reasons": [], "requires_approval": True},
             "license": {"source": "x", "review_required": False},
             "lifecycle_status": "candidate", "enabled": False,
             "promotion": {"requires_human_review": True, "requires_tests": True, "requires_metadata_completion": True}}
        b = dict(a)
        b["candidate_id"] = "beta"
        b["title"] = "Beta"
        result = _deduplicate_candidates([a, b])
        assert len(result) == 2


# ── Missing Optional Sources ─────────────────────────────────────────────────


class TestMissingSources:
    """Missing optional sources do not crash."""

    def test_empty_root_returns_empty(self, empty_root: Path) -> None:
        candidates = discover_candidates(empty_root)
        assert candidates == []

    def test_nonexistent_root_returns_empty(self, tmp_path: Path) -> None:
        candidates = discover_candidates(tmp_path / "does_not_exist")
        assert candidates == []

    def test_partial_tree_scripts_only(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        s = scripts_dir / "tool.py"
        lines = ['"""A tool."""', ""]
        for i in range(105):
            lines.append(f"# {i}")
        s.write_text("\n".join(lines), encoding="utf-8")
        candidates = discover_candidates(tmp_path)
        assert len(candidates) == 1
        assert candidates[0]["source_evidence"][0]["source_category"] == "scripts"

    def test_config_disables_discovery(self, project_root: Path) -> None:
        config = {"discovery": {"enabled": False}}
        candidates = discover_candidates(project_root, config=config)
        assert candidates == []

    def test_config_limits_scanners(self, project_root: Path) -> None:
        config = {"discovery": {"scanners": ["scripts"]}}
        candidates = discover_candidates(project_root, config=config)
        # Only scripts scanner ran.
        for c in candidates:
            for ev in c["source_evidence"]:
                assert ev["source_category"] == "scripts"


# ── Candidate Writer Round-Trip ──────────────────────────────────────────────


class TestCandidateWriter:
    """Candidate writer round-trip: write then load."""

    def test_write_and_load_round_trip(self, tmp_path: Path) -> None:
        candidates = [
            {
                "candidate_id": "test-round-trip",
                "title": "Round Trip Test",
                "source_evidence": [
                    {"path": "test.py", "source_category": "scripts", "content_hash": "abc123"}
                ],
                "proposed_capabilities": ["test"],
                "suitable_task_types": ["testing"],
                "proposed_inputs": [],
                "proposed_outputs": [],
                "risk": {"level": "low", "reasons": ["test"], "requires_approval": True},
                "license": {"source": "test", "review_required": False},
                "lifecycle_status": "candidate",
                "enabled": False,
                "promotion": {
                    "requires_human_review": True,
                    "requires_tests": True,
                    "requires_metadata_completion": True,
                },
            }
        ]
        out = tmp_path / "candidates.yml"
        write_candidates(candidates, out)
        loaded = load_candidates(out)
        assert len(loaded) == 1
        assert loaded[0]["candidate_id"] == "test-round-trip"
        assert loaded[0]["enabled"] is False

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        loaded = load_candidates(tmp_path / "no_such_file.yml")
        assert loaded == []

    def test_merge_candidates_deduplicates(self) -> None:
        existing = [
            {"candidate_id": "a", "title": "A", "source_evidence": [
                {"path": "x.py", "source_category": "scripts", "content_hash": "h1"}
            ]},
        ]
        new = [
            {"candidate_id": "a", "title": "A Updated", "source_evidence": [
                {"path": "y.py", "source_category": "scripts", "content_hash": "h2"}
            ]},
            {"candidate_id": "b", "title": "B", "source_evidence": [
                {"path": "z.py", "source_category": "docs", "content_hash": "h3"}
            ]},
        ]
        merged = merge_candidates(existing, new)
        assert len(merged) == 2
        # Existing "a" kept, evidence merged.
        a_entry = [c for c in merged if c["candidate_id"] == "a"][0]
        assert a_entry["title"] == "A"  # existing takes precedence
        paths = {ev["path"] for ev in a_entry["source_evidence"]}
        assert "x.py" in paths
        assert "y.py" in paths

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "candidates.yml"
        write_candidates([], out)
        assert out.exists()


# ── Policy Loading ───────────────────────────────────────────────────────────


class TestDiscoveryPolicy:
    """Policy loading and defaults."""

    def test_default_policy_is_disabled(self) -> None:
        policy = load_discovery_policy()
        assert policy["enabled"] is False
        assert policy["allow_network"] is False
        assert policy["auto_import"] is False
        assert policy["auto_promote"] is False

    def test_default_policy_has_safety(self) -> None:
        policy = load_discovery_policy()
        safety = policy["safety"]
        assert safety["always_require_human_review"] is True
        assert safety["never_execute_external_code"] is True
        assert safety["never_copy_external_source"] is True

    def test_load_from_missing_file(self, tmp_path: Path) -> None:
        policy = load_discovery_policy(tmp_path / "no_such_policy.yml")
        assert policy["enabled"] is False

    def test_load_from_yaml_file(self, tmp_path: Path) -> None:
        import yaml
        policy_file = tmp_path / "discovery_policy.yml"
        policy_file.write_text(
            yaml.safe_dump({"enabled": True, "max_candidates_per_scan": 10}),
            encoding="utf-8",
        )
        policy = load_discovery_policy(policy_file)
        assert policy["enabled"] is True
        assert policy["max_candidates_per_scan"] == 10
        # Safety fields remain immutable.
        assert policy["safety"]["always_require_human_review"] is True

    def test_safety_cannot_be_overridden(self, tmp_path: Path) -> None:
        import yaml
        policy_file = tmp_path / "bad_policy.yml"
        policy_file.write_text(
            yaml.safe_dump({
                "safety": {
                    "always_require_human_review": False,
                    "never_execute_external_code": False,
                }
            }),
            encoding="utf-8",
        )
        policy = load_discovery_policy(policy_file)
        assert policy["safety"]["always_require_human_review"] is True
        assert policy["safety"]["never_execute_external_code"] is True


# ── Candidate Validation ─────────────────────────────────────────────────────


class TestCandidateValidation:
    """Validation of candidate dicts."""

    def _valid_candidate(self, **overrides: object) -> dict:
        base = {
            "candidate_id": "test-valid",
            "title": "Test Valid",
            "source_evidence": [
                {"path": "test.py", "source_category": "scripts", "content_hash": "abc"}
            ],
            "proposed_capabilities": ["test"],
            "suitable_task_types": ["testing"],
            "proposed_inputs": [],
            "proposed_outputs": [],
            "risk": {"level": "low", "reasons": ["test"], "requires_approval": True},
            "license": {"source": "test", "review_required": False},
            "lifecycle_status": "candidate",
            "enabled": False,
            "promotion": {
                "requires_human_review": True,
                "requires_tests": True,
                "requires_metadata_completion": True,
            },
        }
        base.update(overrides)
        return base

    def test_valid_candidate_passes(self) -> None:
        errors = validate_candidate(self._valid_candidate())
        assert errors == []

    def test_missing_field_fails(self) -> None:
        c = self._valid_candidate()
        del c["title"]
        errors = validate_candidate(c)
        assert any("missing" in e.lower() for e in errors)

    def test_enabled_true_fails(self) -> None:
        errors = validate_candidate(self._valid_candidate(enabled=True))
        assert any("enabled" in e.lower() for e in errors)

    def test_wrong_lifecycle_status_fails(self) -> None:
        errors = validate_candidate(self._valid_candidate(lifecycle_status="active"))
        assert any("lifecycle_status" in e.lower() for e in errors)

    def test_risk_requires_approval_false_fails(self) -> None:
        errors = validate_candidate(
            self._valid_candidate(
                risk={"level": "low", "reasons": [], "requires_approval": False}
            )
        )
        assert any("requires_approval" in e for e in errors)

    def test_human_review_false_fails(self) -> None:
        errors = validate_candidate(
            self._valid_candidate(
                promotion={
                    "requires_human_review": False,
                    "requires_tests": True,
                    "requires_metadata_completion": True,
                }
            )
        )
        assert any("requires_human_review" in e for e in errors)

    def test_empty_evidence_fails(self) -> None:
        errors = validate_candidate(self._valid_candidate(source_evidence=[]))
        assert any("source_evidence" in e for e in errors)

    def test_invalid_risk_level_fails(self) -> None:
        errors = validate_candidate(
            self._valid_candidate(
                risk={"level": "extreme", "reasons": [], "requires_approval": True}
            )
        )
        assert any("risk.level" in e for e in errors)

    def test_all_discovered_candidates_validate(self, project_root: Path) -> None:
        """Every candidate produced by discover_candidates must pass validation."""
        for c in discover_candidates(project_root):
            errors = validate_candidate(c)
            assert errors == [], f"Candidate {c['candidate_id']} failed: {errors}"


# ── Candidate ID Determinism ─────────────────────────────────────────────────


class TestCandidateIdSlug:
    """_make_candidate_id produces deterministic slugs."""

    def test_simple_title(self) -> None:
        assert _make_candidate_id("My Cool Tool") == "my-cool-tool"

    def test_special_characters(self) -> None:
        assert _make_candidate_id("Deploy: Pre-flight Check!") == "deploy-pre-flight-check"

    def test_empty_title(self) -> None:
        assert _make_candidate_id("") == "unnamed-candidate"

    def test_deterministic(self) -> None:
        title = "Script: Deploy Check"
        assert _make_candidate_id(title) == _make_candidate_id(title)
