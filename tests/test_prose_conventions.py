from __future__ import annotations

import hashlib
from pathlib import Path

from agent_runtime.narrative.production.chapter_engine import ChapterEngine, ChapterRequest
from agent_runtime.narrative.production.writer_contract import validate_writer_v2_output
from agent_runtime.narrative.quality.prose_conventions import (
    evaluate_prose_conventions,
)


def test_chinese_dialogue_quotes_and_indirect_speech_pass() -> None:
    prose = (
        "# 第一章\n\n"
        "阿德里安说：“炉火不对。”\n\n"
        "凯恩知道阿德里安说炉火不对，却没有立刻回答。\n\n"
        "“你听见他说‘别碰灰烬’了吗？”莉亚问。\n"
    )

    report = evaluate_prose_conventions(prose)

    assert report["status"] == "pass"
    assert report["mechanical_status"] == "pass"
    assert report["writer_rerun_needed"] is False
    assert report["metrics"]["dialogue_quote_errors"] == 0


def test_clear_unquoted_direct_speech_blocks_writer_contract() -> None:
    report = evaluate_prose_conventions(
        "# 第一章\n\n阿德里安说：炉火不对，你必须马上离开。\n"
    )

    assert report["status"] == "blocked"
    assert report["mechanical_status"] == "blocked"
    assert report["writer_rerun_needed"] is True
    assert any(issue["id"] == "unquoted_direct_speech" for issue in report["issues"])


def test_ascii_quotes_around_chinese_dialogue_block() -> None:
    report = evaluate_prose_conventions('凯恩说："我不会把灰交给教会。"\n')

    assert report["status"] == "blocked"
    assert any(issue["id"] == "ascii_quote_for_chinese_dialogue" for issue in report["issues"])


def test_rhetorical_family_density_requests_local_revision() -> None:
    prose = (
        "不是火熄了，而是火忘了怎样燃烧。"
        + "灰" * 120
        + "不是风停了，而是风绕开了这间屋子。"
        + "灰" * 120
        + "不是影子动了，而是墙在缓慢呼吸。"
    )

    report = evaluate_prose_conventions(prose)

    assert report["status"] == "revision_required"
    assert report["mechanical_status"] == "pass"
    assert report["writer_rerun_needed"] is False
    assert any(issue["id"] == "rhetorical_family_cluster" for issue in report["issues"])


def test_code_fences_and_markdown_headings_are_excluded() -> None:
    prose = '# 阿德里安说：炉火不对\n\n```text\n凯恩说：离开这里\n```\n\n叙述继续。\n'

    report = evaluate_prose_conventions(prose)

    assert report["status"] == "pass"


def test_writer_contract_blocks_quotes_but_leaves_rhetoric_for_editor() -> None:
    dialogue = validate_writer_v2_output(
        {"fiction_draft.md": "阿德里安说：你必须在天亮前离开。\n"},
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-dialogue",
    )
    rhetoric = validate_writer_v2_output(
        {
            "fiction_draft.md": (
                "不是火熄了，而是火忘了燃烧。"
                + "灰" * 120
                + "不是风停了，而是风绕开了屋子。"
                + "灰" * 120
                + "不是影子动了，而是墙在呼吸。"
            )
        },
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-rhetoric",
    )

    assert dialogue["status"] == "blocked"
    assert dialogue["prose_conventions"]["writer_rerun_needed"] is True
    assert rhetoric["status"] == "pass"
    assert rhetoric["prose_conventions"]["status"] == "revision_required"


def test_chapter_engine_requests_writer_rerun_for_mechanical_dialogue(
    tmp_path: Path,
) -> None:
    source = tmp_path / "chapter-contract.yml"
    source.write_text("chapter: 1\n", encoding="utf-8")
    source_path = str(source.resolve())
    outcome = ChapterEngine.run(
        ChapterRequest(
            chapter_id=1,
            creative_brief={
                "schema_version": 2,
                "chapter_id": 1,
                "primary_function": "plot",
                "pov": "char_kain",
                "opposing_wants": "验证灰痕与避开教会登记之间的冲突",
                "turn": "名单提前出现凯恩的名字",
                "cost": "他必须放弃铁匠身份",
                "reader_question": "是谁提前登记了凯恩？",
                "must_preserve": [],
                "creative_freedom": [],
                "source_hashes": {
                    source_path: hashlib.sha256(source.read_bytes()).hexdigest()
                },
            },
            writer_output={
                "fiction_draft.md": "阿德里安说：你必须在天亮前离开。\n"
            },
            provider="deepseek",
            model="deepseek-v4-pro",
            call_id="call-engine-dialogue",
        )
    )

    assert outcome.status == "blocked"
    assert outcome.writer_rerun_needed is True
