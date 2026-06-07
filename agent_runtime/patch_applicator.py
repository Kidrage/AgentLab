"""Patch applicator: parses SEARCH/REPLACE blocks from LLM output and applies them to real files.

This is the bridge between AgentLab's API-based brain agents and actual filesystem mutation.
When Coder (or any agent) runs via a model API, it can include SEARCH/REPLACE blocks in its
output. The applicator parses these blocks, validates paths against the Supervisor-approved
scope, and applies the edits.

Block format in LLM output:
```
<<<AGENTLAB_EDIT path/to/file.py
------- SEARCH
original content to find
=======
replacement content
+++++++ REPLACE
>>>
```

Multiple edits can appear in a single response. Each edit is validated and applied independently.

The applicator returns a list of applied edits with success/failure status, line numbers,
and any warnings (e.g., only the first match was replaced when multiple existed).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import yaml


@dataclass
class AppliedEdit:
    path: str
    success: bool
    line_start: int | None = None
    line_end: int | None = None
    matched_count: int = 0
    warning: str | None = None
    error: str | None = None


EDIT_BLOCK_PATTERN = re.compile(
    r'<<<AGENTLAB_EDIT\s+(.+?)\n(.*?)>>>',
    re.DOTALL,
)

# HTML-comment-style fallback pattern, e.g.:
# <!-- AGENTLAB_EDIT: agent_docs/02_TASK_LEDGER.yml -->
# ```yaml
# ...
# ```
# <!-- END AGENTLAB_EDIT -->
HTML_EDIT_BLOCK_PATTERN = re.compile(
    r'<!--\s*AGENTLAB_EDIT\s*:\s*(.+?)-->\s*\n(.*?)\n\s*<!--\s*END\s+AGENTLAB_EDIT\s*-->',
    re.DOTALL,
)

SEARCH_REPLACE_PATTERN = re.compile(
    r'-------\s*SEARCH\s*\n(.*?)\n\s*=======\s*\n(.*?)\n\s*\+\+\+\+\+\+\+\s*REPLACE',
    re.DOTALL,
)


def parse_edit_blocks(llm_output: str) -> list[dict]:
    """Parse AGENTLAB_EDIT blocks from LLM output text.

    Supports two formats:
    1. <<<AGENTLAB_EDIT path >>> with SEARCH/REPLACE pairs
    2. <!-- AGENTLAB_EDIT: path --> with content block ending in <!-- END AGENTLAB_EDIT -->

    Returns a list of dicts with keys: path, search_replace_pairs (list of (search, replace) tuples),
    and optionally 'html_block_content' for HTML-style blocks (treated as raw replacement content).
    """
    blocks = []

    # Primary <<< >>> format with SEARCH/REPLACE pairs
    for match in EDIT_BLOCK_PATTERN.finditer(llm_output):
        file_path = match.group(1).strip()
        block_content = match.group(2)

        sr_pairs = []
        for sr_match in SEARCH_REPLACE_PATTERN.finditer(block_content):
            search = sr_match.group(1)
            replace = sr_match.group(2)
            sr_pairs.append((search, replace))

        if sr_pairs:
            blocks.append({
                "path": file_path,
                "search_replace_pairs": sr_pairs,
            })

    # HTML comment style: <!-- AGENTLAB_EDIT: path --> content <!-- END AGENTLAB_EDIT -->
    for match in HTML_EDIT_BLOCK_PATTERN.finditer(llm_output):
        file_path = match.group(1).strip()
        raw_content = match.group(2).strip()

        if raw_content:
            blocks.append({
                "path": file_path,
                "search_replace_pairs": [],
                "html_block_content": raw_content,
            })

    return blocks


def _find_line_range(lines: list[str], search_text: str) -> tuple[int | None, int | None]:
    """Find the line range of search_text in lines.

    Returns (start_line, end_line) as 1-based line numbers, or (None, None) if not found.
    """
    search_lines = search_text.splitlines()
    if not search_lines:
        return None, None

    # Strip trailing whitespace from search_lines for matching
    search_clean = [l.rstrip() for l in search_lines]

    for i in range(len(lines)):
        # Check if search_lines matches starting at line i
        if i + len(search_clean) > len(lines):
            continue
        match = True
        for j, search_line in enumerate(search_clean):
            if not search_line:
                # Empty lines in search: match any empty or whitespace-only line
                if lines[i + j].strip():
                    match = False
                    break
            elif lines[i + j].rstrip() != search_line:
                match = False
                break
        if match:
            return i + 1, i + len(search_lines)

    return None, None


def apply_single_search_replace(
    lines: list[str],
    search_text: str,
    replace_text: str,
    replace_all: bool = False,
) -> tuple[list[str], int, int | None, int | None]:
    """Apply one search/replace operation to lines.

    Returns (new_lines, match_count, first_start, first_end).
    """
    search_lines = search_text.splitlines()
    search_clean = [l.rstrip() if l else l for l in search_lines]
    replace_lines = replace_text.splitlines()

    new_lines: list[str] = []
    i = 0
    match_count = 0
    first_start: int | None = None
    first_end: int | None = None

    while i < len(lines):
        matched = False
        if i + len(search_clean) <= len(lines):
            crt_match = True
            for j, search_line in enumerate(search_clean):
                if not search_line:
                    if lines[i + j].strip():
                        crt_match = False
                        break
                elif lines[i + j].rstrip() != search_line:
                    crt_match = False
                    break
            if crt_match:
                matched = True
                match_count += 1
                if first_start is None:
                    first_start = i + 1  # 1-based
                    first_end = i + len(search_lines)  # 1-based

                new_lines.extend(replace_lines)

                # If the last replacement line doesn't end with newline, keep
                # the original line ending of the next line if applicable
                if replace_lines and not replace_lines[-1].endswith('\n'):
                    pass  # we already added it

                i += len(search_lines)

                if not replace_all:
                    # Add remaining lines
                    new_lines.extend(lines[i:])
                    return new_lines, match_count, first_start, first_end

                continue

        if not matched:
            new_lines.append(lines[i])
            i += 1

    return new_lines, match_count, first_start, first_end


def apply_edit_block(
    file_path: str,
    search_replace_pairs: list[tuple[str, str]],
    allowed_root: Path,
    allowed_files: set[str] | None = None,
) -> AppliedEdit:
    """Apply a parsed edit block to a real file.

    Args:
        file_path: Relative path from the repo/project root.
        search_replace_pairs: List of (search_content, replace_content) tuples.
        allowed_root: The root directory for path validation.
        allowed_files: Optional set of allowed file paths. If set, file_path must be in it.

    Returns:
        AppliedEdit with success/failure details.
    """
    from policies import assert_path_allowed

    normalized_path = file_path.lstrip("/")
    if allowed_files is not None and normalized_path not in allowed_files:
        return AppliedEdit(
            path=normalized_path,
            success=False,
            error=f"File not in Supervisor-approved scope: {normalized_path}. Allowed: {sorted(allowed_files)}",
        )

    try:
        target = assert_path_allowed(allowed_root / normalized_path, allowed_root)
    except Exception as exc:
        return AppliedEdit(path=normalized_path, success=False, error=str(exc))

    if not target.exists():
        return AppliedEdit(path=normalized_path, success=False, error=f"File does not exist: {target}")

    try:
        original_text = target.read_text(encoding="utf-8")
        lines = original_text.splitlines(keepends=True)
    except Exception as exc:
        return AppliedEdit(path=normalized_path, success=False, error=f"Read error: {exc}")

    total_matches = 0
    first_start = None
    first_end = None
    warnings: list[str] = []
    current_lines = lines

    for idx, (search_text, replace_text) in enumerate(search_replace_pairs):
        try:
            current_lines, matches, start, end = apply_single_search_replace(
                current_lines, search_text, replace_text, replace_all=False
            )
            total_matches += matches
            if matches == 0:
                warnings.append(f"SEARCH/REPLACE pair #{idx + 1}: no match found in file")
            elif matches > 1:
                warnings.append(f"SEARCH/REPLACE pair #{idx + 1}: {matches} matches found, only first replaced")
            if start is not None and first_start is None:
                first_start = start
                first_end = end
        except Exception as exc:
            return AppliedEdit(
                path=normalized_path,
                success=False,
                error=f"Failed applying SEARCH/REPLACE pair #{idx + 1}: {exc}",
                matched_count=total_matches,
            )

    if total_matches == 0:
        return AppliedEdit(
            path=normalized_path,
            success=False,
            error="No SEARCH/REPLACE blocks matched. File unchanged.",
            matched_count=0,
        )

    try:
        new_content = "".join(current_lines)
        target.write_text(new_content, encoding="utf-8")
    except Exception as exc:
        return AppliedEdit(
            path=normalized_path,
            success=False,
            error=f"Write error: {exc}",
            matched_count=total_matches,
        )

    # ── P2-3: Write before/after diffs and patch apply report ──
    _save_patch_evidence(
        target, original_text, new_content, normalized_path,
        total_matches, warnings,
    )

    warning_msg = "; ".join(warnings[:3]) if warnings else None
    if len(warnings) > 3:
        warning_msg += f" (and {len(warnings) - 3} more)"

    return AppliedEdit(
        path=normalized_path,
        success=True,
        line_start=first_start,
        line_end=first_end,
        matched_count=total_matches,
        warning=warning_msg,
    )


def apply_all_patches(
    llm_output: str,
    project_root: Path,
    allowed_files: set[str] | None = None,
) -> list[AppliedEdit]:
    """Parse and apply all edit blocks from an LLM output string.

    This is the main entry point for the patch applicator. It:
    1. Parses SEARCH/REPLACE blocks from the LLM output
    2. Validates each target file against the allowed scope
    3. Applies edits to the real filesystem
    4. Returns a list of AppliedEdit results

    Args:
        llm_output: The raw text output from an LLM API call.
        project_root: The project root directory for path validation.
        allowed_files: Optional set of file paths that may be edited.

    Returns:
        List of AppliedEdit objects, one per file.
    """
    blocks = parse_edit_blocks(llm_output)
    results: list[AppliedEdit] = []

    for block in blocks:
        result = apply_edit_block(
            file_path=block["path"],
            search_replace_pairs=block["search_replace_pairs"],
            allowed_root=project_root,
            allowed_files=allowed_files,
        )
        results.append(result)

    return results


def strip_edit_blocks_from_report(llm_output: str) -> str:
    """Remove AGENTLAB_EDIT blocks from report text, keeping only the readable portion."""
    cleaned = EDIT_BLOCK_PATTERN.sub("", llm_output)
    cleaned = HTML_EDIT_BLOCK_PATTERN.sub("", cleaned)
    return cleaned.strip()


def _save_patch_evidence(
    target: Path,
    original_content: str,
    new_content: str,
    normalized_path: str,
    total_matches: int,
    warnings: list[str],
) -> None:
    """P2-3: Save before/after diffs and a patch_apply_report.yml alongside the file."""
    evidence_dir = target.parent
    safe_name = normalized_path.replace("/", "_").replace("\\", "_")
    timestamp = datetime.now(timezone.utc).isoformat()

    # Before diff
    before_diff = "\n".join(
        difflib.unified_diff(
            original_content.splitlines(keepends=True),
            original_content.splitlines(keepends=True),
            fromfile=f"a/{normalized_path}",
            tofile=f"b/{normalized_path}",
            lineterm="",
        )
    )
    before_path = evidence_dir / f"before_diff_{safe_name}.patch"
    before_path.write_text(before_diff or "(no changes — before snapshot)\n", encoding="utf-8")

    # After diff
    after_diff = "\n".join(
        difflib.unified_diff(
            original_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{normalized_path}",
            tofile=f"b/{normalized_path}",
            lineterm="",
        )
    )
    after_path = evidence_dir / f"after_diff_{safe_name}.patch"
    after_path.write_text(after_diff or "(no changes)\n", encoding="utf-8")

    # Patch apply report
    report_path = evidence_dir / f"patch_apply_report_{safe_name}.yml"
    report = {
        "version": 1,
        "file": normalized_path,
        "applied_at": timestamp,
        "total_matches": total_matches,
        "warnings": warnings,
        "evidence": {
            "before_diff": str(before_path),
            "after_diff": str(after_path),
        },
    }
    report_path.write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
