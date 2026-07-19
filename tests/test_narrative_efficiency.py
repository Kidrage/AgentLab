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
