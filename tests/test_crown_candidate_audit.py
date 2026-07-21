from __future__ import annotations

from pathlib import Path
import hashlib

import pytest
import yaml
from typer.testing import CliRunner

import agent_runtime.crown_candidate_audit as crown_audit_module
from agent_runtime.crown_candidate_audit import (
    build_crown_completion_batch_audit,
    build_crown_live_candidate_audit,
)
from agent_runtime.narrative.production.revision_attempts import (
    reserve_revision_attempt,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_crown_live_candidate_audit_checks_candidate_integrity(
    private_crown_project_root: Path,
) -> None:
    report = build_crown_live_candidate_audit(private_crown_project_root)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "pass"
    assert by_id["required_files_present"]["status"] == "pass"
    assert by_id["delivery_protocol_valid"]["status"] == "pass"
    assert by_id["draft_substantial"]["metrics"]["lines"] >= 100
    assert by_id["chapter_packet_reset_baseline"]["status"] == "pass"
    assert by_id["state_transition_candidate_only"]["status"] == "pass"
    assert by_id["production_manuscript_not_modified"]["status"] == "pass"
    assert report["summary"]["candidate_only"] is True


def test_crown_live_candidate_audit_cli_writes_yaml(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "crown_live_candidate_audit.yml"

    result = runner.invoke(app, ["crown-live-candidate-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_crown_live_candidate_audit"
    assert report["status"] == "pass"


@pytest.mark.parametrize(
    ("job_kind", "run_mode", "identity_status"),
    [
        ("narrative_generation", "generate_candidate", "pass"),
        ("narrative_revision", "targeted_rewrite", "pass"),
        ("narrative_revision", "generate_candidate", "fail"),
        ("narrative_generation", "targeted_rewrite", "fail"),
    ],
)
def test_crown_live_candidate_audit_uses_v2_prose_only_contract(
    tmp_path: Path,
    job_kind: str,
    run_mode: str,
    identity_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "task_narrative_v2_gate1_preflight_ch025"
    project_root = tmp_path / "projects" / "Crown_of_Ash"
    run_dir = project_root / "runs" / task_id
    brief = project_root / "candidates" / "gate1" / "brief_ch025.yml"
    run_dir.mkdir(parents=True)
    brief.parent.mkdir(parents=True)
    brief.write_text(
        yaml.safe_dump(
            {
                "chapter": 25,
                "pov": "Kane",
                "scene_goal": "verify the map",
                "irreversible_plot_change": "the forged route is exposed",
                "closing_state": "trust has a price",
                "character_state_change": "Kane chooses verification",
                "reader_question": "Who forged it?",
                "target_character_range": [4500, 5500],
                "must_preserve": ["Kane reasons from evidence"],
                "creative_freedom": ["dialogue rhythm"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    brief_ref = {
        "path": brief.relative_to(tmp_path).as_posix(),
        "sha256": hashlib.sha256(brief.read_bytes()).hexdigest(),
    }
    request = {
        "schema_version": 1,
        "job_kind": job_kind,
        "run_mode": run_mode,
        "project": "Crown_of_Ash",
        "task_id": task_id,
        "chapter_id": 25,
        "candidate_only": True,
        "production_modified": False,
        "external_context_approval_required": True,
        "creative_brief_source": brief_ref,
    }
    revision_identity = {}
    if job_kind == "narrative_revision":
        evidence_dir = project_root / "candidates" / "gate1" / "evidence"
        evidence_dir.mkdir(parents=True)
        evidence_refs = {}
        for name in (
            "source_candidate",
            "triggering_audit",
            "revision_contract",
        ):
            evidence_path = evidence_dir / f"{name}.yml"
            evidence_path.write_text(f"kind: {name}\n", encoding="utf-8")
            evidence_refs[name] = {
                "path": evidence_path.relative_to(tmp_path).as_posix(),
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
        reservation = reserve_revision_attempt(
            root=tmp_path,
            project="Crown_of_Ash",
            candidate_set_id="candidate-set-1",
            source_job_id="source-job-1",
            source_run_id="source-run-1",
            triggered_by_audit_id="audit-1",
            task_id=task_id,
            attempt_id="attempt-0001",
            lease_token="lease-1",
            lease_expires_at="2030-01-01T00:00:00+00:00",
            preflight_spec_sha256="e" * 64,
            claimed_rewrite_count=0,
            source_candidate_sha256=evidence_refs["source_candidate"]["sha256"],
            triggering_audit_sha256=evidence_refs["triggering_audit"]["sha256"],
            revision_contract_sha256=evidence_refs["revision_contract"]["sha256"],
        )
        attempt_receipt = reservation.receipt_path
        attempt_receipt_bytes = attempt_receipt.read_bytes()
        revision_identity = {
            "candidate_set_id": "candidate-set-1",
            "source_job_id": "source-job-1",
            "source_run_id": "source-run-1",
            "triggered_by_audit_id": "audit-1",
            "attempt_id": "attempt-0001",
            "lease_token": "lease-1",
            "lease_expires_at": "2030-01-01T00:00:00+00:00",
            "automatic_rewrite_count": 0,
            "automatic_rewrite_number": 1,
            "fencing_token": reservation.fencing_token,
            "attempt_receipt": reservation.reference(tmp_path),
            **evidence_refs,
        }
        request.update(revision_identity)
    request_path = run_dir / "narrative_v2_writer_request.yml"
    request_path.write_text(
        yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
    )
    prose = "# 第二十五章 · 心之遗物\n\n" + ("字" * 5501) + "\n"
    draft = run_dir / "fiction_draft.md"
    draft.write_text(prose, encoding="utf-8")
    prose_hash = hashlib.sha256(draft.read_bytes()).hexdigest()
    session = {
        **{key: request[key] for key in (
            "schema_version",
            "job_kind",
            "run_mode",
            "project",
            "task_id",
            "chapter_id",
            "candidate_only",
            "production_modified",
            "external_context_approval_required",
        )},
        **revision_identity,
        "status": "pass",
        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        "compiled_packet_sha256": "a" * 64,
        "prose_length_contract": {
            "unit": "han_characters_excluding_markdown_headings",
            "minimum": 4500,
            "maximum": 5500,
        },
    }
    session_path = run_dir / "narrative_v2_writer_session_receipt.yml"
    session_path.write_text(
        yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
    )
    (run_dir / "writer_v2_output_contract.yml").write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "candidate_only": True,
                "production_modified": False,
                "issues": [],
                "prose_sha256": prose_hash,
                "writer_execution_receipt": "writer_execution_receipt.yml",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "writer_execution_receipt.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "issuer": "AgentLab",
                "issuer_role": "writer_contract_validator",
                "prose_sha256": prose_hash,
                "observed_provider": "agentlab-cli-executor",
                "observed_model": "deepseek-v4-pro",
                "observed_call_id": "cmd-v2-audit",
                "writer_cannot_overwrite": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "fail"
    assert report["contract_version"] == 2
    assert report["candidate_sha256"] == prose_hash
    assert "required_files_present" not in by_id
    assert by_id["v2_prose_only_artifacts"]["status"] == "pass"
    assert by_id["v2_session_identity_and_request_hash"]["status"] == identity_status
    assert by_id["prose_length_contract"]["status"] == "fail"
    assert by_id["prose_length_contract"]["observed"] == 5501

    if identity_status == "pass":
        for key, spoofed in {
            "schema_version": True,
            "candidate_only": 1,
            "production_modified": 0,
            "external_context_approval_required": 1,
        }.items():
            original_request = request[key]
            original_session = session[key]
            request[key] = spoofed
            session[key] = spoofed
            request_path.write_text(
                yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
            )
            session["request_sha256"] = hashlib.sha256(
                request_path.read_bytes()
            ).hexdigest()
            session_path.write_text(
                yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
            )
            spoofed_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
            spoofed_by_id = {item["id"]: item for item in spoofed_report["checks"]}
            assert spoofed_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
            request[key] = original_request
            session[key] = original_session
        request_path.write_text(
            yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
        )
        session["request_sha256"] = hashlib.sha256(
            request_path.read_bytes()
        ).hexdigest()

        request_bytes = request_path.read_bytes()
        outside_request = tmp_path.parent / f"{tmp_path.name}-outside-request.yml"
        outside_request.write_bytes(request_bytes)
        request_path.unlink()
        request_path.symlink_to(outside_request)
        request_link_report = build_crown_live_candidate_audit(
            tmp_path,
            task_id=task_id,
        )
        request_link_by_id = {
            item["id"]: item for item in request_link_report["checks"]
        }
        assert request_link_by_id["v2_prose_only_artifacts"]["status"] == "fail"
        assert "narrative_v2_writer_request.yml" in request_link_by_id[
            "v2_prose_only_artifacts"
        ]["missing"]
        request_path.unlink()
        request_path.write_bytes(request_bytes)

        draft_bytes = draft.read_bytes()
        outside_draft = tmp_path.parent / f"{tmp_path.name}-outside-draft.md"
        outside_draft.write_bytes(draft_bytes)
        draft.unlink()
        draft.symlink_to(outside_draft)
        draft_link_report = build_crown_live_candidate_audit(
            tmp_path,
            task_id=task_id,
        )
        draft_link_by_id = {
            item["id"]: item for item in draft_link_report["checks"]
        }
        assert draft_link_by_id["v2_prose_only_artifacts"]["status"] == "fail"
        assert "fiction_draft.md" in draft_link_by_id["v2_prose_only_artifacts"][
            "missing"
        ]
        draft.unlink()
        draft.write_bytes(draft_bytes)

        if job_kind == "narrative_generation":
            request_path.write_text(
                yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
            )
            request_bytes = request_path.read_bytes()
            session["request_sha256"] = hashlib.sha256(request_bytes).hexdigest()
            session_path.write_text(
                yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
            )
            mutated_request = {**request, "job_kind": "code_generation"}
            mutated_request_bytes = yaml.safe_dump(
                mutated_request,
                sort_keys=False,
            ).encode("utf-8")
            session["request_sha256"] = hashlib.sha256(
                mutated_request_bytes
            ).hexdigest()
            session_path.write_text(
                yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
            )
            original_reader = crown_audit_module._root_snapshot_bytes
            request_mutated = False

            def mutate_request_after_snapshot(root: Path, path: Path) -> bytes | None:
                nonlocal request_mutated
                raw = original_reader(root, path)
                if path == request_path and not request_mutated:
                    request_mutated = True
                    request_path.write_bytes(mutated_request_bytes)
                return raw

            with monkeypatch.context() as patch_context:
                patch_context.setattr(
                    crown_audit_module,
                    "_root_snapshot_bytes",
                    mutate_request_after_snapshot,
                )
                request_mutation_report = build_crown_live_candidate_audit(
                    tmp_path,
                    task_id=task_id,
                )
            request_mutation_by_id = {
                item["id"]: item for item in request_mutation_report["checks"]
            }
            assert request_mutation_report["status"] == "fail"
            assert request_mutation_by_id["v2_artifact_snapshot_stable"][
                "status"
            ] == "fail"
            request_path.write_bytes(request_bytes)

            session["request_sha256"] = hashlib.sha256(request_bytes).hexdigest()
            session_path.write_text(
                yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
            )
            mutated_draft_bytes = draft_bytes + "变".encode("utf-8")
            draft_mutated = False

            def mutate_draft_after_snapshot(root: Path, path: Path) -> bytes | None:
                nonlocal draft_mutated
                raw = original_reader(root, path)
                if path == draft and not draft_mutated:
                    draft_mutated = True
                    draft.write_bytes(mutated_draft_bytes)
                return raw

            with monkeypatch.context() as patch_context:
                patch_context.setattr(
                    crown_audit_module,
                    "_root_snapshot_bytes",
                    mutate_draft_after_snapshot,
                )
                draft_mutation_report = build_crown_live_candidate_audit(
                    tmp_path,
                    task_id=task_id,
                )
            draft_mutation_by_id = {
                item["id"]: item for item in draft_mutation_report["checks"]
            }
            assert draft_mutation_by_id["v2_artifact_snapshot_stable"][
                "status"
            ] == "fail"
            draft.write_bytes(draft_bytes)

    if job_kind == "narrative_revision" and run_mode == "targeted_rewrite":
        for key in revision_identity:
            request_value = request.pop(key)
            session_value = session.pop(key)
            request_path.write_text(
                yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
            )
            session["request_sha256"] = hashlib.sha256(
                request_path.read_bytes()
            ).hexdigest()
            session_path.write_text(
                yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
            )
            missing_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
            missing_by_id = {item["id"]: item for item in missing_report["checks"]}
            assert missing_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
            request[key] = request_value
            session[key] = session_value
        request_path.write_text(
            yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
        )
        session["request_sha256"] = hashlib.sha256(
            request_path.read_bytes()
        ).hexdigest()

        session["candidate_set_id"] = "different-candidate-set"
        session_path.write_text(
            yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
        )
        mismatch_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
        mismatch_by_id = {item["id"]: item for item in mismatch_report["checks"]}
        assert mismatch_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
        session["candidate_set_id"] = request["candidate_set_id"]

        attempt_receipt.write_text("status: tampered\n", encoding="utf-8")
        session_path.write_text(
            yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
        )
        stale_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
        stale_by_id = {item["id"]: item for item in stale_report["checks"]}
        assert stale_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
        attempt_receipt.write_bytes(attempt_receipt_bytes)

        original_receipt_ref = request["attempt_receipt"]
        alias_receipt = project_root / "candidates" / "not-a-ledger-receipt.yml"
        alias_receipt.write_bytes(attempt_receipt_bytes)
        alias_ref = {
            "path": alias_receipt.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(alias_receipt.read_bytes()).hexdigest(),
        }
        request["attempt_receipt"] = alias_ref
        session["attempt_receipt"] = alias_ref
        request_path.write_text(
            yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
        )
        session["request_sha256"] = hashlib.sha256(
            request_path.read_bytes()
        ).hexdigest()
        session_path.write_text(
            yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
        )
        alias_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
        alias_by_id = {item["id"]: item for item in alias_report["checks"]}
        assert alias_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
        request["attempt_receipt"] = original_receipt_ref
        session["attempt_receipt"] = original_receipt_ref

        original_audit_id = request["triggered_by_audit_id"]
        request["triggered_by_audit_id"] = request["source_run_id"]
        session["triggered_by_audit_id"] = request["source_run_id"]
        request_path.write_text(
            yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
        )
        session["request_sha256"] = hashlib.sha256(
            request_path.read_bytes()
        ).hexdigest()
        session_path.write_text(
            yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
        )
        same_run_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
        same_run_by_id = {item["id"]: item for item in same_run_report["checks"]}
        assert same_run_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
        request["triggered_by_audit_id"] = original_audit_id
        session["triggered_by_audit_id"] = original_audit_id

        request["automatic_rewrite_number"] = True
        session["automatic_rewrite_number"] = True
        request_path.write_text(
            yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
        )
        session["request_sha256"] = hashlib.sha256(
            request_path.read_bytes()
        ).hexdigest()
        session_path.write_text(
            yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
        )
        bool_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
        bool_by_id = {item["id"]: item for item in bool_report["checks"]}
        assert bool_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
        request["automatic_rewrite_number"] = 1
        session["automatic_rewrite_number"] = 1

        session["automatic_rewrite_count"] = False
        session["automatic_rewrite_number"] = True
        request_path.write_text(
            yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
        )
        session["request_sha256"] = hashlib.sha256(
            request_path.read_bytes()
        ).hexdigest()
        session_path.write_text(
            yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
        )
        session_bool_report = build_crown_live_candidate_audit(
            tmp_path,
            task_id=task_id,
        )
        session_bool_by_id = {
            item["id"]: item for item in session_bool_report["checks"]
        }
        assert session_bool_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
        session["automatic_rewrite_count"] = 0
        session["automatic_rewrite_number"] = 1

    session["chapter_id"] = 26
    session_path.write_text(
        yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
    )
    chapter_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
    chapter_by_id = {item["id"]: item for item in chapter_report["checks"]}
    assert chapter_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
    session["chapter_id"] = 25

    request["chapter_id"] = 1
    session["chapter_id"] = True
    request_path.write_text(
        yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
    )
    session["request_sha256"] = hashlib.sha256(request_path.read_bytes()).hexdigest()
    session_path.write_text(
        yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
    )
    chapter_bool_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
    chapter_bool_by_id = {
        item["id"]: item for item in chapter_bool_report["checks"]
    }
    assert chapter_bool_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
    request["chapter_id"] = 25
    session["chapter_id"] = 25

    request["job_kind"] = [job_kind]
    session["job_kind"] = [job_kind]
    request_path.write_text(
        yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
    )
    session["request_sha256"] = hashlib.sha256(request_path.read_bytes()).hexdigest()
    session_path.write_text(
        yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
    )
    malformed_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
    malformed_by_id = {item["id"]: item for item in malformed_report["checks"]}
    assert malformed_by_id["v2_session_identity_and_request_hash"]["status"] == "fail"
    request["job_kind"] = job_kind
    session["job_kind"] = job_kind
    request_path.write_text(
        yaml.safe_dump(request, sort_keys=False), encoding="utf-8"
    )
    session["request_sha256"] = hashlib.sha256(request_path.read_bytes()).hexdigest()
    session_path.write_text(
        yaml.safe_dump(session, sort_keys=False), encoding="utf-8"
    )

    forged_receipt = yaml.safe_load(
        (run_dir / "writer_execution_receipt.yml").read_text(encoding="utf-8")
    )
    forged_receipt["issuer"] = "Writer"
    forged_receipt["writer_cannot_overwrite"] = False
    (run_dir / "writer_execution_receipt.yml").write_text(
        yaml.safe_dump(forged_receipt, sort_keys=False), encoding="utf-8"
    )

    forged_report = build_crown_live_candidate_audit(tmp_path, task_id=task_id)
    forged_by_id = {item["id"]: item for item in forged_report["checks"]}

    assert forged_by_id["v2_output_contract_and_hashes"]["status"] == "fail"
    assert forged_by_id["v2_output_contract_and_hashes"][
        "agentlab_execution_receipt_valid"
    ] is False


def _write_batch_chapter(root: Path, chapter: int, eval_id: str) -> None:
    task_id = f"task_narrative_eval_ch{chapter:02d}_{eval_id}"
    run_dir = root / "projects" / "Crown_of_Ash" / "runs" / task_id
    run_dir.mkdir(parents=True)
    previous_id = f"task_narrative_eval_ch{chapter - 1:02d}_{eval_id}"
    previous = [] if chapter == 1 else [
        f"runs/{previous_id}/fiction_draft.md",
        f"runs/{previous_id}/continuity_ledger.yml",
        f"runs/{previous_id}/state_transition_proposal.yml",
    ]
    baseline = "reset" if chapter == 1 else "continuation"
    draft = f"# 第{chapter}章\n\n" + (f"正文{chapter}" * 1100)
    files = {
        "chapter_packet.yml": {
            "chapter": chapter,
            "baseline_mode": baseline,
            "previous_candidate_sources": previous,
            "chapter_intent": {"hard_character_range": [3000, 8000]},
        },
        "continuity_ledger.yml": {
            "schema_version": 1,
            "chapter": chapter,
            "baseline_mode": baseline,
            "timeline": {"monotonic": True},
            "plot_state_changes": [f"plot {chapter}"],
            "character_changes": [f"character {chapter}"],
            "relationship_or_worldline_changes": [f"worldline {chapter}"],
            "foreshadowing": [f"foreshadowing {chapter}"],
        },
        "state_transition_proposal.yml": {
            "schema_version": 1,
            "status": "candidate",
            "chapter": chapter,
            "requires_user_promotion": True,
            "events": [
                {
                    "event_type": "chapter_state_change",
                    "scope": "candidate_only",
                    "summary": f"event {chapter}",
                }
            ],
        },
        "narrative_delivery_receipt.yml": {
            "schema_version": 1,
            "status": "pass",
            "candidate_only": True,
            "checks": {
                "chapter_and_title": "pass",
                "required_beats": "pass",
                "continuity_outputs": "pass",
                "production_untouched": "pass",
                "deprecated_sources_excluded": "pass",
            },
        },
        "writer_output_contract.yml": {
            "schema_version": 1,
            "status": "pass",
            "normalizations": [],
        },
        "candidate_fact_ledger.yml": {
            "schema_version": 1,
            "status": "candidate",
            "promoted": False,
            "through_chapter": chapter - 1,
            "event_count": chapter - 1,
        },
    }
    (run_dir / "fiction_draft.md").write_text(draft, encoding="utf-8")
    for filename, data in files.items():
        (run_dir / filename).write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    log_dir = run_dir / "command_logs"
    log_dir.mkdir()
    (log_dir / "agy_cli_agent.log").write_text(
        'Propagating selected model override to backend: label="Gemini 3.5 Flash (High)"\n',
        encoding="utf-8",
    )
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(
            {
                "task_id": task_id,
                "included_agents": {"Writer": {"role_alias_of": "ArtifactProducer"}},
                "model_profiles": {
                    "Writer": {
                        "provider": "agy-gemini-oauth",
                        "model": "gemini-3.5-flash-high",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "live_writer_role_session_guard.yml").write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "role": "Writer",
                "worker": "agy",
                "project": "Crown_of_Ash",
                "task_id": task_id,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_deepseek_execution(root: Path, chapter: int, eval_id: str) -> Path:
    task_id = f"task_narrative_eval_ch{chapter:02d}_{eval_id}"
    run_dir = root / "projects" / "Crown_of_Ash" / "runs" / task_id
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(
            {
                "task_id": task_id,
                "included_agents": {"Writer": {"execution_owner": "claude_code"}},
                "model_profiles": {
                    "Writer": {"provider": "deepseek", "model": "deepseek-v4-pro"}
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "live_writer_role_session_guard.yml").write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "role": "Writer",
                "worker": "claude_code",
                "project": "Crown_of_Ash",
                "task_id": task_id,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "model_execution_chain_writer.yml").write_text(
        yaml.safe_dump(
            {
                "role": "Writer",
                "status": "pass",
                "attempts": [
                    {
                        "status": "pass",
                        "provider": "deepseek",
                        "selected_model": "deepseek-v4-pro",
                        "fallback_detected": False,
                    }
                ],
                "fallback_used": False,
                "final": {
                    "status": "pass",
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def test_crown_completion_batch_audit_checks_one_continuous_chain(tmp_path: Path) -> None:
    manuscript = tmp_path / "projects" / "Crown_of_Ash" / "production" / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / ".gitkeep").write_text("", encoding="utf-8")
    _write_batch_chapter(tmp_path, 1, "fixture")
    _write_batch_chapter(tmp_path, 2, "fixture")

    report = build_crown_completion_batch_audit(
        tmp_path,
        eval_id="fixture",
        through_chapter=2,
    )

    assert report["status"] == "pass"
    assert report["summary"]["valid_chapter_count"] == 2
    assert report["summary"]["total_candidate_events"] == 2
    assert report["summary"]["production_manuscript_files"] == []
    assert report["warnings"] == []
    assert report["issues"] == []


def test_crown_completion_batch_audit_accepts_declared_deepseek_writer(
    tmp_path: Path,
) -> None:
    manuscript = tmp_path / "projects" / "Crown_of_Ash" / "production" / "manuscript"
    manuscript.mkdir(parents=True)
    _write_batch_chapter(tmp_path, 1, "fixture")
    _write_deepseek_execution(tmp_path, 1, "fixture")

    report = build_crown_completion_batch_audit(
        tmp_path,
        eval_id="fixture",
        through_chapter=1,
    )

    assert report["status"] == "pass"
    execution = report["chapters"][0]["writer_execution"]
    assert execution["status"] == "pass"
    assert execution["mode"] == "model_execution_chain"
    assert execution["expected"] == execution["observed"]


def test_crown_completion_batch_audit_rejects_writer_model_fallback(
    tmp_path: Path,
) -> None:
    manuscript = tmp_path / "projects" / "Crown_of_Ash" / "production" / "manuscript"
    manuscript.mkdir(parents=True)
    _write_batch_chapter(tmp_path, 1, "fixture")
    run_dir = _write_deepseek_execution(tmp_path, 1, "fixture")
    chain_path = run_dir / "model_execution_chain_writer.yml"
    chain = yaml.safe_load(chain_path.read_text(encoding="utf-8"))
    chain["fallback_used"] = True
    chain_path.write_text(yaml.safe_dump(chain, sort_keys=False), encoding="utf-8")

    report = build_crown_completion_batch_audit(
        tmp_path,
        eval_id="fixture",
        through_chapter=1,
    )

    assert report["status"] == "fail"
    execution = report["chapters"][0]["writer_execution"]
    assert execution["status"] == "fail"
    assert execution["issues"] == ["model_chain_fallback"]
    assert "writer_execution_contract" in report["chapters"][0]["issues"]


def test_crown_completion_batch_audit_rejects_cross_chapter_passage_reuse(
    tmp_path: Path,
) -> None:
    manuscript = tmp_path / "projects" / "Crown_of_Ash" / "production" / "manuscript"
    manuscript.mkdir(parents=True)
    _write_batch_chapter(tmp_path, 1, "fixture")
    _write_batch_chapter(tmp_path, 2, "fixture")
    runs = tmp_path / "projects" / "Crown_of_Ash" / "runs"
    first = runs / "task_narrative_eval_ch01_fixture" / "fiction_draft.md"
    second = runs / "task_narrative_eval_ch02_fixture" / "fiction_draft.md"
    repeated_body = first.read_text(encoding="utf-8").split("\n", 2)[-1]
    second.write_text(f"# 第2章\n\n{repeated_body}", encoding="utf-8")

    report = build_crown_completion_batch_audit(
        tmp_path,
        eval_id="fixture",
        through_chapter=2,
    )

    assert report["status"] == "fail"
    assert report["summary"]["repetition_failure_count"] == 1
    assert report["repetition_findings"][0]["chapter"] == 2
    assert report["repetition_findings"][0]["source_chapter"] == 1
    assert report["repetition_findings"][0]["blocking"] is True
    assert "cross_chapter_repetition" in report["chapters"][1]["issues"]
