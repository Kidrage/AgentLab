"""Verify HTML-style AGENTLAB_EDIT blocks are parsed and merged correctly."""
from pathlib import Path
from agent_runtime.patch_applicator import apply_all_patches, parse_edit_blocks, strip_edit_blocks_from_report


def test_html_block_parsed():
    html_block = """<!-- AGENTLAB_EDIT: agent_docs/02_TASK_LEDGER.yml -->
```yaml
task_test:
  status: complete
```
<!-- END AGENTLAB_EDIT -->"""
    blocks = parse_edit_blocks(html_block)
    assert len(blocks) == 1
    assert blocks[0]["path"] == "agent_docs/02_TASK_LEDGER.yml"
    assert "html_block_content" in blocks[0]


def test_mixed_blocks_parsed():
    sr_marker = "------- SEARCH"
    eq_marker = "======="
    rp_marker = "+++++++ REPLACE"
    mixed = f"""text
<<<AGENTLAB_EDIT agent_docs/03_DECISION_LOG.md
{sr_marker}
old
{eq_marker}
new
{rp_marker}
>>>
more
<!-- AGENTLAB_EDIT: agent_docs/02_TASK_LEDGER.yml -->
key: val
<!-- END AGENTLAB_EDIT -->"""
    blocks = parse_edit_blocks(mixed)
    assert len(blocks) == 2
    sr = [b for b in blocks if "html_block_content" not in b]
    html = [b for b in blocks if "html_block_content" in b]
    assert len(sr) == 1
    assert len(html) == 1
    assert sr[0]["search_replace_pairs"]


def test_strip_removes_both_styles():
    mixed = "Hello. <<<AGENTLAB_EDIT x\n>>> bye <!-- AGENTLAB_EDIT: y -->\nz\n<!-- END AGENTLAB_EDIT -->"
    cleaned = strip_edit_blocks_from_report(mixed)
    assert "<<<" not in cleaned
    assert "AGENTLAB_EDIT" not in cleaned
    assert "Hello" in cleaned


def test_html_block_applies_full_file_with_optional_fence(tmp_path: Path):
    llm_output = """Draft done.

<!-- AGENTLAB_EDIT: drafts/chapter.md -->
```markdown
# Chapter

New prose.
```
<!-- END AGENTLAB_EDIT -->
"""

    results = apply_all_patches(
        llm_output=llm_output,
        project_root=tmp_path,
        allowed_files={"drafts/chapter.md"},
    )

    assert len(results) == 1
    assert results[0].success is True
    assert (tmp_path / "drafts" / "chapter.md").read_text(encoding="utf-8") == "# Chapter\n\nNew prose.\n"
    assert (tmp_path / "drafts" / "after_diff_drafts_chapter.md.patch").exists()


def test_html_block_respects_allowed_files(tmp_path: Path):
    llm_output = """<!-- AGENTLAB_EDIT: drafts/chapter.md -->
Not allowed.
<!-- END AGENTLAB_EDIT -->"""

    results = apply_all_patches(
        llm_output=llm_output,
        project_root=tmp_path,
        allowed_files={"drafts/other.md"},
    )

    assert len(results) == 1
    assert results[0].success is False
    assert "Supervisor-approved scope" in (results[0].error or "")
    assert not (tmp_path / "drafts" / "chapter.md").exists()


def test_real_task_0032_archivist_output():
    agentlab_root = Path(__file__).resolve().parents[1]
    content = (agentlab_root / "tests/fixtures/html_archivist/blocked_Archivist.md").read_text()
    blocks = parse_edit_blocks(content)
    assert len(blocks) >= 1, f"Expected at least 1 HTML block, got {len(blocks)}"
    html_blocks = [b for b in blocks if "html_block_content" in b]
    assert len(html_blocks) >= 1, "Expected HTML-style block in task_0032 output"
