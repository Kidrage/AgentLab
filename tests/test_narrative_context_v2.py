from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.narrative.craft_cards import validate_craft_card
from agent_runtime.narrative.role_context import compile_role_context_pack
from agent_runtime.run_task import app

ROOT = Path(__file__).resolve().parents[1]


def test_craft_card_accepts_traceable_technique_and_rejects_source_text() -> None:
    valid = {
        "device": "Delay an answer through a materially costly interruption.",
        "preconditions": ["The reader already understands the open question."],
        "mechanism": "Interrupt the answer with a consequence-bearing choice.",
        "reader_effect": "Sustained tension without erasing forward motion.",
        "failure_modes": ["The interruption feels unrelated or consequence-free."],
        "applicable_scenes": ["interrogation", "negotiation"],
        "originality_constraints": [
            "Rebuild the device from Crown-specific motives and causality."
        ],
        "source_rights": "criticism_research",
        "source_locator": "Example Essay, section 3",
    }

    assert validate_craft_card(valid) == []

    copied = {
        **valid,
        "source_rights": "unlicensed_contemporary_fiction",
        "source_text": "A copied passage.",
    }
    assert validate_craft_card(copied) == [
        "source_rights_not_allowed:unlicensed_contemporary_fiction",
        "source_text_storage_forbidden:source_text",
    ]


def test_role_context_pack_is_namespace_scoped_budgeted_and_hash_bound(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "context_bundle_id": "ctx-test",
                "shared_files": [],
                "role_specific_files": {},
            }
        ),
        encoding="utf-8",
    )
    evidence = []
    for name, namespace, stage in (
        ("canon.yml", "canon", "hard_fact"),
        ("timeline.yml", "timeline", "graph_adjacent"),
        ("names.yml", "exact_name_index", "semantic"),
        ("knowledge.yml", "character_knowledge", "reflective"),
    ):
        path = source_root / name
        path.write_text("12345678", encoding="utf-8")
        evidence.append(
            {
                "path": path,
                "namespace": namespace,
                "retrieval_stage": stage,
                "score": 1.0,
            }
        )

    first = compile_role_context_pack(
        ROOT,
        role_id="canon_timeline_steward",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=evidence,
        token_budget=5,
        minimum_evidence_items=3,
        output_dir=source_root / "role_context",
    )
    second = compile_role_context_pack(
        ROOT,
        role_id="canon_timeline_steward",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=evidence,
        token_budget=5,
        minimum_evidence_items=3,
        output_dir=source_root / "role_context",
    )

    assert first["status"] == "pass"
    assert second["status"] == "current"
    assert first["retrieval_order"] == [
        "hard_fact",
        "graph_adjacent",
        "semantic",
        "reflective",
    ]
    assert [item["retrieval_stage"] for item in first["selected_evidence"]] == [
        "hard_fact",
        "graph_adjacent",
    ]
    assert first["omitted_evidence"] == [
        {
            "path": "names.yml",
            "namespace": "exact_name_index",
            "retrieval_stage": "semantic",
            "reason": "token_budget_exceeded",
        },
        {
            "path": "knowledge.yml",
            "namespace": "character_knowledge",
            "retrieval_stage": "reflective",
            "reason": "token_budget_exceeded",
        },
    ]
    assert first["token_usage"]["used"] == 4
    assert len(first["pack_sha256"]) == 64


def test_role_context_pack_blocks_cross_role_namespace_leak(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-test\n",
        encoding="utf-8",
    )
    private_memory = source_root / "private_memory.yml"
    private_memory.write_text("secret: true\n", encoding="utf-8")

    result = compile_role_context_pack(
        ROOT,
        role_id="writer",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=[
            {
                "path": private_memory,
                "namespace": "character_private_memory",
                "retrieval_stage": "hard_fact",
            }
        ],
        token_budget=100,
        minimum_evidence_items=1,
        output_dir=source_root / "role_context",
    )

    assert result["status"] == "blocked"
    assert result["issues"] == [
        "namespace_not_allowed:writer:character_private_memory"
    ]
    assert not (source_root / "role_context").exists()


def test_role_context_pack_rejects_unlicensed_craft_card_payload(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-test\n",
        encoding="utf-8",
    )
    craft_card = source_root / "craft_card.yml"
    craft_card.write_text(
        yaml.safe_dump(
            {
                "device": "Borrowed mannerism",
                "preconditions": ["A source novel exists."],
                "mechanism": "Copy it.",
                "reader_effect": "Imitation.",
                "failure_modes": ["Copyright violation."],
                "applicable_scenes": ["all"],
                "originality_constraints": ["none"],
                "source_rights": "unlicensed_contemporary_fiction",
                "source_locator": "Novel, chapter 4",
                "source_text": "Copied prose.",
            }
        ),
        encoding="utf-8",
    )

    result = compile_role_context_pack(
        ROOT,
        role_id="research_style_curator",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=[
            {
                "path": craft_card,
                "namespace": "craft_cards",
                "retrieval_stage": "semantic",
            }
        ],
        token_budget=1000,
        minimum_evidence_items=1,
        output_dir=source_root / "role_context",
    )

    assert result["status"] == "blocked"
    assert result["issues"] == [
        (
            f"craft_card_invalid:{craft_card}:0:"
            "source_rights_not_allowed:unlicensed_contemporary_fiction"
        ),
        f"craft_card_invalid:{craft_card}:0:source_text_storage_forbidden:source_text",
    ]


def test_reflective_retrieval_is_skipped_when_prior_evidence_is_sufficient(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-test\n",
        encoding="utf-8",
    )
    hard_fact = source_root / "canon.yml"
    reflection = source_root / "reflection.yml"
    hard_fact.write_text("fact", encoding="utf-8")
    reflection.write_text("reflection", encoding="utf-8")

    result = compile_role_context_pack(
        ROOT,
        role_id="canon_timeline_steward",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=[
            {
                "path": reflection,
                "namespace": "character_knowledge",
                "retrieval_stage": "reflective",
            },
            {
                "path": hard_fact,
                "namespace": "canon",
                "retrieval_stage": "hard_fact",
            },
        ],
        token_budget=100,
        minimum_evidence_items=1,
        output_dir=source_root / "role_context",
    )

    assert [item["path"] for item in result["selected_evidence"]] == ["canon.yml"]
    assert result["omitted_evidence"] == [
        {
            "path": "reflection.yml",
            "namespace": "character_knowledge",
            "retrieval_stage": "reflective",
            "reason": "reflective_retrieval_not_needed",
        }
    ]


def test_narrative_context_compile_cli_uses_request_contract(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-cli\n",
        encoding="utf-8",
    )
    canon = source_root / "canon.yml"
    canon.write_text("fact: true\n", encoding="utf-8")
    request = tmp_path / "request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "schema_version": "role-context-compile-request/v1",
                "role_id": "canon_timeline_steward",
                "source_root": str(source_root),
                "context_bundle_manifest": "context_bundle.yml",
                "evidence_candidates": [
                    {
                        "path": "canon.yml",
                        "namespace": "canon",
                        "retrieval_stage": "hard_fact",
                    }
                ],
                "token_budget": 100,
                "minimum_evidence_items": 1,
                "output_dir": "role_context",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["narrative", "context", "compile", "--request", str(request)],
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)
    assert payload["schema_version"] == "role-context-pack/v1"
    assert payload["status"] == "pass"
    assert Path(payload["pack_path"]).is_file()
