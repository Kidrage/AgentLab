from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import yaml

from agent_runtime.background_job_controller import (
    load_job_state,
    create_crown_delivery_job,
    schedule_next_attempt,
    write_process_receipt,
    consume_process_receipt,
)
from agent_runtime.background_job_worker import execute_action
from agent_runtime.narrative.diagnostics.baseline import (
    aggregate_case_metrics,
    build_efficiency_baseline,
    collect_background_job_metrics,
    collect_run_metrics,
)
from agent_runtime.narrative.diagnostics.telemetry import (
    NARRATIVE_DIAGNOSTICS_ENV,
    record_narrative_invocation,
)
from agent_runtime.narrative.audit.precheck import run_deterministic_precheck
from agent_runtime.narrative.audit.execution import execute_tiered_audit
from agent_runtime.narrative.audit.background import run_tiered_followup
from agent_runtime.narrative.audit.runtime import run_revision_support_pipeline
from agent_runtime.narrative.efficiency.context_bundle import build_context_bundle
from agent_runtime.narrative.efficiency.planning import (
    compute_incremental_audit_window,
    plan_chapter_execution,
)
from agent_runtime.narrative.production.brief_compiler import (
    CreativeBrief,
    validate_creative_brief,
)
from agent_runtime.narrative.production.context_compiler import (
    ContextCompiler,
    ContextRequest,
    ContextResult,
)
from agent_runtime.schemas import LLMCallResult


def _plan(run_dir: Path, route_key: str = "narrative_heavy_audit") -> SimpleNamespace:
    return SimpleNamespace(
        run_dir=str(run_dir),
        task_id="task_narrative_probe",
        project="ProbeNovel",
        route=SimpleNamespace(route_key=route_key),
    )


def test_narrative_invocation_telemetry_is_opt_in(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(NARRATIVE_DIAGNOSTICS_ENV, raising=False)

    event = record_narrative_invocation(
        _plan(tmp_path),
        "Writer",
        LLMCallResult(provider="test", model="test-model", content="draft prose"),
        provider_surface="cli_agent:test",
    )

    assert event is None
    assert not (tmp_path / "narrative_invocations.jsonl").exists()


def test_narrative_invocation_telemetry_preserves_failed_paid_call_without_prose(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(NARRATIVE_DIAGNOSTICS_ENV, "1")
    manifest_path = tmp_path / "outbound_context_manifest_writer.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "payload": {"bytes": 1234, "sha256": "packet-sha"},
                "source_inventory": {
                    "count": 2,
                    "files": [
                        {"path": "canon.md", "bytes": 300, "sha256": "canon-sha"},
                        {"path": "chapter.md", "bytes": 700, "sha256": "chapter-sha"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    receipt_path = tmp_path / "model_execution_receipt_writer.yml"
    receipt_path.write_text(
        yaml.safe_dump(
            {
                "selected_provider": "deepseek",
                "selected_model_id": "deepseek-v4-pro",
                "provider_reported_primary_model_id": "deepseek-v4-pro-202607",
                "provider_reported_session_id": "session-1",
                "provider_process_started": True,
                "attempt_id": "attempt-1",
                "provider_reported_usage": {
                    "input_tokens": 1200,
                    "output_tokens": 400,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 10,
                    "total_tokens": 1810,
                    "estimated_cost": 0.42,
                    "cost_currency": "USD",
                    "usage_source": "external_cli_reported",
                },
            }
        ),
        encoding="utf-8",
    )
    result = LLMCallResult(
        provider="claude_code",
        model="deepseek-v4-pro",
        content="UNPUBLISHED DRAFT PROSE MUST NOT BE LOGGED",
        status="fallback_handoff",
        error="schema parse failed after provider returned",
        input_tokens=1200,
        output_tokens=400,
        total_tokens=1810,
        raw_usage={
            "duration_s": 12.5,
            "model_execution_receipt": str(receipt_path),
            "outbound_context_manifest": str(manifest_path),
            "failure_class": "schema_parse_failed",
        },
    )

    event = record_narrative_invocation(
        _plan(tmp_path),
        "Writer",
        result,
        provider_surface="cli_agent:claude_code",
        capacity_route="Writer",
        local_orchestration_seconds=1.25,
    )

    assert event is not None
    assert event["task"]["id"] == "task_narrative_probe"
    assert event["attempt"]["id"] == "attempt-1"
    error = "schema parse failed after provider returned"
    assert event["result"] == {
        "status": "fallback_handoff",
        "error_present": True,
        "error_chars": len(error),
        "error_sha256": hashlib.sha256(error.encode("utf-8")).hexdigest(),
        "failure_class": "schema_parse_failed",
    }
    assert event["requested_agent"] == "agentlab"
    assert event["invoked_agent"] == "claude_code"
    assert event["reporting_agent"] == "agentlab"
    assert event["timing"] == {
        "model_active_seconds": None,
        "model_active_measurement": "unavailable_from_provider",
        "provider_process_wall_seconds": 12.5,
        "provider_process_measurement": "external_cli_process_wall",
        "local_orchestration_seconds": 1.25,
        "local_orchestration_measurement": "caller_measured",
        "queue_wait_seconds": None,
        "queue_wait_measurement": "not_observed_at_invocation_boundary",
    }
    assert event["usage"]["input_tokens"] == 1200
    assert event["usage"]["cache_read_input_tokens"] == 200
    assert event["cost"] == {
        "amount": 0.42,
        "currency": "USD",
        "source": "external_cli_reported",
    }
    assert event["context"]["payload_bytes"] == 1234
    assert event["context"]["source_count"] == 2
    assert event["context"]["source_bytes"] == 1000
    assert event["safety"] == {
        "candidate_only": None,
        "production_modified": None,
        "measurement": "not_observed_at_invocation_boundary",
    }

    lines = (
        (tmp_path / "narrative_invocations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == 1
    persisted = json.loads(lines[0])
    assert persisted == event
    assert "UNPUBLISHED" not in lines[0]


def test_baseline_collector_exposes_unledgered_calls_and_duplicate_context(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "execution_log.yml").write_text(
        yaml.safe_dump(
            {
                "commands": [
                    {
                        "node": "INIT_TASK",
                        "dry_run": True,
                        "started_at": "2026-01-01T00:00:00+00:00",
                        "completed_at": "2026-01-01T00:00:01+00:00",
                    },
                    {
                        "node": "Writer",
                        "cli_agent": "claude_code",
                        "started_at": "2026-01-01T00:00:02+00:00",
                        "completed_at": "2026-01-01T00:00:12+00:00",
                    },
                    {
                        "node": "Writer",
                        "cli_agent": "claude_code",
                        "started_at": "2026-01-01T00:00:13+00:00",
                        "completed_at": "2026-01-01T00:00:18+00:00",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "lifecycle.yml").write_text(
        yaml.safe_dump(
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:20+00:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "cost_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {"dry_run": True, "usage_source": "no_llm_call"},
                    {
                        "agent": "Writer",
                        "dry_run": False,
                        "usage_source": "cli_agent",
                        "input_tokens": 50,
                        "output_tokens": 10,
                        "total_tokens": 60,
                        "estimated_cost": 0.1,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    for index, usage in enumerate(
        [
            {
                "input_tokens": 50,
                "output_tokens": 10,
                "cache_read_input_tokens": 5,
                "total_tokens": 65,
                "estimated_cost": 0.1,
            },
            {
                "input_tokens": 30,
                "output_tokens": 5,
                "cache_read_input_tokens": 0,
                "total_tokens": 35,
                "estimated_cost": 0.05,
            },
        ],
        start=1,
    ):
        (run_dir / f"model_execution_receipt_writer_{index}.yml").write_text(
            yaml.safe_dump(
                {
                    "provider_reported_session_id": f"session-{index}",
                    "provider_reported_usage": usage,
                }
            ),
            encoding="utf-8",
        )
    for role, unique_hash, unique_bytes in [
        ("writer", "chapter-a", 100),
        ("reviewer", "chapter-b", 200),
    ]:
        (run_dir / f"outbound_context_manifest_{role}.yml").write_text(
            yaml.safe_dump(
                {
                    "role": role.title(),
                    "payload": {"bytes": 1000, "sha256": f"packet-{role}"},
                    "source_inventory": {
                        "count": 2,
                        "files": [
                            {"path": "shared.yml", "bytes": 300, "sha256": "shared"},
                            {
                                "path": f"{unique_hash}.md",
                                "bytes": unique_bytes,
                                "sha256": unique_hash,
                            },
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

    metrics = collect_run_metrics(run_dir, evidence_root=tmp_path)

    assert metrics["wall_clock_seconds"]["value"] == 20.0
    assert metrics["model_active_seconds"]["value"] is None
    assert metrics["provider_process_wall_seconds"]["value"] == 15.0
    assert metrics["non_provider_wall_seconds"]["value"] == 5.0
    assert metrics["model_call_count"]["value"] == 2
    assert metrics["cost_ledger_call_count"]["value"] == 1
    assert metrics["ledger_total_tokens"]["value"] == 60
    assert metrics["ledger_cost_usd"]["value"] == 0.1
    assert metrics["unledgered_model_call_count"]["value"] == 1
    assert metrics["receipt_total_tokens"]["value"] == 100
    assert metrics["receipt_cost_usd"]["value"] == 0.15
    assert metrics["context_payload_bytes"]["value"] == 2000
    assert metrics["duplicated_context_bytes"]["value"] == 300
    assert metrics["duplicated_context_ratio"]["value"] == 0.333333
    assert metrics["context_by_role"]["Writer"]["source_count"] == 2
    assert metrics["run_dir"] == "run"
    assert metrics["wall_clock_seconds"]["source"] == ["run/lifecycle.yml"]
    assert metrics["duplicated_context_ratio"]["measurement"] == "lower_bound"
    assert metrics["duplicated_context_ratio"]["confidence"] == "medium"

    aggregate = aggregate_case_metrics([run_dir, run_dir], evidence_root=tmp_path)
    assert aggregate["model_call_count"]["value"] == 4
    assert aggregate["receipt_total_tokens"]["value"] == 200
    assert aggregate["duplicated_context_bytes"]["value"] == 1200
    assert aggregate["duplicated_context_ratio"]["value"] == 0.666667
    assert aggregate["run_count"]["source"] == ["run", "run"]
    assert aggregate["duplicated_context_ratio"]["measurement"] == "lower_bound"


def test_background_queue_wait_comes_from_persisted_state_events(tmp_path) -> None:
    job_dir = tmp_path / "background_jobs" / "job-1"
    job_dir.mkdir(parents=True)
    events = [
        {
            "event_type": "JOB_CREATED",
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "status": "queued",
        },
        {
            "event_type": "ATTEMPT_SCHEDULED",
            "recorded_at": "2026-01-01T00:00:03+00:00",
            "status": "preflight",
        },
        {
            "event_type": "RECEIPT_CONSUMED",
            "recorded_at": "2026-01-01T00:00:05+00:00",
            "status": "retry_wait",
        },
        {
            "event_type": "ATTEMPT_SCHEDULED",
            "recorded_at": "2026-01-01T00:00:12+00:00",
            "status": "preflight",
        },
    ]
    (job_dir / "job_events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    metrics = collect_background_job_metrics(job_dir, evidence_root=tmp_path)

    assert metrics["queue_wait_seconds"]["value"] == 3.0
    assert metrics["retry_wait_seconds"]["value"] == 7.0
    assert metrics["capacity_wait_seconds"]["value"] == 0.0
    assert metrics["job_dir"] == "background_jobs/job-1"


def test_baseline_receipt_uses_relative_paths_and_measured_safety(tmp_path) -> None:
    receipt_path = tmp_path / "acceptance" / "live_trial_receipt.json"
    receipt_path.parent.mkdir()
    receipt_path.write_text(
        json.dumps(
            {
                "execution_isolation": {"candidate_only": True},
                "production_guard": {"match": True},
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "acceptance" / "frozen_samples.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "source_git_head": "frozen-head",
                "positive_calibration_status": "missing_user_samples",
                "live_trial_receipt": "acceptance/live_trial_receipt.json",
                "metric_cases": [],
                "frozen_files": [],
            }
        ),
        encoding="utf-8",
    )

    baseline = build_efficiency_baseline(tmp_path, manifest_path)

    assert baseline["root"] == "."
    assert baseline["manifest"] == "acceptance/frozen_samples.yml"
    assert baseline["git"]["source_head"] == "frozen-head"
    assert baseline["safety"] == {
        "candidate_only": True,
        "production_modified": False,
        "measurement": "live_trial_production_tree_hash_match",
    }
    assert str(tmp_path) not in json.dumps(baseline)


def test_shared_context_bundle_is_immutable_and_reused_by_hash(tmp_path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    canon = sources / "canon.yml"
    chapter = sources / "chapter_025.md"
    reviewer = sources / "reviewer_rules.yml"
    canon.write_text("facts: []\n", encoding="utf-8")
    chapter.write_text("candidate prose\n", encoding="utf-8")
    reviewer.write_text("dimensions: [tension]\n", encoding="utf-8")

    first = build_context_bundle(
        tmp_path / "bundles",
        source_root=tmp_path,
        canon_snapshot_sha256="canon-snapshot-sha",
        chapter_window=[25],
        shared_files=[canon, chapter],
        role_specific_files={"Reviewer": [reviewer]},
    )
    second = build_context_bundle(
        tmp_path / "bundles",
        source_root=tmp_path,
        canon_snapshot_sha256="canon-snapshot-sha",
        chapter_window=[25],
        shared_files=[canon, chapter],
        role_specific_files={"Reviewer": [reviewer]},
    )

    assert first["context_bundle_id"] == second["context_bundle_id"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["reused"] is False
    assert second["reused"] is True
    assert first["shared_files"] == [
        {
            "path": "sources/canon.yml",
            "bytes": 10,
            "sha256": hashlib.sha256(b"facts: []\n").hexdigest(),
        },
        {
            "path": "sources/chapter_025.md",
            "bytes": 16,
            "sha256": hashlib.sha256(b"candidate prose\n").hexdigest(),
        },
    ]
    assert first["role_specific_files"]["Reviewer"][0]["path"] == (
        "sources/reviewer_rules.yml"
    )
    assert len(list((tmp_path / "bundles").glob("*.yml"))) == 1


def test_only_risk_triggered_chapters_use_multiple_candidates_and_judges() -> None:
    plan = plan_chapter_execution(
        [25, 26],
        risk_signals={26: ["key_reveal", "existing_blocking"]},
    )

    assert plan["chapters"][0] == {
        "chapter_id": 25,
        "risk_tier": "ordinary",
        "risk_signals": [],
        "strategy_count": 1,
        "candidate_count": 1,
        "judge_count": 1,
        "audit_stages": ["deterministic_precheck", "primary_literary_judge"],
    }
    assert plan["chapters"][1]["risk_tier"] == "high"
    assert plan["chapters"][1]["strategy_count"] == 2
    assert plan["chapters"][1]["candidate_count"] == 2
    assert plan["chapters"][1]["judge_count"] == 2
    assert plan["chapters"][1]["audit_stages"] == [
        "deterministic_precheck",
        "primary_literary_judge",
        "independent_second_judge",
        "conflict_arbitration_if_needed",
    ]


def test_incremental_reaudit_reads_only_changed_neighbors_and_fact_dependents() -> None:
    result = compute_incremental_audit_window(
        changed_chapters=[26],
        available_chapters=range(21, 31),
        fact_dependencies={26: [29, 30]},
    )

    assert result == {
        "mode": "incremental",
        "changed_chapters": [26],
        "audit_chapters": [25, 26, 27, 29, 30],
        "excluded_chapters": [21, 22, 23, 24, 28],
        "reason": "changed_neighbors_and_fact_dependencies",
    }


def test_canon_or_arc_change_expands_incremental_reaudit_to_full_window() -> None:
    result = compute_incremental_audit_window(
        changed_chapters=[26],
        available_chapters=range(21, 31),
        fact_dependencies={},
        full_reaudit_reason="canon_changed",
    )

    assert result["mode"] == "full"
    assert result["audit_chapters"] == list(range(21, 31))
    assert result["excluded_chapters"] == []
    assert result["reason"] == "canon_changed"


def test_deterministic_precheck_blocks_hash_version_and_metadata_defects(
    tmp_path,
) -> None:
    chapter = tmp_path / "chapter_025.md"
    chapter.write_text("A" * 220 + "\n", encoding="utf-8")
    manifest = {
        "manifest_version": 2,
        "chapters": [
            {
                "chapter_id": 25,
                "artifact_path": "chapter_025.md",
                "artifact_sha256": "stale-hash",
                "pov": "",
                "timeline_slot": "not-a-slot",
                "status": "candidate",
            }
        ],
    }

    result = run_deterministic_precheck(
        manifest,
        source_root=tmp_path,
        required_chapters=[25, 26],
        expected_manifest_version=1,
    )

    assert result["status"] == "blocked"
    assert set(result["blocking_codes"]) == {
        "artifact_hash_mismatch",
        "invalid_manifest_version",
        "invalid_timeline_slot",
        "missing_chapter",
        "missing_pov",
    }


def test_deterministic_precheck_accepts_established_timeline_identifier(
    tmp_path,
) -> None:
    chapter = tmp_path / "chapter_026.md"
    chapter.write_text("A valid candidate scene.\n", encoding="utf-8")
    result = run_deterministic_precheck(
        {
            "manifest_version": 1,
            "chapters": [
                {
                    "chapter_id": 26,
                    "artifact_path": "chapter_026.md",
                    "artifact_sha256": hashlib.sha256(chapter.read_bytes()).hexdigest(),
                    "pov": "Kane",
                    "timeline_slot": "T26-FROST-OBSERVATION",
                }
            ],
        },
        source_root=tmp_path,
        required_chapters=[26],
        expected_manifest_version=1,
    )

    assert result["status"] == "pass"


def test_deterministic_precheck_accepts_legacy_chinese_timeline_description(
    tmp_path,
) -> None:
    chapter = tmp_path / "chapter_025.md"
    chapter.write_text("A valid candidate scene.\n", encoding="utf-8")
    result = run_deterministic_precheck(
        {
            "manifest_version": 1,
            "chapters": [
                {
                    "chapter_id": 25,
                    "artifact_path": "chapter_025.md",
                    "artifact_sha256": hashlib.sha256(chapter.read_bytes()).hexdigest(),
                    "pov": "Kane",
                    "timeline_slot": "抵达圣光修道院外围后的第三日凌晨",
                }
            ],
        },
        source_root=tmp_path,
        required_chapters=[25],
        expected_manifest_version=1,
    )

    assert result["status"] == "pass"


def test_deterministic_precheck_rejects_unstructured_chinese_timeline_text(
    tmp_path,
) -> None:
    chapter = tmp_path / "chapter_025.md"
    chapter.write_text("A valid candidate scene.\n", encoding="utf-8")
    result = run_deterministic_precheck(
        {
            "manifest_version": 1,
            "chapters": [
                {
                    "chapter_id": 25,
                    "artifact_path": "chapter_025.md",
                    "artifact_sha256": hashlib.sha256(chapter.read_bytes()).hexdigest(),
                    "pov": "Kane",
                    "timeline_slot": "随便写点中文",
                }
            ],
        },
        source_root=tmp_path,
        required_chapters=[25],
        expected_manifest_version=1,
    )

    assert result["status"] == "blocked"
    assert "invalid_timeline_slot" in result["blocking_codes"]


def test_deterministic_precheck_blocks_repeated_paragraph_inside_one_chapter(
    tmp_path,
) -> None:
    paragraph = "This deliberately repeated paragraph contains enough substantive text to cross the deterministic threshold."
    chapter = tmp_path / "chapter_025.md"
    chapter.write_text(f"{paragraph}\n\n{paragraph}\n", encoding="utf-8")
    result = run_deterministic_precheck(
        {
            "manifest_version": 1,
            "chapters": [
                {
                    "chapter_id": 25,
                    "artifact_path": "chapter_025.md",
                    "artifact_sha256": hashlib.sha256(chapter.read_bytes()).hexdigest(),
                    "pov": "Kane",
                    "timeline_slot": "T25-HOLY-HEART-ACCEPTANCE",
                }
            ],
        },
        source_root=tmp_path,
        required_chapters=[25],
        expected_manifest_version=1,
    )

    assert result["status"] == "blocked"
    assert "duplicate_paragraph" in result["blocking_codes"]


def test_ordinary_chapter_runs_one_judge_after_deterministic_precheck() -> None:
    calls: list[str] = []

    def primary(_chapter_id: int) -> dict[str, object]:
        calls.append("primary")
        return {"status": "pass", "judge_id": "judge-primary", "blocking": []}

    def forbidden_second(_chapter_id: int) -> dict[str, object]:
        raise AssertionError("ordinary chapter must not run a second judge")

    result = execute_tiered_audit(
        {
            "chapter_id": 25,
            "risk_tier": "ordinary",
            "judge_count": 1,
        },
        deterministic_precheck={"status": "pass", "blocking_codes": []},
        primary_judge=primary,
        second_judge=forbidden_second,
    )

    assert calls == ["primary"]
    assert result["status"] == "pass"
    assert result["judge_receipts"] == [
        {"status": "pass", "judge_id": "judge-primary", "blocking": []}
    ]
    assert result["arbitration"] is None


def test_high_risk_chapter_runs_independent_second_judge_and_arbitrates_conflict() -> None:
    calls: list[str] = []

    def primary(_chapter_id: int) -> dict[str, object]:
        calls.append("primary")
        return {
            "status": "pass",
            "judge_id": "judge-a",
            "context_id": "context-a",
        }

    def second(_chapter_id: int) -> dict[str, object]:
        calls.append("second")
        return {
            "status": "blocked",
            "judge_id": "judge-b",
            "context_id": "context-b",
        }

    def arbitrate(
        _chapter_id: int,
        _primary: dict[str, object],
        _second: dict[str, object],
    ) -> dict[str, object]:
        calls.append("arbitrator")
        return {"status": "blocked", "reason": "blocking_evidence_confirmed"}

    result = execute_tiered_audit(
        {"chapter_id": 26, "risk_tier": "high", "judge_count": 2},
        deterministic_precheck={"status": "pass", "blocking_codes": []},
        primary_judge=primary,
        second_judge=second,
        arbitrator=arbitrate,
    )

    assert calls == ["primary", "second", "arbitrator"]
    assert result["status"] == "blocked"
    assert result["arbitration"] == {
        "status": "blocked",
        "reason": "blocking_evidence_confirmed",
    }


def test_background_attempt_persists_risk_tier_plan_without_text_rerouting(
    tmp_path,
) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-tiered",
        eval_id="eval-tiered",
        start_chapter=25,
        end_chapter=26,
        batch_size=2,
        writer_worker="claude_code",
        chapter_state_plan="plan.yml",
        risk_signals={26: ["key_reveal"]},
        now="2026-01-01T00:00:00+00:00",
    )

    active_attempt = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-tiered",
        now="2026-01-01T00:00:01+00:00",
    )

    assert active_attempt is not None
    request = yaml.safe_load(
        Path(active_attempt["action_request_path"]).read_text(encoding="utf-8")
    )
    assert request["narrative_execution_plan"]["chapters"][0]["judge_count"] == 1
    assert request["narrative_execution_plan"]["chapters"][1]["judge_count"] == 2
    assert request["job_kind"] == "narrative_generation"
    assert request["run_mode"] == "generate_candidate"


def test_ordinary_background_audit_uses_single_judge_runner(
    tmp_path,
    monkeypatch,
) -> None:
    observed: list[str] = []

    monkeypatch.setattr(
        "agent_runtime.narrative.audit.background.prepare_and_precheck_audit",
        lambda *_args, **_kwargs: {
            "prepared": {"status": "ready"},
            "precheck": {"status": "pass", "blocking_codes": []},
        },
    )
    def single_judge(*_args, **_kwargs) -> dict[str, object]:
        observed.append("single")
        return {"success": False, "blocked_reason": "provider_unavailable"}

    monkeypatch.setattr(
        "agent_runtime.narrative.audit.runtime.run_single_judge_pipeline",
        single_judge,
    )
    result = execute_action(
        {
            "action": "heavy_audit",
            "candidate_only": True,
            "production_allowed": False,
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "job-tiered",
            "attempt_id": "attempt-ordinary",
            "batch": {"start": 25, "end": 25},
            "config": {
                "eval_id": "eval-tiered",
                "narrative_adapter": "crown",
                "transient_retry_seconds": 1,
            },
            "narrative_execution_plan": {
                "chapters": [
                    {"chapter_id": 25, "risk_tier": "ordinary", "judge_count": 1}
                ]
            },
            "prior_results": {},
            "require_independent_reaudit": False,
        }
    )

    assert observed == ["single"]
    assert result["outcome"] == "failed_recoverable"
    assert result["result"]["reason"] == "provider_unavailable"


def test_background_audit_runs_deterministic_precheck_before_any_judge(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "projects" / "Crown_of_Ash"
    run_dir = project_root / "runs" / "audit-precheck"
    run_dir.mkdir(parents=True)
    draft = project_root / "runs" / "source" / "fiction_draft.md"
    draft.parent.mkdir(parents=True)
    draft.write_text("candidate changed after manifest\n", encoding="utf-8")
    manifest_path = run_dir / "narrative_audit_manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready",
                "manifest_path": str(manifest_path),
                "sources": [
                    {
                        "chapter": 25,
                        "files": {
                            "fiction_draft.md": {
                                "path": "runs/source/fiction_draft.md",
                                "sha256": "stale-hash",
                            },
                            "chapter_packet.yml": {
                                "path": "runs/source/chapter_packet.yml",
                                "sha256": "packet-hash",
                            },
                            "continuity_ledger.yml": {
                                "path": "runs/source/continuity_ledger.yml",
                                "sha256": "ledger-hash",
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_runtime.narrative_heavy_audit.prepare_crown_narrative_heavy_audit",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "manifest_path": str(manifest_path),
        },
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.audit.runtime.run_single_judge_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("judge must not run after a blocked precheck")
        ),
    )

    result = execute_action(
        {
            "action": "heavy_audit",
            "candidate_only": True,
            "production_allowed": False,
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "job-precheck",
            "attempt_id": "attempt-precheck",
            "batch": {"start": 25, "end": 25},
            "config": {"eval_id": "eval", "narrative_adapter": "crown"},
            "narrative_execution_plan": {
                "chapters": [{"chapter_id": 25, "judge_count": 1}]
            },
            "prior_results": {},
            "require_independent_reaudit": False,
        }
    )

    assert result["outcome"] == "failed"
    assert result["result"]["reason"] == "deterministic_precheck_blocked"
    assert "artifact_hash_mismatch" in result["result"]["blocking_codes"]


def test_mixed_risk_batch_adds_second_judge_only_for_high_risk_chapter(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "agent_runtime.narrative.audit.background.prepare_and_precheck_audit",
        lambda *_args, **_kwargs: {
            "prepared": {"status": "ready", "manifest_path": "manifest.yml"},
            "precheck": {"status": "pass", "blocking_codes": []},
        },
    )

    def run_judge(_root, *, project, task_id, budget_mode="balanced"):
        del project, budget_mode
        calls.append(task_id)
        return {
            "success": False,
            "blocked_reason": "provider_unavailable",
            "judge_receipt": {"judge_id": "Reviewer", "context_id": task_id},
        }

    monkeypatch.setattr(
        "agent_runtime.narrative.audit.runtime.run_single_judge_pipeline",
        run_judge,
    )
    result = execute_action(
        {
            "action": "heavy_audit",
            "candidate_only": True,
            "production_allowed": False,
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "job-mixed",
            "attempt_id": "attempt-mixed",
            "batch": {"start": 25, "end": 26},
            "config": {"eval_id": "eval", "narrative_adapter": "crown"},
            "narrative_execution_plan": {
                "chapters": [
                    {"chapter_id": 25, "judge_count": 1},
                    {"chapter_id": 26, "judge_count": 2},
                ]
            },
            "prior_results": {},
            "require_independent_reaudit": False,
        }
    )

    assert result["outcome"] == "failed_recoverable"
    assert len(calls) == 1
    assert "ch025_ch026" in calls[0]


def test_tiered_followup_runs_one_extra_judge_for_one_high_risk_chapter(
    tmp_path,
    monkeypatch,
) -> None:
    project_runs = tmp_path / "projects" / "Crown_of_Ash" / "runs"
    primary_task = "audit-primary"

    def passing_evidence(run_dir: Path) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        for name, value in (
            ("fiction_review.yml", {"status": "pass"}),
            (
                "continuity_failure_report.yml",
                {"status": "pass", "blocking_issue_count": 0},
            ),
            ("narrative_quality_scorecard.yml", {"status": "pass"}),
        ):
            (run_dir / name).write_text(yaml.safe_dump(value), encoding="utf-8")

    passing_evidence(project_runs / primary_task)
    second_calls: list[str] = []

    def prepare(request: dict, *, task_id: str) -> dict[str, object]:
        passing_evidence(project_runs / task_id)
        return {
            "prepared": {"status": "ready", "run_dir": str(project_runs / task_id)},
            "precheck": {"status": "pass", "blocking_codes": []},
        }

    def run_judge(_root, *, project: str, task_id: str, budget_mode: str):
        del project, budget_mode
        second_calls.append(task_id)
        return {
            "success": True,
            "judge_receipt": {
                "judge_id": "Reviewer",
                "context_id": task_id,
            },
        }

    monkeypatch.setattr(
        "agent_runtime.narrative.audit.background.prepare_and_precheck_audit",
        prepare,
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.audit.runtime.run_single_judge_pipeline",
        run_judge,
    )
    receipt = run_tiered_followup(
        {
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "batch": {"start": 25, "end": 26},
            "config": {"eval_id": "eval"},
            "narrative_execution_plan": {
                "chapters": [
                    {"chapter_id": 25, "judge_count": 1},
                    {"chapter_id": 26, "judge_count": 2},
                ]
            },
        },
        primary_task_id=primary_task,
        primary_pipeline={
            "judge_receipt": {"judge_id": "Reviewer", "context_id": primary_task}
        },
    )

    assert receipt["status"] == "pass"
    assert [chapter["chapter_id"] for chapter in receipt["chapters"]] == [25, 26]
    assert len(receipt["chapters"][0]["judge_receipts"]) == 1
    assert len(receipt["chapters"][1]["judge_receipts"]) == 2
    assert len(second_calls) == 1
    assert "ch026_judge2" in second_calls[0]


def test_revision_support_roles_run_only_through_findings_adapter(
    tmp_path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "audit"
    run_dir.mkdir(parents=True)
    plan = SimpleNamespace(run_dir=str(run_dir))
    roles: list[str] = []

    monkeypatch.setattr(
        "agent_runtime.workflow_plan.build_workflow_plan",
        lambda *_args, **_kwargs: plan,
    )

    def run_model(_root, _plan, role: str, _output):
        roles.append(role)
        return SimpleNamespace(provider="fake", model="fake", status="completed")

    monkeypatch.setattr("agent_runtime.agent_runner.run_agent_model", run_model)
    monkeypatch.setattr(
        "agent_runtime.narrative_heavy_audit.materialize_narrative_heavy_audit_result",
        lambda *_args, **_kwargs: True,
    )

    result = run_revision_support_pipeline(
        tmp_path,
        project="Crown_of_Ash",
        task_id="audit",
    )

    assert result["success"] is True
    assert roles == ["Scribe", "Verifier"]


def test_rewrite_result_persists_incremental_window_for_independent_reaudit(
    tmp_path,
) -> None:
    project = tmp_path / "projects" / "Crown_of_Ash"
    project.mkdir(parents=True)
    create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        eval_id="eval-incremental",
        start_chapter=21,
        end_chapter=30,
        writer_worker="fake",
        chapter_state_plan="plan.yml",
        now="2026-01-01T00:00:00+00:00",
    )
    state_path = project / "background_jobs" / "job-incremental" / "job_state.yml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["status"] = "rewrite_required"
    state["current_batch"] = {"number": 1, "start": 21, "end": 30}
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    active = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        now="2026-01-01T00:00:01+00:00",
    )
    write_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        attempt_id=active["attempt_id"],
        idempotency_key=active["idempotency_key"],
        lease_token=active["lease_token"],
        outcome="success",
        exit_code=0,
        result={
            "status": "pass",
            "changed_chapters": [26],
            "fact_dependencies": {26: [29]},
        },
        now="2026-01-01T00:00:02+00:00",
    )
    consume_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        now="2026-01-01T00:00:02+00:00",
    )
    deterministic = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        now="2026-01-01T00:00:03+00:00",
    )
    assert deterministic["action"] == "deterministic_reaudit"
    write_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        attempt_id=deterministic["attempt_id"],
        idempotency_key=deterministic["idempotency_key"],
        lease_token=deterministic["lease_token"],
        outcome="success",
        exit_code=0,
        result={"status": "pass"},
        now="2026-01-01T00:00:04+00:00",
    )
    consume_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        now="2026-01-01T00:00:04+00:00",
    )
    audit = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-incremental",
        now="2026-01-01T00:00:05+00:00",
    )
    request = yaml.safe_load(Path(audit["action_request_path"]).read_text())

    assert request["audit_window"]["audit_chapters"] == [25, 26, 27, 29]
    assert load_job_state(tmp_path, "Crown_of_Ash", "job-incremental")[
        "revision_audit_window"
    ]["excluded_chapters"] == [21, 22, 23, 24, 28, 30]


def test_deterministic_reaudit_executes_only_persisted_incremental_window(
    tmp_path,
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def prepare(request: dict, *, task_id: str) -> dict[str, object]:
        observed["window"] = request["audit_window"]
        observed["task_id"] = task_id
        return {
            "prepared": {"status": "ready"},
            "precheck": {
                "status": "pass",
                "blocking_codes": [],
                "findings": [],
                "checked_chapters": [25, 26, 27, 29],
            },
        }

    monkeypatch.setattr(
        "agent_runtime.narrative.audit.background.prepare_and_precheck_audit",
        prepare,
    )
    result = execute_action(
        {
            "action": "deterministic_reaudit",
            "candidate_only": True,
            "production_allowed": False,
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "job-incremental",
            "attempt_id": "attempt-incremental",
            "batch": {"start": 21, "end": 30},
            "config": {"eval_id": "eval", "narrative_adapter": "crown"},
            "audit_window": {
                "mode": "incremental",
                "audit_chapters": [25, 26, 27, 29],
                "excluded_chapters": [21, 22, 23, 24, 28, 30],
            },
        }
    )

    assert result["outcome"] == "success"
    assert result["result"]["audit_window"]["audit_chapters"] == [25, 26, 27, 29]
    assert observed["window"]["excluded_chapters"] == [21, 22, 23, 24, 28, 30]


# ---------------------------------------------------------------------------
# ContextCompiler tests — Phase 2R Node A
# ---------------------------------------------------------------------------


def _make_brief(chapter_id: int, tmp_path: Path) -> CreativeBrief:
    """Build a minimal valid CreativeBrief for testing."""
    canon = tmp_path / "canon.yml"
    canon.write_text("characters: {Kane: {role: protagonist}}\n", encoding="utf-8")
    canon_hash = hashlib.sha256(canon.read_bytes()).hexdigest()
    data = {
        "schema_version": 2,
        "chapter_id": chapter_id,
        "primary_function": "plot",
        "pov": "Kane",
        "opposing_wants": "survive vs truth",
        "turn": "discovers betrayal",
        "cost": "trust lost",
        "reader_question": "who_is_the_traitor",
        "must_preserve": ["magic_system_rules"],
        "creative_freedom": ["dialogue_tone"],
        "source_hashes": {str(canon.resolve()): canon_hash},
    }
    issues = validate_creative_brief(data)
    assert not issues, f"test brief invalid: {issues}"
    return CreativeBrief(data)


def test_context_compiler_blocks_on_missing_required_inputs(tmp_path) -> None:
    """Failing / missing-required-input cases.

    - No creative brief → blocked.
    - No canon snapshot → blocked.
    - No hard state → blocked.
    - chapter_id > 1 with no predecessor prose → blocked.
    - chapter_id > 1 with no predecessor_chapter_id → blocked.
    - chapter_id > 1 with wrong predecessor_chapter_id → blocked.
    """
    brief = _make_brief(25, tmp_path)
    # canon.yml already set up by _make_brief — do not overwrite.
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose content\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    # Missing creative brief.
    r1 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=None,  # type: ignore[arg-type]
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r1.status == "blocked"
    assert any("creative_brief" in i for i in r1.issues)

    # Missing canon snapshot.
    r2 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=tmp_path / "missing.yml",
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r2.status == "blocked"
    assert any("canon_snapshot" in i for i in r2.issues)

    # Missing hard state.
    r3 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=tmp_path / "missing.yml",
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r3.status == "blocked"
    assert any("hard_state" in i for i in r3.issues)

    # chapter_id > 1 with no predecessor prose.
    r4 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=None,
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r4.status == "blocked"
    assert any("predecessor" in i for i in r4.issues)

    # chapter_id > 1 with no predecessor_chapter_id.
    r5 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=None,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r5.status == "blocked"
    assert any("predecessor_chapter_id" in i for i in r5.issues)

    # chapter_id > 1 with wrong predecessor_chapter_id.
    r6 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=23,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r6.status == "blocked"
    assert any("wrong_predecessor_chapter_id" in i for i in r6.issues)


def test_context_compiler_chapter_one_no_predecessor_required(tmp_path) -> None:
    """Predecessor boundary: chapter 1 must NOT require predecessor prose."""
    brief = _make_brief(1, tmp_path)
    canon = tmp_path / "canon.yml"
    canon.write_text("characters: {Kane: {role: protagonist}}\n", encoding="utf-8")
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    # Chapter 1 without predecessor — should pass.
    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=1,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=None,
            predecessor_chapter_id=None,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass", f"unexpected issues: {r.issues}"
    assert r.context_bundle_id != ""

    # Chapter 2 without predecessor — must block.
    brief2 = _make_brief(2, tmp_path)
    r2 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=2,
            creative_brief=brief2,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=None,
            predecessor_chapter_id=None,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r2.status == "blocked"
    assert any("predecessor" in i for i in r2.issues)


def test_context_compiler_excludes_unrelated_chapter_prose(tmp_path) -> None:
    """Unrelated chapter prose is not loaded — only the immediate predecessor."""
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"  # already written by _make_brief
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")

    # Create several chapter prose files.
    ch23 = tmp_path / "ch023.md"
    ch23.write_text("chapter 23 content\n", encoding="utf-8")
    ch24 = tmp_path / "ch024.md"
    ch24.write_text("chapter 24 content\n", encoding="utf-8")
    ch26 = tmp_path / "ch026.md"
    ch26.write_text("chapter 26 content\n", encoding="utf-8")

    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=ch24,  # Only ch24 is the immediate predecessor.
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass", f"unexpected issues: {r.issues}"

    # The shared files must include ch24 (predecessor) but NOT ch23 or ch26.
    shared_paths = {f["path"] for f in r.shared_files}
    assert any("ch024" in p for p in shared_paths), (
        f"immediate predecessor ch024 not in shared: {shared_paths}"
    )
    assert not any("ch023" in p for p in shared_paths), (
        f"unrelated chapter ch023 leaked into shared: {shared_paths}"
    )
    assert not any("ch026" in p for p in shared_paths), (
        f"future chapter ch026 leaked into shared: {shared_paths}"
    )


def test_context_compiler_shared_bundle_built_exactly_once(tmp_path, monkeypatch) -> None:
    """Shared builder spy: build_context_bundle is called exactly once per compile."""
    brief = _make_brief(25, tmp_path)
    # canon.yml already set up by _make_brief — do not overwrite.
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    call_count = [0]

    def spy_build_context_bundle(*args, **kwargs):
        call_count[0] += 1
        return build_context_bundle(*args, **kwargs)

    monkeypatch.setattr(
        "agent_runtime.narrative.production.context_compiler.build_context_bundle",
        spy_build_context_bundle,
    )

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass"
    assert call_count[0] == 1, (
        f"build_context_bundle called {call_count[0]} times, expected exactly 1"
    )


def test_context_compiler_role_private_slice_isolation(tmp_path) -> None:
    """Each role gets the same shared bundle ID plus only its private slice."""
    brief = _make_brief(25, tmp_path)
    # canon.yml already set up by _make_brief — do not overwrite.
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    writer_rules = tmp_path / "writer_rules.yml"
    writer_rules.write_text("voice: neutral\n", encoding="utf-8")
    reviewer_rules = tmp_path / "reviewer_rules.yml"
    reviewer_rules.write_text("dimensions: [tension]\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            role_slices={
                "Writer": [writer_rules],
                "Reviewer": [reviewer_rules],
            },
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass", f"unexpected issues: {r.issues}"
    assert r.context_bundle_id != ""

    # Both roles are represented in role_specific_files.
    assert "Writer" in r.role_specific_files
    assert "Reviewer" in r.role_specific_files

    # Writer slice contains only writer_rules, not reviewer_rules.
    writer_paths = {f["path"] for f in r.role_specific_files["Writer"]}
    assert any("writer_rules" in p for p in writer_paths)
    assert not any("reviewer_rules" in p for p in writer_paths)

    # Reviewer slice contains only reviewer_rules, not writer_rules.
    reviewer_paths = {f["path"] for f in r.role_specific_files["Reviewer"]}
    assert any("reviewer_rules" in p for p in reviewer_paths)
    assert not any("writer_rules" in p for p in reviewer_paths)

    # Shared files are identical for both roles (they share the same bundle ID).
    assert len(r.shared_files) > 0


def test_context_compiler_deterministic_bundle_reuse(tmp_path) -> None:
    """Same inputs produce the same bundle ID; second call is reused."""
    brief = _make_brief(25, tmp_path)
    # canon.yml already set up by _make_brief — do not overwrite.
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    def _compile():
        return ContextCompiler.compile(
            ContextRequest(
                chapter_id=25,
                creative_brief=brief,
                canon_snapshot_path=canon,
                hard_state_path=hard,
                predecessor_prose_path=pred,
                predecessor_chapter_id=24,
                output_dir=output_dir,
                source_root=tmp_path,
            )
        )

    r1 = _compile()
    assert r1.status == "pass", f"first compile issues: {r1.issues}"
    assert r1.reused is False

    r2 = _compile()
    assert r2.status == "pass", f"second compile issues: {r2.issues}"
    assert r2.reused is True
    assert r2.context_bundle_id == r1.context_bundle_id
    assert r2.manifest_sha256 == r1.manifest_sha256

    # Only one manifest file on disk.
    assert len(list(output_dir.glob("ctx-*.yml"))) == 1


def test_context_compiler_metrics_derive_from_loaded_records(tmp_path) -> None:
    """Metric receipt values (total_files_loaded, total_bytes_loaded) come from
    actual loaded file records, not estimates."""
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"
    canon.write_text("characters: {Kane: {role: protagonist}}\n", encoding="utf-8")
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts:\n  - fact: the_wall_is_breached\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("The predecessor prose content for chapter 24.\n", encoding="utf-8")
    voice = tmp_path / "voice_memory.yml"
    voice.write_text("voice_notes: [terse, rhythmic]\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            voice_memory_paths=[voice],
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass", f"unexpected issues: {r.issues}"

    # total_files_loaded must match actual unique file count.
    unique_paths: set[str] = set()
    total_bytes = 0
    for rec in r.shared_files:
        unique_paths.add(str(rec["path"]))
        total_bytes += int(rec["bytes"])
    for role_recs in r.role_specific_files.values():
        for rec in role_recs:
            unique_paths.add(str(rec["path"]))
            total_bytes += int(rec["bytes"])

    assert r.total_files_loaded == len(unique_paths), (
        f"total_files_loaded={r.total_files_loaded} != unique={len(unique_paths)}"
    )
    assert r.total_bytes_loaded == total_bytes, (
        f"total_bytes_loaded={r.total_bytes_loaded} != computed={total_bytes}"
    )
    # Metrics are positive when files are loaded.
    assert r.total_files_loaded > 0
    assert r.total_bytes_loaded > 0


def test_context_compiler_advisory_pattern_signals_are_tagged(tmp_path) -> None:
    """Advisory pattern signals cannot set literary pass or promotion —
    every signal is explicitly tagged ``advisory: true``."""
    brief = _make_brief(25, tmp_path)
    # canon.yml already set up by _make_brief — do not overwrite.
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    patterns = tmp_path / "patterns.yml"
    patterns.write_text(
        yaml.safe_dump(
            [
                {"signal": "repeated_opening_template", "severity": "low"},
                {"signal": "high_explanation_density", "severity": "medium"},
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            pattern_signal_paths=[patterns],
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass", f"unexpected issues: {r.issues}"

    # Every pattern signal must be tagged advisory.
    assert len(r.pattern_signals) == 2
    for sig in r.pattern_signals:
        assert sig.get("advisory") is True, (
            f"pattern signal not tagged advisory: {sig}"
        )

    # Verify the compiled bundle has the right structure for metrics.
    assert r.context_bundle_id != ""
    assert r.manifest_sha256 != ""
    assert len(r.shared_files) > 0


# ---------------------------------------------------------------------------
# Adversarial tests — Phase 2R Node A correction 1
# ---------------------------------------------------------------------------


def test_stale_or_mismatched_brief_source_hash_blocks(tmp_path) -> None:
    """Recompute every declared source hash and block stale/mismatched files.

    After the brief is created, the canon source file is overwritten with
    different content.  The stale hash in the brief no longer matches, so
    compilation must be blocked.
    """
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"
    # Overwrite canon with DIFFERENT content after brief creation.
    canon.write_text("characters: {Aria: {role: antagonist}}\n", encoding="utf-8")
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose content\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "blocked", (
        f"expected blocked on stale hash, got {r.status}: {r.issues}"
    )
    assert any(
        "source_hash_mismatch" in i for i in r.issues
    ), f"expected source_hash_mismatch in issues: {r.issues}"


def test_creative_brief_bytes_and_hash_are_in_manifest_identity(tmp_path) -> None:
    """The content-addressed manifest must include CreativeBrief bytes and SHA256.

    Read the manifest file written to disk and verify ``creative_brief_sha256`` is
    present and matches the brief's canonical serialization.
    """
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"  # matches _make_brief content
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass", f"unexpected issues: {r.issues}"

    # Read the manifest from disk and verify creative_brief_sha256 is present.
    manifest_path = Path(r.manifest_path)
    assert manifest_path.is_file(), f"manifest not found: {r.manifest_path}"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert "creative_brief_sha256" in manifest, (
        "manifest missing creative_brief_sha256; only storing source files"
        " is not sufficient"
    )

    # The manifest's creative_brief_sha256 must match what we compute.
    expected_sha = hashlib.sha256(
        json.dumps(
            brief.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert manifest["creative_brief_sha256"] == expected_sha, (
        f"manifest creative_brief_sha256 mismatch:"
        f" {manifest['creative_brief_sha256']} != {expected_sha}"
    )
    assert manifest["creative_brief"] == brief.to_dict()

    # Verify the predecessor_sha256 is also present (chapter_id > 1).
    assert "predecessor_sha256" in manifest, (
        "manifest missing predecessor_sha256 for chapter_id > 1"
    )
    expected_pred_sha = hashlib.sha256(pred.read_bytes()).hexdigest()
    assert manifest["predecessor_sha256"] == expected_pred_sha


def test_wrong_predecessor_chapter_id_blocks(tmp_path) -> None:
    """For chapter_id > 1, predecessor_chapter_id must equal chapter_id - 1.

    Passing predecessor_chapter_id=20 for chapter_id=25 must block.
    """
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"  # matches _make_brief content
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=20,  # WRONG — should be 24
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "blocked", (
        f"expected blocked on wrong predecessor_chapter_id, got {r.status}"
    )
    assert any(
        "wrong_predecessor_chapter_id" in i for i in r.issues
    ), f"expected wrong_predecessor_chapter_id in issues: {r.issues}"


def test_predecessor_hash_mismatch_blocks(tmp_path) -> None:
    """The predecessor SHA256 is bound into the manifest identity; changing the
    predecessor prose changes the manifest.

    Two compilations with different predecessor content must produce different
    manifest IDs and SHA256s.
    """
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"  # matches _make_brief content
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("original predecessor prose\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    r1 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            predecessor_prose_sha256=hashlib.sha256(pred.read_bytes()).hexdigest(),
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r1.status == "pass", f"first compile issues: {r1.issues}"

    expected_pred_sha = hashlib.sha256(pred.read_bytes()).hexdigest()
    # Change the predecessor prose content while retaining the prior receipt hash.
    pred.write_text("tampered predecessor prose — different content\n", encoding="utf-8")
    r2 = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            predecessor_prose_sha256=expected_pred_sha,
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r2.status == "blocked"
    assert any("predecessor_prose_hash_mismatch" in issue for issue in r2.issues)


def test_shared_role_and_cross_role_duplicates_are_loaded_once_and_metrics_are_nonzero(
    tmp_path,
) -> None:
    """Cross-slice duplicates are removed before bundle construction.

    A file already in shared context cannot remain private.  A file requested
    by multiple roles becomes shared once.  ``duplicate_context_ratio`` must be
    > 0.0 when duplication actually exists.
    """
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"  # matches _make_brief content
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    shared_also = tmp_path / "shared_also_used_by_writer.yml"
    shared_also.write_text("rules: [pacing, dialogue]\n", encoding="utf-8")
    writer_only = tmp_path / "writer_private.yml"
    writer_only.write_text("style: experimental\n", encoding="utf-8")
    reviewer_only = tmp_path / "reviewer_private.yml"
    reviewer_only.write_text("criteria: [coherence]\n", encoding="utf-8")
    output_dir = tmp_path / "bundles"

    # shared_also is in BOTH the shared voice_memory_paths AND Writer's role slice.
    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            voice_memory_paths=[shared_also],
            role_slices={
                "Writer": [shared_also, writer_only],
                "Reviewer": [reviewer_only],
            },
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "pass", f"unexpected issues: {r.issues}"

    # shared_also must appear in shared_files (because it was in voice_memory_paths).
    shared_paths = {f["path"] for f in r.shared_files}
    assert any("shared_also_used_by_writer" in p for p in shared_paths), (
        f"shared_also missing from shared files: {shared_paths}"
    )

    # shared_also must NOT appear in Writer's role_specific_files.
    writer_slice = r.role_specific_files.get("Writer", [])
    writer_paths = {f["path"] for f in writer_slice}
    assert not any("shared_also_used_by_writer" in p for p in writer_paths), (
        f"shared_also duplicated in Writer private slice: {writer_paths}"
    )

    # duplicate_context_ratio MUST be > 0 because shared_also was in both places.
    assert r.duplicate_context_ratio > 0.0, (
        f"duplicate_context_ratio is {r.duplicate_context_ratio}; "
        f"expected > 0.0 since shared_also appears in both shared and role slices"
    )
    assert r.duplicate_bytes_saved > 0, (
        f"duplicate_bytes_saved is {r.duplicate_bytes_saved}; expected > 0"
    )


def test_authoritative_pattern_signal_fields_block(tmp_path) -> None:
    """Pattern signals containing authoritative fields are rejected.

    Fields like status, pass, accept, seal, promotion must not be returned
    — even with advisory=true.  Signals with these fields are excluded.
    """
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"  # matches _make_brief content
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    patterns = tmp_path / "patterns.yml"
    patterns.write_text(
        yaml.safe_dump(
            [
                {"signal": "bad_opening", "severity": "low", "pass": True},
                {"signal": "good_pacing", "severity": "low"},
                {"signal": "elevated_risk", "severity": "high", "status": "accepted"},
                {"signal": "malicious", "promotion": "publish", "seal": "approved"},
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            pattern_signal_paths=[patterns],
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "blocked"
    assert any("authoritative_pattern_signal_field" in issue for issue in r.issues)
    assert r.pattern_signals == []


def test_caller_owned_pattern_data_is_not_mutated(tmp_path) -> None:
    """Caller-owned pattern signal data must never be mutated.

    Even when signals contain authoritative fields, the original in-memory
    dict is left untouched.
    """
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"  # matches _make_brief content
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")

    # Create pattern data with authoritative fields.
    original_item = {
        "signal": "high_tension",
        "severity": "critical",
        "pass": True,
        "status": "accepted",
        "promotion": "urgent",
    }
    patterns = tmp_path / "patterns.yml"
    patterns.write_text(
        yaml.safe_dump([original_item]),
        encoding="utf-8",
    )
    output_dir = tmp_path / "bundles"

    r = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            pattern_signal_paths=[patterns],
            output_dir=output_dir,
            source_root=tmp_path,
        )
    )
    assert r.status == "blocked"

    # The signal with authoritative fields must be rejected.
    assert len(r.pattern_signals) == 0, (
        f"expected 0 signals (all rejected), got: {r.pattern_signals}"
    )

    # The original dict (re-read from disk) must be unchanged — no mutation.
    raw_roundtrip = yaml.safe_load(patterns.read_text(encoding="utf-8"))
    assert isinstance(raw_roundtrip, list) and len(raw_roundtrip) == 1
    rt_item = raw_roundtrip[0]
    assert rt_item.get("pass") is True, "caller data was mutated: pass removed"
    assert rt_item.get("status") == "accepted", "caller data was mutated: status changed"
    assert rt_item.get("promotion") == "urgent", "caller data was mutated: promotion removed"
    # advisory must NOT have been injected into the caller's data.
    assert "advisory" not in rt_item, (
        "caller data was mutated: advisory tag injected into original dict"
    )


def test_cross_role_duplicate_is_promoted_to_shared_and_removed_from_all_roles(
    tmp_path,
) -> None:
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    common = tmp_path / "common_rules.yml"
    common.write_text("rules: [tension]\n", encoding="utf-8")

    result = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            role_slices={"Writer": [common], "Reviewer": [common]},
            output_dir=tmp_path / "bundles",
            source_root=tmp_path,
        )
    )

    assert result.status == "pass"
    assert [record["path"] for record in result.shared_files].count(
        "common_rules.yml"
    ) == 1
    assert all(
        record["path"] != "common_rules.yml"
        for records in result.role_specific_files.values()
        for record in records
    )


def test_literary_status_alias_cannot_bypass_advisory_signal_gate(tmp_path) -> None:
    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    pred = tmp_path / "ch024.md"
    pred.write_text("predecessor prose\n", encoding="utf-8")
    patterns = tmp_path / "patterns.yml"
    patterns.write_text(
        yaml.safe_dump({"signal": "false_green", "literary_status": "pass"}),
        encoding="utf-8",
    )

    result = ContextCompiler.compile(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=pred,
            predecessor_chapter_id=24,
            pattern_signal_paths=[patterns],
            output_dir=tmp_path / "bundles",
            source_root=tmp_path,
        )
    )

    assert result.status == "blocked"
    assert any("literary_status" in issue for issue in result.issues)


def test_candidate_writer_packet_preview_uses_compiled_context_only(tmp_path) -> None:
    from agent_runtime.narrative.production.writer_packet_preview import (
        build_writer_packet_preview,
    )

    canon = tmp_path / "canon.yml"
    canon.write_text("canon_marker: fixed\n", encoding="utf-8")
    hard = tmp_path / "hard_state.yml"
    hard.write_text("hard_state_marker: chapter_24\n", encoding="utf-8")
    predecessor = tmp_path / "ch024.md"
    predecessor.write_text("predecessor_prose_marker\n", encoding="utf-8")
    brief_source = tmp_path / "chapter_plan.yml"
    brief_source.write_text("brief_source_marker: chapter_25\n", encoding="utf-8")
    writer_notes = tmp_path / "writer_notes.yml"
    writer_notes.write_text("writer_private_marker: preserve_voice\n", encoding="utf-8")
    reviewer_notes = tmp_path / "reviewer_notes.yml"
    reviewer_notes.write_text("reviewer_private_marker: hidden\n", encoding="utf-8")
    unrelated = tmp_path / "ch001.md"
    unrelated.write_text("unrelated_chapter_marker\n", encoding="utf-8")
    brief = CreativeBrief(
        {
            "schema_version": 2,
            "chapter_id": 25,
            "primary_function": "plot",
            "pov": "Kane",
            "opposing_wants": "verify the map without exposing distrust",
            "turn": "the map omission becomes an investigation target",
            "cost": "accepting the mission narrows retreat options",
            "reader_question": "what is hidden below the monastery",
            "must_preserve": ["the second underground level remains unknown"],
            "creative_freedom": ["choose scene blocking and sensory detail"],
            "word_count_target": [4500, 5500],
            "source_hashes": {
                str(brief_source.resolve()): hashlib.sha256(
                    brief_source.read_bytes()
                ).hexdigest()
            },
        }
    )

    preview = build_writer_packet_preview(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=predecessor,
            predecessor_chapter_id=24,
            role_slices={"Writer": [writer_notes], "Reviewer": [reviewer_notes]},
            output_dir=tmp_path / "bundles",
            source_root=tmp_path,
        ),
        project="ProbeNovel",
        task_id="task_ch025_preview",
    )

    assert preview.status == "pass"
    assert preview.payload is not None
    assert preview.payload["schema_version"] == 2
    assert preview.payload["packet_type"] == "agentlab_sealed_role_session"
    assert preview.payload["agent"] == "Writer"
    assert preview.payload["required_outputs"] == ["fiction_draft.md"]
    assert preview.payload["context_policy"]["mode"] == "sealed_messages_only"
    assert preview.candidate_only is True
    assert preview.production_modified is False
    assert preview.payload["context_policy"]["additional_file_reads_allowed"] is False
    rendered = json.dumps(preview.payload, ensure_ascii=False, sort_keys=True)
    for marker in (
        "canon_marker",
        "hard_state_marker",
        "predecessor_prose_marker",
        "brief_source_marker",
        "writer_private_marker",
    ):
        assert marker in rendered
    assert "reviewer_private_marker" not in rendered
    assert "unrelated_chapter_marker" not in rendered
    assert str(tmp_path) not in rendered
    assert preview.payload_bytes == len(preview.payload_json.encode("utf-8"))
    assert preview.token_estimate == (preview.payload_bytes + 3) // 4
    assert preview.loaded_file_count == 5
    expected_writer_bytes = sum(
        path.stat().st_size
        for path in (canon, hard, predecessor, brief_source, writer_notes)
    )
    assert preview.loaded_context_bytes == expected_writer_bytes
    assert f"loaded_context_bytes: {expected_writer_bytes}" in rendered
    assert "word_count_target" in rendered
    assert "4500" in rendered and "5500" in rendered


def test_writer_packet_preview_blocks_production_output_before_compile(tmp_path) -> None:
    from agent_runtime.narrative.production.writer_packet_preview import (
        build_writer_packet_preview,
    )

    canon = tmp_path / "canon.yml"
    canon.write_text("canon: fixed\n", encoding="utf-8")
    hard = tmp_path / "hard_state.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    predecessor = tmp_path / "ch024.md"
    predecessor.write_text("previous chapter\n", encoding="utf-8")
    brief_source = tmp_path / "chapter_plan.yml"
    brief_source.write_text("chapter: 25\n", encoding="utf-8")
    brief = CreativeBrief(
        {
            "schema_version": 2,
            "chapter_id": 25,
            "primary_function": "plot",
            "pov": "Kane",
            "opposing_wants": "verify the map without exposing distrust",
            "turn": "the omission becomes an investigation target",
            "cost": "the accepted mission narrows retreat options",
            "reader_question": "what is hidden below the monastery",
            "must_preserve": ["the lower level remains unknown"],
            "creative_freedom": ["choose scene blocking"],
            "source_hashes": {
                str(brief_source.resolve()): hashlib.sha256(
                    brief_source.read_bytes()
                ).hexdigest()
            },
        }
    )
    production_output = tmp_path / "projects" / "ProbeNovel" / "production" / "context"

    preview = build_writer_packet_preview(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=predecessor,
            predecessor_chapter_id=24,
            output_dir=production_output,
            source_root=tmp_path,
        ),
        project="ProbeNovel",
        task_id="task_ch025_production_probe",
    )

    assert preview.status == "blocked"
    assert "preview_output_dir_is_production" in preview.issues
    assert preview.payload is None
    assert preview.production_modified is False
    assert not production_output.exists()

    other_project_production = (
        tmp_path / "projects" / "OtherNovel" / "production" / "context"
    )
    mismatch = build_writer_packet_preview(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=predecessor,
            predecessor_chapter_id=24,
            output_dir=other_project_production,
            source_root=tmp_path,
        ),
        project="ProbeNovel",
        task_id="task_ch025_cross_project_production_probe",
    )
    assert mismatch.status == "blocked"
    assert "preview_output_dir_is_production" in mismatch.issues
    assert not other_project_production.exists()


def test_writer_packet_preview_measures_duplicate_writer_inputs(tmp_path) -> None:
    from agent_runtime.narrative.production.writer_packet_preview import (
        build_writer_packet_preview,
    )

    brief = _make_brief(25, tmp_path)
    canon = tmp_path / "canon.yml"
    hard = tmp_path / "hard.yml"
    predecessor = tmp_path / "ch024.md"
    repeated = tmp_path / "writer_memory.yml"
    hard.write_text("facts: []\n", encoding="utf-8")
    predecessor.write_text("previous prose\n", encoding="utf-8")
    repeated.write_text("voice: restrained\n", encoding="utf-8")

    preview = build_writer_packet_preview(
        ContextRequest(
            chapter_id=25,
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard,
            predecessor_prose_path=predecessor,
            predecessor_chapter_id=24,
            role_slices={"Writer": [repeated, repeated]},
            output_dir=tmp_path / "bundles",
            source_root=tmp_path,
        ),
        project="ProbeNovel",
        task_id="task_ch025_duplicate_writer_input",
    )

    assert preview.status == "pass"
    assert preview.duplicate_context_ratio > 0.0
    assert preview.loaded_file_count == 4


def test_frozen_writer_packet_measurement_is_reproducible_and_keeps_candidate_scope(
    tmp_path,
) -> None:
    from agent_runtime.narrative.production.writer_packet_measurement import (
        measure_frozen_writer_packets,
    )

    project_root = tmp_path / "projects" / "ProbeNovel"
    source_dir = project_root / "candidates" / "frozen_source"
    source_dir.mkdir(parents=True)
    source_plan = source_dir / "chapter_state_plan.yml"
    source_plan.write_text(
        yaml.safe_dump(
            {
                "target_character_range": [4500, 5500],
                "hard_character_range": [3000, 8000],
                "chapter_state_plan": [
                    {
                        "chapter": 2,
                        "pov": "Kane",
                        "scene_goal": "verify the map",
                        "irreversible_plot_change": "the omission becomes actionable",
                        "closing_state": "the route is conditionally accepted",
                        "reader_question": "what was removed",
                        "must_preserve": ["the lower level remains unknown"],
                        "creative_freedom": ["choose scene blocking"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    canon = source_dir / "canon.yml"
    canon.write_text("canon: fixed\n", encoding="utf-8")
    memory = source_dir / "memory.yml"
    memory.write_text("open_reader_questions: [what was removed]\n", encoding="utf-8")
    writer_template = source_dir / "writer.md"
    writer_template.write_text("Writer prose-only contract\n", encoding="utf-8")
    predecessor = source_dir / "ch001.md"
    predecessor.write_text("previous prose\n", encoding="utf-8")
    hard = source_dir / "hard.yml"
    hard.write_text("facts: []\n", encoding="utf-8")

    def ref(path: Path) -> dict[str, str]:
        return {
            "path": path.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    manifest_path = tmp_path / "measurement.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "freeze_id": "probe_measurement",
                "project": "ProbeNovel",
                "candidate_only": True,
                "derived_candidate_dir": (
                    "projects/ProbeNovel/candidates/phase2r_preview"
                ),
                "source_plan": ref(source_plan),
                "canon_snapshot": ref(canon),
                "shared_memory_sources": [ref(memory)],
                "writer_private_sources": [ref(writer_template)],
                "chapter_inputs": [
                    {
                        "chapter_id": 2,
                        "predecessor_prose": ref(predecessor),
                        "hard_state": ref(hard),
                    }
                ],
                "legacy_baseline_sources": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    baseline_refs = []
    for chapter_id in (1, 2, 3):
        baseline = source_dir / f"legacy_{chapter_id}.yml"
        baseline.write_text(
            yaml.safe_dump(
                {
                    "payload": {"bytes": 100000},
                    "source_inventory": {
                        "count": 10,
                        "files": [{"bytes": 50000}],
                    },
                }
            ),
            encoding="utf-8",
        )
        baseline_refs.append(ref(baseline))
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["legacy_baseline_sources"] = baseline_refs
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    first = measure_frozen_writer_packets(manifest_path, repository_root=tmp_path)
    second = measure_frozen_writer_packets(manifest_path, repository_root=tmp_path)

    assert first == second
    assert first["packet_contract"] == "agentlab_sealed_role_session_v2_preview"
    assert first["rows"][0]["word_count_target"] == [4500, 5500]
    assert first["checks"]["writer_template_present"] is True
    derived = tmp_path / first["derived_sources"][0]["path"]
    assert derived.is_file()
    assert project_root / "production" not in derived.parents
    assert first["production_writes"] == 0
    assert first["target"]["quality_preserving_evaluated"] is False
    assert first["target"]["phase_acceptance_met"] is False
