"""Focused tests for the canonical current capability evidence chain.

All filesystem mutation stays under tmp_path. Nothing rewrites the repository
canonical acceptance report or chain.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

import yaml
from typer.testing import CliRunner

from agent_runtime.capability_acceptance import ArtifactProbe, _artifact_probe
from agent_runtime.capability_evidence_chain import (
    CANONICAL_SOURCE_REL,
    CHAIN_ID,
    CHAIN_FILENAME,
    REPORT_TYPE,
    apply_current_evidence_policy,
    compute_aggregate_digest,
    is_historical_evidence_path,
    sha256_file,
    verify_capability_current_evidence_chain,
    write_capability_current_evidence_chain,
)
from agent_runtime.run_task import app


runner = CliRunner()


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _seed_active_file(root: Path, rel: str, body: str = "active-evidence\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _seed_config(root: Path) -> None:
    _write_yaml(
        root / "config" / "run_retention_policy.yml",
        {"schema_version": 1, "archive_root": "archive/run_history"},
    )
    _write_yaml(
        root / "config" / "content_project_governance.yml",
        {"schema_version": 1, "archive_roots": ["archive", "_archive"]},
    )


def _minimal_capability_report(
    *,
    capability_id: str = "demo_capability",
    status: str = "pass",
    evidence: list[str] | None = None,
    historical_evidence: list[str] | None = None,
) -> dict:
    capability = {
        "id": capability_id,
        "title": "Demo",
        "status": status,
        "evidence": evidence or [],
        "summary": "demo",
        "issues": [],
    }
    if historical_evidence:
        capability["historical_evidence"] = historical_evidence
    return {
        "schema_version": 1,
        "report_type": "agentlab_capability_acceptance",
        "overall_status": status,
        "status_counts": {status: 1},
        "capabilities": [capability],
    }


def _seed_canonical_report(root: Path, report: dict) -> Path:
    path = root / CANONICAL_SOURCE_REL
    _write_yaml(path, report)
    return path


def test_historical_path_classifier_rejects_archive_and_run_history(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    assert is_historical_evidence_path(
        "projects/AgentLab/archive/run_history/pruning/runs/task_x/workflow_plan.yml",
        tmp_path,
    )
    assert is_historical_evidence_path("projects/X/superseded/old.yml", tmp_path)
    assert is_historical_evidence_path("projects/X/retired/old.yml", tmp_path)
    assert not is_historical_evidence_path(
        "acceptance_runs/agentlab_capability_acceptance/media_series_scaffold_audit.yml",
        tmp_path,
    )
    assert not is_historical_evidence_path("agent_runtime/production_packs.py", tmp_path)


def test_archived_evidence_remains_on_disk_but_cannot_count_as_current(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    archived = (
        root
        / "projects"
        / "AgentLab"
        / "archive"
        / "run_history"
        / "pruning-test"
        / "runs"
        / "task_probe"
    )
    for name in ("workflow_plan.yml", "lifecycle.yml", "artifact_manifest.yml"):
        _write_yaml(archived / name, {"valid": True, "status": "pass"})
    _write_yaml(
        archived / "artifact_manifest.yml",
        {
            "valid": True,
            "pass_rate": 1.0,
            "artifacts_passed": 1,
            "artifacts_checked": 1,
            "issues": [],
        },
    )

    probe = ArtifactProbe(
        capability_id="code_factory_orchestration",
        title="Code factory orchestration",
        project="AgentLab",
        task_id="task_probe",
    )
    capability = _artifact_probe(root, probe)
    gated = apply_current_evidence_policy(root, capability)

    assert archived.is_dir()
    assert gated["status"] != "pass"
    assert gated["evidence"] == []
    assert gated.get("historical_evidence")
    assert all(is_historical_evidence_path(path, root) for path in gated["historical_evidence"])
    assert "only historical archived evidence available" in gated["issues"]


def test_report_cannot_claim_pass_from_archived_only_probe(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    archived_path = (
        "projects/AgentLab/archive/run_history/pruning-test/runs/task_x/workflow_plan.yml"
    )
    _seed_active_file(root, archived_path, "historical\n")
    raw = {
        "id": "code_factory_orchestration",
        "title": "Code factory orchestration",
        "status": "pass",
        "evidence": [archived_path],
        "summary": "artifact pass rate 1.0",
        "issues": [],
    }
    gated = apply_current_evidence_policy(root, raw)
    assert gated["status"] == "candidate"
    assert gated["evidence"] == []
    assert gated["historical_evidence"] == [archived_path]
    assert any("only historical" in issue for issue in gated["issues"])


def test_only_one_canonical_current_chain_is_accepted(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    active = _seed_active_file(root, "agent_runtime/demo.py", "print('ok')\n")
    report = _minimal_capability_report(evidence=[str(active.relative_to(root))])
    report["capabilities"][0] = apply_current_evidence_policy(root, report["capabilities"][0])
    _seed_canonical_report(root, report)
    write_capability_current_evidence_chain(root, capability_report=report)

    alias = base / "current_evidence_chain_now.yml"
    alias.write_text((base / CHAIN_FILENAME).read_text(encoding="utf-8"), encoding="utf-8")

    verification = verify_capability_current_evidence_chain(root)
    assert verification["status"] == "fail"
    reasons = {issue.get("reason") for issue in verification["issues"]}
    assert "duplicate_current_chain" in reasons


def test_nested_yaml_duplicate_chain_is_rejected(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    active = _seed_active_file(root, "config/demo.yml", "ok: true\n")
    report = _minimal_capability_report(evidence=[str(active.relative_to(root))])
    report["capabilities"][0] = apply_current_evidence_policy(root, report["capabilities"][0])
    _seed_canonical_report(root, report)
    write_capability_current_evidence_chain(root, capability_report=report)

    nested = (
        root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "snapshots"
        / "alias_chain.yaml"
    )
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "report_type": REPORT_TYPE,
                "chain_id": "some_other_id",
                "current_evidence": [],
                "aggregate_digest": "0" * 64,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    verification = verify_capability_current_evidence_chain(root)
    assert verification["status"] == "fail"
    assert any(issue.get("reason") == "duplicate_current_chain" for issue in verification["issues"])


def test_tampered_missing_or_hash_mismatched_evidence_fails_closed(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    active = _seed_active_file(root, "config/demo.yml", "ok: true\n")
    report = _minimal_capability_report(evidence=[str(active.relative_to(root))])
    report["capabilities"][0] = apply_current_evidence_policy(root, report["capabilities"][0])
    _seed_canonical_report(root, report)
    chain = write_capability_current_evidence_chain(root, capability_report=report)
    assert chain["status"] == "pass"
    assert verify_capability_current_evidence_chain(root)["status"] == "pass"

    active.write_text("tampered\n", encoding="utf-8")
    mismatch = verify_capability_current_evidence_chain(root)
    assert mismatch["status"] == "fail"
    assert any(
        issue.get("reason") == "current_evidence_hash_mismatch" for issue in mismatch["issues"]
    )

    active.write_text("ok: true\n", encoding="utf-8")
    write_capability_current_evidence_chain(root, capability_report=report)
    active.unlink()
    missing = verify_capability_current_evidence_chain(root)
    assert missing["status"] == "fail"
    assert any(
        issue.get("reason") in {"current_evidence_missing", "current_evidence_set_mismatch"}
        for issue in missing["issues"]
    )

    active = _seed_active_file(root, "config/demo.yml", "ok: true\n")
    write_capability_current_evidence_chain(root, capability_report=report)
    chain_file = base / CHAIN_FILENAME
    loaded = yaml.safe_load(chain_file.read_text(encoding="utf-8"))
    loaded["aggregate_digest"] = "0" * 64
    chain_file.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    bad_digest = verify_capability_current_evidence_chain(root)
    assert bad_digest["status"] == "fail"
    assert any(issue.get("reason") == "aggregate_digest_mismatch" for issue in bad_digest["issues"])


def test_source_path_substitution_fails_closed(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    active = _seed_active_file(root, "agent_runtime/a.py", "a=1\n")
    report = _minimal_capability_report(evidence=[str(active.relative_to(root))])
    report["capabilities"][0] = apply_current_evidence_policy(root, report["capabilities"][0])
    _seed_canonical_report(root, report)
    write_capability_current_evidence_chain(root, capability_report=report)

    chain_file = root / "acceptance_runs" / "agentlab_capability_acceptance" / CHAIN_FILENAME
    loaded = yaml.safe_load(chain_file.read_text(encoding="utf-8"))
    alt = root / "acceptance_runs" / "agentlab_capability_acceptance" / "alternate.yml"
    alt.write_text((root / CANONICAL_SOURCE_REL).read_text(encoding="utf-8"), encoding="utf-8")
    loaded["source_report"]["path"] = (
        "acceptance_runs/agentlab_capability_acceptance/alternate.yml"
    )
    loaded["source_report"]["sha256"] = sha256_file(alt)
    chain_file.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    verification = verify_capability_current_evidence_chain(root)
    assert verification["status"] == "fail"
    assert any(
        issue.get("reason") == "source_report_path_not_canonical"
        for issue in verification["issues"]
    )


def test_evidence_set_capability_id_substitution_with_recomputed_digest_fails(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _seed_config(root)
    active_a = _seed_active_file(root, "agent_runtime/a.py", "a=1\n")
    active_b = _seed_active_file(root, "config/b.yml", "b: 2\n")
    report = _minimal_capability_report(
        evidence=[str(active_a.relative_to(root)), str(active_b.relative_to(root))]
    )
    report["capabilities"][0] = apply_current_evidence_policy(root, report["capabilities"][0])
    _seed_canonical_report(root, report)
    write_capability_current_evidence_chain(root, capability_report=report)

    chain_file = root / "acceptance_runs" / "agentlab_capability_acceptance" / CHAIN_FILENAME
    loaded = yaml.safe_load(chain_file.read_text(encoding="utf-8"))
    # Drop one evidence path and recompute digest so a naive digest check would pass.
    loaded["current_evidence"] = [
        item
        for item in loaded["current_evidence"]
        if item["path"] != str(active_b.relative_to(root))
    ]
    for item in loaded["current_evidence"]:
        item["capability_ids"] = ["substituted_capability"]
    loaded["aggregate_digest"] = compute_aggregate_digest(
        [{"path": item["path"], "sha256": item["sha256"]} for item in loaded["current_evidence"]]
    )
    chain_file.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    verification = verify_capability_current_evidence_chain(root)
    assert verification["status"] == "fail"
    reasons = {issue.get("reason") for issue in verification["issues"]}
    assert "current_evidence_set_mismatch" in reasons or "aggregate_digest_mismatch" in reasons
    assert (
        "current_evidence_capability_ids_mismatch" in reasons
        or "current_evidence_set_mismatch" in reasons
    )


def test_absolute_root_escape_symlink_directory_evidence_rejected(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    active = _seed_active_file(root, "config/ok.yml", "ok: true\n")
    outside = tmp_path.parent / f"outside-{tmp_path.name}.yml"
    outside.write_text("outside\n", encoding="utf-8")
    directory = root / "config" / "subdir"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "nested.yml").write_text("nested\n", encoding="utf-8")
    link = root / "config" / "linked.yml"
    link.symlink_to(active)

    report = _minimal_capability_report(
        evidence=[
            str(active.relative_to(root)),
            str(active),  # absolute paths are rejected even when under root
            str(outside),  # absolute outside root
            "../escape.yml",
            "config/subdir",  # directory
            "config/linked.yml",  # symlink
        ]
    )
    gated = apply_current_evidence_policy(root, report["capabilities"][0])
    assert gated["evidence"] == [str(active.relative_to(root))]
    assert gated["status"] == "fail"  # missing/unsafe paths prevent pass

    report["capabilities"][0] = gated
    report["overall_status"] = gated["status"]
    _seed_canonical_report(root, report)
    chain = write_capability_current_evidence_chain(root, capability_report=report)
    paths = {item["path"] for item in chain["current_evidence"]}
    assert str(active.relative_to(root)) in paths
    assert str(outside) not in paths
    assert "../escape.yml" not in paths
    assert "config/subdir" not in paths
    assert "config/linked.yml" not in paths


def test_parent_symlink_evidence_is_rejected(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    target = root / "real"
    target.mkdir()
    (target / "evidence.yml").write_text("status: pass\n", encoding="utf-8")
    (root / "linked").symlink_to(target, target_is_directory=True)

    gated = apply_current_evidence_policy(
        root,
        _minimal_capability_report(evidence=["linked/evidence.yml"])["capabilities"][0],
    )

    assert gated["status"] == "fail"
    assert gated["evidence"] == []


def test_verifier_rejects_noncanonical_chain_file_without_reading_it(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _seed_config(root)
    external = tmp_path.parent / f"{tmp_path.name}-external-chain.yml"
    external.write_text("not: [valid", encoding="utf-8")

    verification = verify_capability_current_evidence_chain(
        root,
        chain_file=external,
    )

    assert verification["status"] == "fail"
    assert verification["issues"] == [
        {
            "reason": "chain_path_not_canonical",
            "expected": (
                "acceptance_runs/agentlab_capability_acceptance/"
                "current_evidence_chain.yml"
            ),
            "actual": str(external),
        }
    ]


def test_historical_capability_id_substitution_is_rejected(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    active = _seed_active_file(root, "agent_runtime/a.py", "a=1\n")
    historical = _seed_active_file(
        root,
        "projects/AgentLab/archive/run_history/old/runs/task/x.yml",
        "old\n",
    )
    report = _minimal_capability_report(
        evidence=[
            str(active.relative_to(root)),
            str(historical.relative_to(root)),
        ]
    )
    report["capabilities"][0] = apply_current_evidence_policy(
        root,
        report["capabilities"][0],
    )
    _seed_canonical_report(root, report)
    write_capability_current_evidence_chain(root, capability_report=report)
    chain_file = (
        root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / CHAIN_FILENAME
    )
    loaded = yaml.safe_load(chain_file.read_text(encoding="utf-8"))
    loaded["historical_references"][0]["capability_ids"] = ["forged"]
    chain_file.write_text(
        yaml.safe_dump(loaded, sort_keys=False),
        encoding="utf-8",
    )

    verification = verify_capability_current_evidence_chain(root)

    assert verification["status"] == "fail"
    assert any(
        issue.get("reason")
        == "historical_reference_capability_ids_mismatch"
        for issue in verification["issues"]
    )


def test_metadata_retired_or_superseded_evidence_rejected(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    _seed_active_file(root, "config/active.yml", "status: pass\nvalue: 1\n")
    retired = root / "config" / "retired.yml"
    retired.parent.mkdir(parents=True, exist_ok=True)
    retired.write_text("status: retired\nvalue: old\n", encoding="utf-8")
    superseded = root / "config" / "superseded.yml"
    superseded.write_text("status: superseded\nvalue: old\n", encoding="utf-8")

    report = _minimal_capability_report(
        evidence=[
            "config/active.yml",
            "config/retired.yml",
            "config/superseded.yml",
        ]
    )
    gated = apply_current_evidence_policy(root, report["capabilities"][0])
    assert gated["evidence"] == ["config/active.yml"]
    assert gated["status"] == "fail"
    report["capabilities"][0] = gated
    _seed_canonical_report(root, report)
    chain = write_capability_current_evidence_chain(root, capability_report=report)
    paths = {item["path"] for item in chain["current_evidence"]}
    assert paths == {"config/active.yml"}


def test_clean_newly_generated_chain_passes(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    active_a = _seed_active_file(root, "agent_runtime/a.py", "a=1\n")
    active_b = _seed_active_file(root, "config/b.yml", "b: 2\n")
    historical = _seed_active_file(
        root,
        "projects/AgentLab/archive/run_history/old/runs/task/x.yml",
        "old\n",
    )
    report = _minimal_capability_report(
        evidence=[
            str(active_a.relative_to(root)),
            str(active_b.relative_to(root)),
            str(historical.relative_to(root)),
        ]
    )
    report["capabilities"][0] = apply_current_evidence_policy(root, report["capabilities"][0])
    report["overall_status"] = report["capabilities"][0]["status"]
    _seed_canonical_report(root, report)

    chain = write_capability_current_evidence_chain(root, capability_report=report)
    verification = verify_capability_current_evidence_chain(root)

    assert chain["report_type"] == REPORT_TYPE
    assert chain["chain_id"] == CHAIN_ID
    assert chain["status"] == "pass"
    assert verification["status"] == "pass"
    assert verification["issues"] == []
    paths = {item["path"] for item in chain["current_evidence"]}
    assert str(active_a.relative_to(root)) in paths
    assert str(active_b.relative_to(root)) in paths
    assert str(historical.relative_to(root)) not in paths
    assert any(
        item["path"] == str(historical.relative_to(root))
        for item in chain["historical_references"]
    )
    expected_aggregate = compute_aggregate_digest(
        [{"path": item["path"], "sha256": item["sha256"]} for item in chain["current_evidence"]]
    )
    assert chain["aggregate_digest"] == expected_aggregate
    assert chain["source_report"]["path"] == CANONICAL_SOURCE_REL
    assert chain["source_report"]["sha256"] == sha256_file(base / "current.yml")


def test_arbitrary_report_out_does_not_mutate_canonical_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path
    _seed_config(root)
    from agent_runtime import capability_acceptance as acceptance_mod
    from agent_runtime.capability_evidence_chain import chain_path

    fake = _minimal_capability_report(evidence=["config/demo.yml"])
    _seed_active_file(root, "config/demo.yml", "ok: true\n")
    monkeypatch.setattr(
        acceptance_mod,
        "build_capability_acceptance_report",
        lambda _root: fake,
    )
    canonical_chain = chain_path(root)
    assert not canonical_chain.exists()
    out = tmp_path / "arbitrary-report.yml"
    acceptance_mod.write_capability_acceptance_report(
        root, out, write_evidence_chain=True
    )
    assert out.exists()
    assert not canonical_chain.exists()


def _typer_app_with_root(root: Path):
    import typer
    from rich.console import Console
    from agent_runtime.cli.capability_acceptance import register_capability_acceptance_commands

    local = typer.Typer()
    register_capability_acceptance_commands(local, root, Console())
    return local


def test_capability_current_evidence_chain_cli_write_and_verify(tmp_path: Path) -> None:
    root = tmp_path
    _seed_config(root)
    active = _seed_active_file(root, "config/demo.yml", "ok: true\n")
    report = _minimal_capability_report(evidence=[str(active.relative_to(root))])
    report["capabilities"][0] = apply_current_evidence_policy(root, report["capabilities"][0])
    _seed_canonical_report(root, report)

    local_app = _typer_app_with_root(root)
    result = runner.invoke(
        local_app,
        ["capability-current-evidence-chain", "--write", "--verify"],
    )
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    chain_file = root / "acceptance_runs" / "agentlab_capability_acceptance" / CHAIN_FILENAME
    assert chain_file.is_file()
    verification = verify_capability_current_evidence_chain(root)
    assert verification["status"] == "pass"


def test_capability_acceptance_arbitrary_out_cli_does_not_write_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path
    _seed_config(root)
    from agent_runtime import capability_acceptance as acceptance_mod

    fake = _minimal_capability_report(status="pass", evidence=["config/demo.yml"])
    _seed_active_file(root, "config/demo.yml", "ok: true\n")
    monkeypatch.setattr(
        acceptance_mod,
        "build_capability_acceptance_report",
        lambda _root: fake,
    )
    out = tmp_path / "out.yml"
    local_app = _typer_app_with_root(root)
    result = runner.invoke(
        local_app,
        ["capability-acceptance", "--out", str(out), "--write-evidence-chain"],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    chain_file = root / "acceptance_runs" / "agentlab_capability_acceptance" / CHAIN_FILENAME
    assert not chain_file.exists()



def test_capability_current_evidence_chain_cli_help_registered() -> None:
    result = runner.invoke(app, ["capability-current-evidence-chain", "--help"])
    assert result.exit_code == 0, result.output
    help_text = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--write" in help_text
    assert "--verify" in help_text


def test_aggregate_digest_is_order_independent() -> None:
    items_a = [
        {"path": "b.yml", "sha256": "bb"},
        {"path": "a.yml", "sha256": "aa"},
    ]
    items_b = [
        {"path": "a.yml", "sha256": "aa"},
        {"path": "b.yml", "sha256": "bb"},
    ]
    assert compute_aggregate_digest(items_a) == compute_aggregate_digest(items_b)
    body = "a.yml:aa\nb.yml:bb\n"
    assert compute_aggregate_digest(items_a) == hashlib.sha256(body.encode("utf-8")).hexdigest()
