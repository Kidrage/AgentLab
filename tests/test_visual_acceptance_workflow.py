from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from agent_runtime.lifecycle_graph import create_lifecycle
from agent_runtime.routing.route_catalog import DEFAULT_ROUTE_AGENTS
from agent_runtime.visual_acceptance_workflow import materialize_visual_acceptance


ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = ("aesthetic", "continuity", "technical", "factual_safety")
VERIFICATION_CHECKS = (
    "asset_integrity",
    "evidence_chain",
    "reviewer_independence",
    "promotion_boundary",
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _dimension_verdicts(label: str) -> dict:
    return {
        name: {"verdict": "pass", "evidence": [f"{label} checked {name}"]}
        for name in DIMENSIONS
    }


def _complete_visual_evidence(run_dir: Path) -> None:
    asset = run_dir / "artifacts" / "media_backend" / "poster.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"real-visual-candidate")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    size_bytes = asset.stat().st_size
    relative = asset.relative_to(run_dir).as_posix()

    _write_yaml(
        run_dir / "artifacts" / "media_backend" / "generation_receipt.yml",
        {
            "status": "complete",
            "producer": {"role": "ArtifactProducer", "id": "grok-role-session-1"},
            "backend": "hermes_grok_oauth",
            "model": "grok-imagine-image",
            "prompt_parameters": {"prompt_sha256": hashlib.sha256(b"prompt").hexdigest()},
            "reference_assets": [],
        },
    )
    _write_yaml(
        run_dir / "artifacts" / "media_backend" / "generated_assets_manifest.yml",
        {
            "status": "complete",
            "assets": [
                {
                    "candidate_id": "poster-1",
                    "path": relative,
                    "media_type": "image",
                    "sha256": digest,
                    "size_bytes": size_bytes,
                }
            ],
        },
    )
    _write_yaml(
        run_dir / "visual_observation_report.yml",
        {
            "status": "complete",
            "observer": {
                "role": "Observer",
                "id": "agy-observer-session-1",
                "backend": "agy_oauth",
                "model": "gemini-3.5-flash",
            },
            "candidates": [
                {
                    "candidate_id": "poster-1",
                    "status": "complete",
                    "asset": {
                        "path": relative,
                        "sha256": digest,
                        "size_bytes": size_bytes,
                    },
                    "keyframes": [{"label": "full_frame", "sha256": digest}],
                    "observations": ["full frame inspected"],
                }
            ],
        },
    )
    _write_yaml(
        run_dir / "visual_review_report.yml",
        {
            "status": "complete",
            "reviewer": {
                "role": "Reviewer",
                "id": "agy-visual-reviewer-session-1",
                "backend": "agy_oauth",
                "model": "gemini-3.5-flash",
            },
            "candidates": [
                {
                    "candidate_id": "poster-1",
                    "status": "complete",
                    "asset": {
                        "path": relative,
                        "sha256": digest,
                        "size_bytes": size_bytes,
                    },
                    "dimensions": _dimension_verdicts("Reviewer"),
                }
            ],
        },
    )
    _write_yaml(
        run_dir / "visual_verification_report.yml",
        {
            "status": "complete",
            "reviewer": {
                "role": "Verifier",
                "id": "hermes-verifier-session-1",
                "backend": "hermes_codex_oauth",
                "model": "gpt-5.6-sol",
            },
            "candidates": [
                {
                    "candidate_id": "poster-1",
                    "status": "complete",
                    "asset": {
                        "path": relative,
                        "sha256": digest,
                        "size_bytes": size_bytes,
                    },
                    "checks": {
                        check: {
                            "verdict": "pass",
                            "evidence": [f"Verifier checked {check}"],
                        }
                        for check in VERIFICATION_CHECKS
                    },
                }
            ],
        },
    )


def test_media_route_and_pack_require_post_production_visual_roles() -> None:
    agents = DEFAULT_ROUTE_AGENTS["media_generation_task"]
    packs = yaml.safe_load((ROOT / "config" / "production_packs.yml").read_text())
    media_packs = {
        pack["pack_id"]: pack
        for pack in packs["packs"]
        if pack["pack_id"] in {"media_generation", "media_series_production"}
    }

    assert agents == [
        "Supervisor",
        "ArtifactProducer",
        "Observer",
        "Reviewer",
        "TesterAuditor",
        "Verifier",
    ]
    for pack in media_packs.values():
        nodes = pack["lifecycle_nodes"]
        assert nodes.index("ARTIFACT_PRODUCTION") < nodes.index("VISUAL_OBSERVATION")
        assert nodes.index("VISUAL_OBSERVATION") < nodes.index("VISUAL_REVIEW")
        assert nodes.index("VISUAL_REVIEW") < nodes.index("VALIDATION")
        assert nodes.index("VALIDATION") < nodes.index("VERIFY")


def test_media_lifecycle_activates_only_post_production_visual_nodes(tmp_path: Path) -> None:
    plan = {
        "route": {"agents": DEFAULT_ROUTE_AGENTS["media_generation_task"]},
        "production_pack": {
            "pack_id": "media_generation",
            "lifecycle_nodes": [
                "INIT_TASK",
                "ARTIFACT_PRODUCTION",
                "VISUAL_OBSERVATION",
                "VISUAL_REVIEW",
                "VALIDATION",
                "VERIFY",
                "FINALIZE",
            ],
        },
    }

    lifecycle = create_lifecycle(tmp_path, plan)

    assert lifecycle["nodes"]["OBSERVATION_OPTIONAL"]["status"] == "skipped"
    assert lifecycle["nodes"]["VISUAL_OBSERVATION"]["status"] == "waiting"
    assert lifecycle["nodes"]["VISUAL_REVIEW"]["status"] == "waiting"


def test_materializer_combines_owned_reports_and_rechecks_real_asset(tmp_path: Path) -> None:
    _complete_visual_evidence(tmp_path)

    result = materialize_visual_acceptance(tmp_path, task_id="task-media-1")

    manifest = yaml.safe_load(
        (tmp_path / "visual_acceptance_candidate.yml").read_text(encoding="utf-8")
    )
    decisions = yaml.safe_load(
        (tmp_path / "visual_acceptance_decision.yml").read_text(encoding="utf-8")
    )
    assert result["status"] == "pass"
    assert result["candidate_count"] == 1
    assert manifest["candidates"][0]["candidate_id"] == "poster-1"
    assert {row["reviewer"]["role"] for row in manifest["candidates"][0]["reviews"]} == {
        "Reviewer",
        "Verifier",
    }
    assert decisions["decisions"][0]["status"] == "accepted_candidate"
    assert decisions["decisions"][0]["asset"]["verified"] is True


def test_materializer_blocks_when_independent_observer_report_is_missing(tmp_path: Path) -> None:
    _complete_visual_evidence(tmp_path)
    (tmp_path / "visual_observation_report.yml").unlink()

    result = materialize_visual_acceptance(tmp_path, task_id="task-media-2")

    assert result["status"] == "blocked"
    assert "missing:visual_observation_report.yml" in result["issues"]
    assert not (tmp_path / "visual_acceptance_candidate.yml").exists()


def test_materializer_allows_explicit_non_live_no_asset_run(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "generation_ledger.yml",
        {"status": "dry_run", "live": False, "generated_assets": []},
    )
    _write_yaml(
        tmp_path / "generated_assets_manifest.yml",
        {"status": "not_required", "assets": []},
    )

    result = materialize_visual_acceptance(tmp_path, task_id="task-media-dry")

    assert result["status"] == "not_required"
    candidate = yaml.safe_load(
        (tmp_path / "visual_acceptance_candidate.yml").read_text(encoding="utf-8")
    )
    assert candidate["status"] == "not_required"
    assert candidate["candidates"] == []


def test_materializer_blocks_live_failure_with_empty_assets(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "generation_ledger.yml",
        {
            "status": "local_cli_error",
            "live": True,
            "generated_assets": [],
            "block_reason": "provider_failed",
        },
    )
    _write_yaml(
        tmp_path / "generated_assets_manifest.yml",
        {"status": "not_required", "assets": []},
    )

    result = materialize_visual_acceptance(tmp_path, task_id="task-media-failed")

    assert result["status"] == "blocked"
    assert "invalid:generated_assets_manifest.assets" in result["issues"]
    assert not (tmp_path / "visual_acceptance_candidate.yml").exists()


def test_materializer_blocks_ambiguous_dry_run_manifest(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "generation_ledger.yml",
        {"status": "dry_run", "live": False, "generated_assets": []},
    )
    _write_yaml(
        tmp_path / "generated_assets_manifest.yml",
        {"status": "not_required", "assets": [], "source": "root"},
    )
    _write_yaml(
        tmp_path / "artifacts" / "media_backend" / "generated_assets_manifest.yml",
        {"status": "not_required", "assets": [], "source": "nested"},
    )

    result = materialize_visual_acceptance(tmp_path, task_id="task-media-ambiguous")

    assert result["status"] == "blocked"
    assert "ambiguous:generated_assets_manifest" in result["issues"]
