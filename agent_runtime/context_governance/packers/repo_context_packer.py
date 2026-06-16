from __future__ import annotations

from pathlib import Path

from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class RepoContextPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        manifest = source_ref(run_dir, "repo_manifest.json")
        sections = [
            section("repo_manifest_summary", "Repo manifest summary", "Repository context is represented by manifest/index references, not a full repo dump.", [manifest]),
            section("changed_files", "Changed files if known", "Changed files are read from git/task artifacts when available; otherwise this is an explicit placeholder.", [source_ref(run_dir, "git_status.txt")]),
            section("test_failure_summary", "Test failure summary if known", "Pytest/CI failures should be included as extractive snippets only when present.", [source_ref(run_dir, "07_validation_report.md")]),
            section("symbols_index", "Symbols/index placeholder", "Symbol and dependency index placeholder. P2-G does not perform heavy repo indexing.", [source_ref(run_dir, "repo_index.yml")]),
        ]
        return make_pack(profile, budget, sections,
            omitted_sections=[omitted("No default full repo loading; drill down by file ref.", "repo://full")],
            externalized=[external(manifest, "full_file", "Raw repo manifest/file contents remain externalized.")],
            evidence_refs=[evidence(manifest, "repo_manifest")],
            warnings=["Code/config/test context forbids lossy rewriting; use refs/extractive snippets."],
        )