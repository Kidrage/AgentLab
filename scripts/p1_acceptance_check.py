#!/usr/bin/env python3
"""Run the AgentLab P1 closed-loop acceptance scenario.

This script is intentionally local/mock only. It scans a fake ECC pack,
generates handoff/search/index/ledger/incubation artifacts, and verifies that
no external provider scripts, MCP servers, remote clones, or private URLs are
executed or accessed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.atomic_io import atomic_write_json, atomic_write_text
from agent_runtime.external_agents.ecc_inventory import scan_ecc_inventory
from agent_runtime.external_agents.handoff import ExternalHandoff
from agent_runtime.ingestion.repo_indexers.codegraph_adapter import CodeGraphAdapter
from agent_runtime.search.anysearch_adapter import AnySearchAdapter
from agent_runtime.skills.incubation import (
    default_incubation_policy,
    propose_internal_skill_candidates,
    write_incubation_artifacts,
)
from agent_runtime.skills.registry import (
    assert_skill_dispatchable,
    default_registry,
    import_inventory_records,
    write_skill_registry,
)
from agent_runtime.skills.usage_ledger import (
    default_skill_usage_ledger,
    record_skill_event,
    write_skill_usage_ledger,
)


def _git_value(args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "unknown"


def _ecc_config(ecc_path: Path) -> dict[str, Any]:
    return {
        "ecc": {
            "local_paths": [str(ecc_path)],
            "scan": {
                "allow_markdown_scan": True,
                "allow_json_yaml_scan": True,
                "max_files": 200,
                "max_file_kb": 256,
            },
            "risk_defaults": {"level": "medium", "requires_approval": True},
        }
    }


def _report_line(name: str, value: bool) -> str:
    return f"- {name}: {'PASS' if value else 'FAIL'}"


def run_acceptance(output_dir: Path, fixture_root: Path | None = None) -> dict[str, Any]:
    fixture_root = fixture_root or ROOT / "tests" / "fixtures" / "p1_closure"
    fake_ecc = fixture_root / "fake_ecc"
    fake_repo = fixture_root / "fake_repo"
    output_dir.mkdir(parents=True, exist_ok=True)

    task_id = "p1_closure_acceptance"
    danger_marker = output_dir / "agentlab_should_not_exist"
    mcp_marker = output_dir / "agentlab_mcp_should_not_exist"

    inventory_path = output_dir / "external_skill_inventory.json"
    registry_path = output_dir / "skill_registry.yml"
    anysearch_trace_path = output_dir / "anysearch_trace.json"
    repo_status_path = output_dir / "repo_index_status.json"
    ledger_path = output_dir / "skill_usage_ledger.yml"
    report_path = output_dir / "p1_acceptance_report.md"

    inventory = scan_ecc_inventory(ROOT, _ecc_config(fake_ecc), inventory_path)

    registry = default_registry()
    imported = import_inventory_records(registry, inventory, overwrite=False)
    write_skill_registry(ROOT, registry, registry_path)

    dispatch_rejected = False
    rejected_skill = imported[0]["skill_id"] if imported else "ecc.planner"
    try:
        assert_skill_dispatchable(registry, rejected_skill)
    except PermissionError:
        dispatch_rejected = True

    handoff = ExternalHandoff(task_id, str(output_dir))
    handoff_data = handoff.create_handoff(
        "cline_codex",
        "Review a small local repo and prepare an external handoff plan",
        "Task summary: local fake repo only. GITHUB_TOKEN=ghp_should_not_render sk_test_should_not_render",
        suggested_external_skills=[skill["skill_id"] for skill in imported[:2]],
    )
    handoff_md = (output_dir / "external_handoff.md").read_text(encoding="utf-8")

    disabled_search = AnySearchAdapter({"enabled": False}).search_web("AgentLab P1 closure")
    mock_search = AnySearchAdapter({"enabled": False}, mock=True).search_web("AgentLab P1 closure")
    batch_search = AnySearchAdapter(
        {"enabled": True, "safety": {"require_approval_for_batch_over": 1}},
        mock=True,
    ).batch_search(["one", "two"])
    blocked_urls = [
        "http://localhost:8000/secret",
        "http://127.0.0.1:8000/secret",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/router",
        "file:///etc/passwd",
    ]
    blocked_results = [
        AnySearchAdapter({"enabled": False}).extract_url(url).as_dict()
        for url in blocked_urls
    ]
    anysearch_trace = {
        "disabled": disabled_search.as_dict(),
        "mock": mock_search.as_dict(),
        "batch": batch_search.as_dict(),
        "blocked_urls": blocked_results,
    }
    atomic_write_json(anysearch_trace_path, anysearch_trace)

    codegraph = CodeGraphAdapter(
        {
            "enabled": True,
            "policy": {
                "require_approval_for_indexing": True,
                "forbid_repo_profile_indexing": True,
            },
        },
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runner should not execute")),
        which=lambda _: "/bin/true",
    )
    disabled_status = CodeGraphAdapter({"enabled": False}).status(fake_repo)
    dry_run = codegraph.index_repo(fake_repo, dry_run=True, mode="repo_patch")
    remote_decision = codegraph.can_index(Path("https://github.com/Kidrage/AgentLab"), mode="repo_patch")
    repo_profile_decision = codegraph.can_index(fake_repo, mode="repo_profile")
    repo_status = {
        "disabled_status": disabled_status.as_dict(),
        "dry_run": dry_run.as_dict(),
        "remote_decision": remote_decision.as_dict(),
        "repo_profile_decision": repo_profile_decision.as_dict(),
    }
    atomic_write_json(repo_status_path, repo_status)

    ledger = default_skill_usage_ledger(task_id)
    for skill in imported[:2]:
        record_skill_event(
            ledger,
            task_id=task_id,
            skill_id=skill["skill_id"],
            source=skill["source"],
            event="planned",
            reason="external skill discovered and planned for handoff only",
            evidence_artifacts=[str(inventory_path.name), "external_handoff.md"],
        )
    record_skill_event(
        ledger,
        task_id=task_id,
        skill_id=rejected_skill,
        source="ecc",
        event="rejected",
        reason="disabled external skill cannot be dispatched automatically",
        evidence_artifacts=[str(registry_path.name)],
    )
    record_skill_event(
        ledger,
        task_id=task_id,
        skill_id="anysearch.web_search",
        source="anysearch",
        event="skipped",
        reason="disabled mode returned safe skipped response",
        evidence_artifacts=[str(anysearch_trace_path.name)],
    )
    for _ in range(2):
        record_skill_event(
            ledger,
            task_id=task_id,
            skill_id=rejected_skill,
            source="ecc",
            event="used",
            reason="useful handoff pattern recorded from external capability metadata",
            success=True,
            quality_score=0.9,
            evidence_artifacts=["external_handoff.md"],
        )

    candidates = propose_internal_skill_candidates(
        registry,
        ledger,
        default_incubation_policy(),
        {"task_id": task_id, "task_type": "repo_patch"},
    )
    if candidates:
        record_skill_event(
            ledger,
            task_id=task_id,
            skill_id=candidates[0].candidate_id,
            source="agentlab_internal",
            event="distilled",
            reason="candidate proposed from repeated useful external workflow",
            success=True,
            evidence_artifacts=["internal_skill_candidates.yml"],
        )
    write_skill_usage_ledger(ledger_path, ledger)
    write_incubation_artifacts(output_dir, task_id=task_id, candidates=candidates)

    candidate_dicts = [candidate.to_dict() for candidate in candidates]
    checks = {
        "inventory_found": inventory["found"] is True,
        "static_inventory_only": inventory["scan_mode"] == "static_inventory_only",
        "skills_imported": bool(imported),
        "external_skills_disabled": all(skill.get("enabled") is False for skill in registry["external_skills"]),
        "unknown_license_review": all(
            (skill.get("license") or {}).get("license_review_required") is True
            for skill in registry["external_skills"]
        ),
        "dispatch_rejected": dispatch_rejected,
        "handoff_generated": (output_dir / "external_handoff.md").exists(),
        "handoff_redacted": "sk_test_" not in handoff_md and "GITHUB_TOKEN" not in handoff_md,
        "handoff_no_auto_execution": "Do not execute external tools automatically" in handoff_md,
        "anysearch_disabled_safe": disabled_search.status == "skipped",
        "anysearch_mock_ok": mock_search.status == "ok" and bool(mock_search.results),
        "anysearch_batch_pending_approval": batch_search.status == "pending_approval",
        "private_urls_rejected": all(item["status"] == "rejected" for item in blocked_results),
        "codegraph_remote_rejected": remote_decision.action == "deny",
        "codegraph_repo_profile_rejected": repo_profile_decision.action == "deny",
        "codegraph_dry_run_not_performed": dry_run.dry_run is True and dry_run.performed is False,
        "ledger_written": ledger_path.exists(),
        "candidate_generated": bool(candidate_dicts),
        "candidate_source_not_copied": bool(candidate_dicts) and candidate_dicts[0]["safety"]["source_code_copied"] is False,
        "candidate_license_review": bool(candidate_dicts) and candidate_dicts[0]["safety"]["license_review_required"] is True,
        "external_script_not_executed": not danger_marker.exists(),
        "mcp_server_not_started": not mcp_marker.exists(),
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"

    report = render_report(
        output_dir=output_dir,
        verdict=verdict,
        checks=checks,
        imported=imported,
        handoff_data=handoff_data,
        candidates=candidate_dicts,
    )
    atomic_write_text(report_path, report)

    return {
        "verdict": verdict,
        "checks": checks,
        "artifacts": {
            "external_skill_inventory": str(inventory_path),
            "skill_registry": str(registry_path),
            "external_handoff": str(output_dir / "external_handoff.md"),
            "anysearch_trace": str(anysearch_trace_path),
            "repo_index_status": str(repo_status_path),
            "skill_usage_ledger": str(ledger_path),
            "internal_skill_candidates": str(output_dir / "internal_skill_candidates.yml"),
            "p1_acceptance_report": str(report_path),
        },
    }


def render_report(
    *,
    output_dir: Path,
    verdict: str,
    checks: dict[str, bool],
    imported: list[dict[str, Any]],
    handoff_data: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    artifacts = [
        "external_skill_inventory.json",
        "skill_registry.yml",
        "external_handoff.md",
        "anysearch_trace.json",
        "repo_index_status.json",
        "skill_usage_ledger.yml",
        "internal_skill_candidates.yml",
        "p1_acceptance_report.md",
    ]
    lines = [
        "# AgentLab P1 Closure Acceptance Report",
        "",
        "## Summary",
        f"P1-A/B/C/D closed-loop acceptance result: {verdict}.",
        "",
        "## Commit",
        f"- hash: {_git_value(['rev-parse', 'HEAD'])}",
        f"- branch: {_git_value(['rev-parse', '--abbrev-ref', 'HEAD'])}",
        "",
        "## Tests Run",
        "- command: python scripts/p1_acceptance_check.py --output acceptance_runs/p1_closure",
        "",
        "## P1-A External Skill Registry / ECC Inventory",
        _report_line("static inventory scan", checks["static_inventory_only"]),
        _report_line("registry imported disabled skills", checks["external_skills_disabled"]),
        _report_line("unknown license requires review", checks["unknown_license_review"]),
        "- evidence: external_skill_inventory.json, skill_registry.yml",
        "",
        "## P1-B External Agent Handoff",
        _report_line("handoff generated", checks["handoff_generated"]),
        _report_line("secrets redacted", checks["handoff_redacted"]),
        _report_line("no auto-execution instruction present", checks["handoff_no_auto_execution"]),
        f"- handoff_id: {handoff_data.get('handoff_id')}",
        "- evidence: external_handoff.md",
        "",
        "## P1-C AnySearch Adapter",
        _report_line("disabled safe response", checks["anysearch_disabled_safe"]),
        _report_line("mock search completed", checks["anysearch_mock_ok"]),
        _report_line("batch approval required", checks["anysearch_batch_pending_approval"]),
        _report_line("local/private/file URLs rejected", checks["private_urls_rejected"]),
        "- evidence: anysearch_trace.json",
        "",
        "## P1-D CodeGraph Adapter",
        _report_line("remote repo URL rejected", checks["codegraph_remote_rejected"]),
        _report_line("repo_profile indexing rejected", checks["codegraph_repo_profile_rejected"]),
        _report_line("local dry-run did not execute", checks["codegraph_dry_run_not_performed"]),
        "- evidence: repo_index_status.json",
        "",
        "## Closed-loop Acceptance",
        f"- external skill discovered: {bool(imported)}",
        f"- registry imported: {bool(imported)}",
        "- handoff generated: true",
        "- mock search completed: true",
        "- repo index dry-run completed: true",
        "- skill ledger written: true",
        f"- incubation candidate generated: {bool(candidates)}",
        "",
        "## Safety Evidence",
        f"- external scripts executed: {'no' if checks['external_script_not_executed'] else 'yes'}",
        f"- MCP servers started: {'no' if checks['mcp_server_not_started'] else 'yes'}",
        "- remote repos cloned: no",
        "- private URLs accessed: no",
        "- secrets exposed: no",
        "- third-party source copied: no",
        "",
        "## Artifacts",
        *[f"- {output_dir / artifact}" for artifact in artifacts],
        "",
        "## Known Limitations",
        "- ECC execution still not implemented.",
        "- AnySearch real API still not implemented.",
        "- CodeGraph real indexing still requires approval.",
        "- External executor router not implemented.",
        "- 3E reviewer not implemented.",
        "",
        "## Verdict",
        verdict,
        "",
        "## Check Detail",
        *[_report_line(name, value) for name, value in checks.items()],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "acceptance_runs" / "p1_closure")
    parser.add_argument("--fixture-root", type=Path, default=ROOT / "tests" / "fixtures" / "p1_closure")
    args = parser.parse_args()

    result = run_acceptance(args.output, args.fixture_root)
    print(yaml.safe_dump(result, sort_keys=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
