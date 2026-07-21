from pathlib import Path
import hashlib
import os
import subprocess

import yaml
import pytest
from click.utils import strip_ansi

from agent_runtime.narrative.assembly import (
    NarrativeAssemblyError,
    assemble_candidate_chapters,
)


def _chapter(root: Path, task_id: str, text: str) -> tuple[str, str]:
    path = root / "projects" / "Crown_of_Ash" / "runs" / task_id / "fiction_draft.md"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path.relative_to(root).as_posix(), hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_assemble_uses_only_hash_bound_audited_candidates_in_chapter_order(
    tmp_path: Path,
) -> None:
    ch2_path, ch2_hash = _chapter(tmp_path, "chapter-02", "# 第二章 灰烬来信\n\n第二章正文。\n")
    ch1_path, ch1_hash = _chapter(tmp_path, "chapter-01", "# 第一章 黑盐港\n\n第一章正文。\n")
    audit_path = tmp_path / "audit.yml"
    audit_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "project": "Crown_of_Ash",
                "status": "pass",
                "candidate_only": True,
                "continuous_review": True,
                "chapter_range": [1, 2],
                "chapters": [
                    {"chapter": 2, "task_id": "chapter-02", "path": ch2_path, "sha256": ch2_hash},
                    {"chapter": 1, "task_id": "chapter-01", "path": ch1_path, "sha256": ch1_hash},
                ],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "Crown_of_Ash_Ch01-Ch02_合订本.txt"
    manifest = tmp_path / "delivery.yml"

    result = assemble_candidate_chapters(
        tmp_path,
        project="Crown_of_Ash",
        audit_manifest=audit_path,
        output_path=output,
        delivery_manifest=manifest,
    )

    text = output.read_text(encoding="utf-8")
    assert text == "# 第一章 黑盐港\n\n第一章正文。\n\n# 第二章 灰烬来信\n\n第二章正文。\n"
    assert text.index("第一章") < text.index("第二章")
    assert "task_id" not in text
    assert result["status"] == "assembled"
    assert result["chapter_count"] == 2
    assert [item["title"] for item in result["chapters"]] == ["第一章 黑盐港", "第二章 灰烬来信"]
    assert result["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert yaml.safe_load(manifest.read_text(encoding="utf-8")) == result


def test_assemble_fails_before_writing_when_candidate_hash_changed(tmp_path: Path) -> None:
    source_path, source_hash = _chapter(
        tmp_path, "chapter-01", "# 第一章 黑盐港\n\n第一章正文。\n"
    )
    audit_path = tmp_path / "audit.yml"
    audit_path.write_text(
        yaml.safe_dump(
            {
                "project": "Crown_of_Ash",
                "status": "pass",
                "candidate_only": True,
                "continuous_review": True,
                "chapter_range": [1, 1],
                "chapters": [
                    {
                        "chapter": 1,
                        "task_id": "chapter-01",
                        "path": source_path,
                        "sha256": source_hash,
                    }
                ],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / source_path).write_text("# 第一章 被篡改\n\nchanged\n", encoding="utf-8")
    output = tmp_path / "omnibus.txt"
    manifest = tmp_path / "delivery.yml"

    with pytest.raises(NarrativeAssemblyError, match="hash mismatch"):
        assemble_candidate_chapters(
            tmp_path,
            project="Crown_of_Ash",
            audit_manifest=audit_path,
            output_path=output,
            delivery_manifest=manifest,
        )

    assert not output.exists()
    assert not manifest.exists()


def test_assemble_rejects_duplicate_titles(tmp_path: Path) -> None:
    ch1_path, ch1_hash = _chapter(
        tmp_path, "chapter-01", "# 第一章 同名\n\n正文一。\n"
    )
    ch2_path, ch2_hash = _chapter(
        tmp_path, "chapter-02", "# 第一章 同名\n\n正文二。\n"
    )
    audit = tmp_path / "audit.yml"
    audit.write_text(
        yaml.safe_dump(
            {
                "project": "Crown_of_Ash",
                "status": "pass",
                "candidate_only": True,
                "continuous_review": True,
                "chapter_range": [1, 2],
                "chapters": [
                    {"chapter": 1, "task_id": "chapter-01", "path": ch1_path, "sha256": ch1_hash},
                    {"chapter": 2, "task_id": "chapter-02", "path": ch2_path, "sha256": ch2_hash},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(NarrativeAssemblyError, match="duplicate chapter title"):
        assemble_candidate_chapters(
            tmp_path,
            project="Crown_of_Ash",
            audit_manifest=audit,
            output_path=tmp_path / "omnibus.txt",
            delivery_manifest=tmp_path / "delivery.yml",
        )


def test_narrative_assemble_cli_is_registered() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "agentlab.sh"), "narrative", "assemble", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if key not in {"FORCE_COLOR", "CLICOLOR_FORCE"}
            },
            "COLUMNS": "180",
            "NO_COLOR": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    stdout = strip_ansi(result.stdout)
    assert "--audit-manifest" in stdout
    assert "--output" in stdout
